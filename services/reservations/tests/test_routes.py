"""HTTP tests of the reservations service: the real Flask app and routes, with an in-memory
repository and a fake vehicles service client (tests/fakes.py).

Run with:
    uv run pytest tests/test_routes.py -v
"""
import logging
from datetime import date, timedelta

import pymssql
import pytest

from app.db import DatabaseUnavailable
from conftest import UI_ORIGIN


def error(response):
    assert response.is_json, response.data
    return response.get_json()["error"]


def days(n):
    return (date.today() + timedelta(days=n)).isoformat()


def booking(**overrides):
    body = {"customer_id": 1, "car_reg_num": "A1", "start_date": days(3), "end_date": days(6)}
    body.update(overrides)
    return body


@pytest.fixture
def ready(store, vehicles):
    """Customer 1 and an active vehicle A1 at 20.50 a day."""
    store.add_customer(1)
    vehicles.add("A1", daily_rate=20.5)


# ---------------------------------------------------------------------------
# meta, stats, health
# ---------------------------------------------------------------------------

class TestMetaStatsHealth:
    def test_meta(self, client):
        body = client.get("/meta").get_json()
        assert body["rental_statuses"] == ["pending", "confirmed", "active", "returned", "canceled"]
        assert len(body["locations"]) == 7

    def test_stats(self, client, store):
        store.add_customer(1)
        store.add_rental(1, status="active")
        store.add_rental(2, status="returned")
        assert client.get("/stats").get_json() == {"active_rentals": 1, "total_customers": 1}

    def test_health_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.get_json() == {
            "service": "reservations", "version": "abc1234", "status": "ok", "database": "ok"}

    def test_health_does_not_depend_on_the_vehicles_service(self, client, vehicles):
        vehicles.down = "not reachable"
        assert client.get("/health").status_code == 200
        assert vehicles.calls == []

    @pytest.mark.parametrize("problem", [False, DatabaseUnavailable("paused"), RuntimeError("x")])
    def test_health_reports_a_database_problem_as_503(self, client, store, problem):
        store.ping_result = problem
        response = client.get("/health")
        assert response.status_code == 503 and response.get_json()["database"] == "down"


# ---------------------------------------------------------------------------
# customers (the "pick a customer" sign-in)
# ---------------------------------------------------------------------------

class TestCustomers:
    def test_list_with_search_and_location(self, client, store):
        store.add_customer(1, name="Liam", location="sevilla")
        store.add_customer(2, name="Ana", location="sevilla")
        store.add_customer(3, name="Liam", location="madrid")

        body = client.get("/customers?search=%20liam%20&location=sevilla").get_json()

        assert [c["id"] for c in body["items"]] == [1] and body["total"] == 1
        assert (body["limit"], body["offset"]) == (100, 0)

    def test_get_customer(self, client, store):
        store.add_customer(7)
        assert client.get("/customers/7").get_json()["id"] == 7

    def test_unknown_customer_is_404(self, client):
        response = client.get("/customers/99")
        assert response.status_code == 404 and error(response) == "customer_not_found"

    @pytest.mark.parametrize("query", [
        "location=paris", "limit=0", "limit=501", "offset=-1", "limit=abc", "search=" + "a" * 101,
    ])
    def test_bad_queries_are_400(self, client, query):
        response = client.get(f"/customers?{query}")
        assert response.status_code == 400 and error(response) == "invalid_query"


# ---------------------------------------------------------------------------
# GET /rentals
# ---------------------------------------------------------------------------

class TestListRentals:
    def test_filters(self, client, store):
        store.add_rental(1, customer_id=1, status="active")
        store.add_rental(2, customer_id=2, status="active")
        store.add_rental(3, customer_id=1, status="pending")

        body = client.get("/rentals?status=active&customer_id=1").get_json()

        assert [r["id"] for r in body["items"]] == [1] and body["total"] == 1

    def test_get_and_404(self, client, store):
        store.add_rental(5)
        assert client.get("/rentals/5").get_json()["id"] == 5
        assert error(client.get("/rentals/6")) == "rental_not_found"

    @pytest.mark.parametrize("query", [
        "status=lost", "customer_id=0", "customer_id=x", "limit=501",
    ])
    def test_bad_queries_are_400(self, client, query):
        assert client.get(f"/rentals?{query}").status_code == 400


# ---------------------------------------------------------------------------
# POST /rentals: the request that calls the vehicles service
# ---------------------------------------------------------------------------

class TestCreateRental:
    def test_created_with_price_from_the_vehicles_service(self, client, store, vehicles, ready):
        response = client.post("/rentals", json=booking())

        assert response.status_code == 201
        body = response.get_json()
        assert response.headers["Location"] == f"/rentals/{body['id']}"
        assert body["total_price"] == 61.5          # 3 days x 20.50, from the vehicles service
        assert body["status"] == "pending"
        assert vehicles.calls == ["A1"]
        assert "commit" in store.events

    def test_reg_num_is_trimmed_before_asking(self, client, vehicles, ready):
        client.post("/rentals", json=booking(car_reg_num="  A1 "))
        assert vehicles.calls == ["A1"]

    @pytest.mark.parametrize("change, code", [
        ({"total_price": 1}, "invalid_field"),       # the client never sets the price
        ({"status": "active"}, "invalid_field"),
        ({"end_date": None}, "missing_field"),
        ({"customer_id": "1"}, "invalid_value"),
        ({"customer_id": 0}, "invalid_value"),
        ({"car_reg_num": "X" * 33}, "invalid_value"),
        ({"start_date": "01/12/2026"}, "invalid_value"),
        ({"end_date": "2026-02-30"}, "invalid_value"),
        ({"start_date": days(3), "end_date": days(3)}, "invalid_rental"),
        ({"start_date": days(-1)}, "invalid_rental"),
    ])
    def test_bad_request_is_400_without_calling_vehicles(self, client, store, vehicles, ready,
                                                         change, code):
        response = client.post("/rentals", json=booking(**change))

        assert response.status_code == 400 and error(response) == code, response.get_json()
        assert vehicles.calls == [] and store.rentals == {}

    def test_body_must_be_a_json_object(self, client):
        response = client.post("/rentals", data="[]", content_type="application/json")
        assert response.status_code == 400 and error(response) == "invalid_json"

    def test_unknown_customer_is_404_without_calling_vehicles(self, client, vehicles, ready):
        response = client.post("/rentals", json=booking(customer_id=42))
        assert response.status_code == 404 and error(response) == "customer_not_found"
        assert vehicles.calls == []

    def test_unknown_vehicle_is_404(self, client, store, ready):
        response = client.post("/rentals", json=booking(car_reg_num="NOPE"))
        assert response.status_code == 404 and error(response) == "vehicle_not_found"
        assert store.rentals == {}

    def test_vehicle_not_active_is_409(self, client, store, vehicles, ready):
        vehicles.add("M1", status="maintenance")
        response = client.post("/rentals", json=booking(car_reg_num="M1"))
        assert response.status_code == 409 and error(response) == "vehicle_not_active"
        assert store.rentals == {}

    def test_vehicles_service_down_is_503_and_nothing_saved(self, client, store, vehicles, ready):
        vehicles.down = "timed out after 2s"

        response = client.post("/rentals", json=booking())

        assert response.status_code == 503 and error(response) == "vehicles_unavailable"
        assert "timed out" in response.get_json()["message"]
        assert store.rentals == {} and "commit" not in store.events

    def test_customer_deleted_meanwhile_is_404(self, client, store, ready):
        store.insert_error = pymssql.IntegrityError("FK")
        response = client.post("/rentals", json=booking())
        assert response.status_code == 404 and "commit" not in store.events


# ---------------------------------------------------------------------------
# PATCH /rentals/<id> and the customer's cancel
# ---------------------------------------------------------------------------

class TestChangeRental:
    def test_status_change(self, client, store):
        store.add_rental(1, status="pending")
        response = client.patch("/rentals/1", json={"status": "confirmed"})
        assert response.status_code == 200 and response.get_json()["status"] == "confirmed"
        assert "commit" in store.events

    def test_new_end_date_recalculates_the_price(self, client, store):
        store.add_rental(1, status="active", start_date="2026-12-01", end_date="2026-12-04",
                         total_price=61.5)
        body = client.patch("/rentals/1", json={"end_date": "2026-12-06"}).get_json()
        assert (body["end_date"], body["total_price"]) == ("2026-12-06", 102.5)

    @pytest.mark.parametrize("status, body, http, code", [
        ("pending", {"status": "returned"}, 409, "invalid_change"),
        ("canceled", {"status": "active"}, 409, "invalid_change"),
        ("returned", {"end_date": "2026-12-09"}, 409, "invalid_change"),
        ("pending", {"end_date": "2026-12-01"}, 400, "invalid_rental"),
        ("pending", {"status": "lost"}, 400, "invalid_value"),
        ("pending", {"end_date": "tomorrow"}, 400, "invalid_value"),
        ("pending", {"total_price": 1}, 400, "invalid_field"),
        ("pending", {}, 400, "missing_field"),
    ])
    def test_refused_changes(self, client, store, status, body, http, code):
        store.add_rental(1, status=status)
        response = client.patch("/rentals/1", json=body)
        assert response.status_code == http and error(response) == code
        assert store.rentals[1]["status"] == status and "commit" not in store.events

    def test_unknown_rental_is_404(self, client):
        assert client.patch("/rentals/9", json={"status": "confirmed"}).status_code == 404

    @pytest.mark.parametrize("status", ["pending", "confirmed", "active"])
    def test_customer_cancels_own_rental(self, client, store, status):
        store.add_rental(1, customer_id=3, status=status)
        response = client.post("/rentals/1/cancel", json={"customer_id": 3})
        assert response.status_code == 200 and response.get_json()["status"] == "canceled"

    def test_cannot_cancel_someone_elses_rental(self, client, store):
        store.add_rental(1, customer_id=3)
        response = client.post("/rentals/1/cancel", json={"customer_id": 4})
        assert response.status_code == 403 and error(response) == "not_your_rental"
        assert store.rentals[1]["status"] == "pending"

    @pytest.mark.parametrize("status", ["returned", "canceled"])
    def test_finished_rental_cannot_be_canceled(self, client, store, status):
        store.add_rental(1, customer_id=3, status=status)
        response = client.post("/rentals/1/cancel", json={"customer_id": 3})
        assert response.status_code == 409 and error(response) == "invalid_change"

    @pytest.mark.parametrize("body", [{}, {"customer_id": "3"}, {"customer_id": 3, "x": 1}])
    def test_cancel_needs_a_valid_customer_id(self, client, store, body):
        store.add_rental(1, customer_id=3)
        assert client.post("/rentals/1/cancel", json=body).status_code == 400


# ---------------------------------------------------------------------------
# Errors, connections, CORS and logs
# ---------------------------------------------------------------------------

class TestCrossCutting:
    def test_unreachable_database_is_503_json(self, client, store):
        store.fail_with = DatabaseUnavailable("paused")
        response = client.get("/customers")
        assert response.status_code == 503 and error(response) == "database_unavailable"

    def test_unexpected_error_is_500_without_details(self, client, store):
        store.fail_with = RuntimeError("secret detail")
        response = client.get("/customers")
        assert response.status_code == 500 and "secret" not in response.get_data(as_text=True)

    def test_unknown_route_is_json_404(self, client):
        assert error(client.get("/nope")) == "not_found"

    def test_each_request_closes_its_connection(self, client, store):
        client.get("/customers")
        assert store.events == ["rollback", "close"]

    def test_cors(self, client):
        allowed = client.get("/meta", headers={"Origin": UI_ORIGIN})
        other = client.get("/meta", headers={"Origin": "https://evil.example"})
        assert allowed.headers["Access-Control-Allow-Origin"] == UI_ORIGIN
        assert "Access-Control-Allow-Origin" not in other.headers

    def test_requests_are_logged(self, client, caplog):
        with caplog.at_level(logging.INFO, logger="request"):
            client.get("/rentals/77")
        assert [r.getMessage() for r in caplog.records if r.name == "request"][0].startswith(
            "GET /rentals/77 -> 404 in ")