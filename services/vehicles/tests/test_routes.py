"""HTTP tests of the vehicles service: the real Flask app and routes, with an in-memory
repository (tests/fakes.py) instead of SQL Server.

Run with:
    uv run pytest tests/test_routes.py -v
"""
import logging
from datetime import date, timedelta

import pymssql
import pytest

from app.db import DatabaseUnavailable
from conftest import UI_ORIGIN

NEW_VEHICLE = {
    "reg_num": "NEWVIN0000000001", "type": "car", "brand": "Kia", "model": "Rio",
    "plate": "9999 ZZZ", "location": "valencia", "fuel": "hybrid", "transmission": "automatic",
    "seat_num": 5, "manufacture_date": "2024-01-10", "km": 1200, "daily_rate": 31.25,
    "category": "midsize",
}


def error(response):
    assert response.is_json, response.data
    return response.get_json()["error"]


# ---------------------------------------------------------------------------
# meta, stats, health
# ---------------------------------------------------------------------------

class TestMetaStatsHealth:
    def test_meta_lists_the_allowed_values(self, client):
        body = client.get("/meta").get_json()
        assert "madrid" in body["locations"] and "mini" in body["types"]
        assert body["statuses"] == ["active", "maintenance", "retired"]
        assert body["sort_options"] == ["price_asc", "price_desc", "km_asc", "km_desc"]

    def test_stats(self, client, store):
        store.add(reg_num="A")
        store.add(reg_num="B", status="maintenance")
        assert client.get("/stats").get_json() == {
            "total_vehicles": 2, "available_vehicles": 1, "pending_trips": 0}

    def test_health_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.get_json() == {
            "service": "vehicles", "version": "abc1234", "status": "ok", "database": "ok"}

    @pytest.mark.parametrize("problem", [False, DatabaseUnavailable("paused"), RuntimeError("x")])
    def test_health_reports_a_database_problem_as_503(self, client, store, problem):
        store.ping_result = problem
        response = client.get("/health")
        assert response.status_code == 503
        assert response.get_json()["database"] == "down"
        assert "paused" not in response.get_data(as_text=True)  # no internal details


# ---------------------------------------------------------------------------
# GET /vehicles
# ---------------------------------------------------------------------------

class TestListVehicles:
    def test_default_page(self, client, store):
        store.add(reg_num="A")
        body = client.get("/vehicles").get_json()
        assert body["total"] == 1 and body["limit"] == 100 and body["offset"] == 0
        assert body["items"][0]["reg_num"] == "A"

    def test_filters(self, client, store):
        store.add(reg_num="A", location="madrid", fuel="diesel")
        store.add(reg_num="B", location="madrid", fuel="petrol")
        store.add(reg_num="C", location="sevilla", fuel="diesel")
        body = client.get("/vehicles?location=madrid&fuel=diesel").get_json()
        assert [v["reg_num"] for v in body["items"]] == ["A"] and body["total"] == 1

    def test_sort_and_paging(self, client, store):
        for i, rate in enumerate([30, 10, 20]):
            store.add(reg_num=f"V{i}", daily_rate=rate)
        body = client.get("/vehicles?sort_by=price_asc&limit=2&offset=1").get_json()
        assert [v["daily_rate"] for v in body["items"]] == [20, 30]
        assert body["total"] == 3

    @pytest.mark.parametrize("query", [
        "status=sold", "location=paris", "sort_by=name", "limit=0", "limit=501", "limit=x",
        "offset=-1",
    ])
    def test_bad_queries_are_400(self, client, query):
        response = client.get(f"/vehicles?{query}")
        assert response.status_code == 400 and error(response) in ("invalid_value", "invalid_query")


# ---------------------------------------------------------------------------
# GET /vehicles/<reg_num>  (what the reservations service calls)
# ---------------------------------------------------------------------------

class TestGetVehicle:
    def test_found(self, client, store):
        store.add(reg_num="A1")
        response = client.get("/vehicles/A1")
        assert response.status_code == 200 and response.get_json()["reg_num"] == "A1"

    def test_not_found_is_404_json(self, client):
        response = client.get("/vehicles/NOPE")
        assert response.status_code == 404 and error(response) == "vehicle_not_found"


# ---------------------------------------------------------------------------
# POST /vehicles
# ---------------------------------------------------------------------------

class TestCreateVehicle:
    def test_created_with_defaults(self, client, store):
        response = client.post("/vehicles", json=NEW_VEHICLE)

        assert response.status_code == 201
        body = response.get_json()
        assert body["reg_num"] == NEW_VEHICLE["reg_num"]
        assert body["status"] == "active"                          # default
        assert body["registration_date"] == date.today().isoformat()  # default
        assert body["color"] is None
        assert store.events[:2] == ["commit", "rollback"] and store.events[-1] == "close"

    def test_optional_fields(self, client):
        body = client.post("/vehicles", json={
            **NEW_VEHICLE, "color": "Blue", "status": "maintenance",
            "registration_date": "2024-02-01",
        }).get_json()
        assert (body["color"], body["status"], body["registration_date"]) == (
            "Blue", "maintenance", "2024-02-01")

    @pytest.mark.parametrize("change, code", [
        ({"price": 1}, "invalid_field"),
        ({"brand": ""}, "missing_fields"),
        ({"km": None}, "missing_fields"),
        ({"type": "truck"}, "invalid_value"),
        ({"location": "paris"}, "invalid_value"),
        ({"seat_num": "5"}, "invalid_value"),
        ({"seat_num": True}, "invalid_value"),
        ({"km": -1}, "invalid_value"),
        ({"km": 10_000_001}, "invalid_value"),
        ({"daily_rate": 0}, "invalid_value"),
        ({"daily_rate": "31"}, "invalid_value"),
        ({"daily_rate": 100_000_000}, "invalid_value"),
        ({"reg_num": "X" * 33}, "invalid_value"),
        ({"plate": 1234}, "invalid_value"),
        ({"manufacture_date": "10/01/2024"}, "invalid_value"),
        ({"type": "mini"}, "invalid_vehicle"),          # a mini with 5 seats
        ({"seat_num": 7}, "invalid_vehicle"),           # a car with 7 seats
        ({"manufacture_date": "2015-01-01"}, "invalid_vehicle"),  # registered > 5 years later
        ({"manufacture_date": (date.today() + timedelta(days=30)).isoformat()}, "invalid_vehicle"),
    ])
    def test_invalid_vehicle_is_400_and_not_saved(self, client, store, change, code):
        response = client.post("/vehicles", json={**NEW_VEHICLE, **change})

        assert response.status_code == 400 and error(response) == code, response.get_json()
        assert store.vehicles == {} and "commit" not in store.events

    @pytest.mark.parametrize("body", ["not json", "[1, 2]", "null"])
    def test_body_must_be_a_json_object(self, client, body):
        response = client.post("/vehicles", data=body, content_type="application/json")
        assert response.status_code == 400 and error(response) == "invalid_body"

    def test_existing_reg_num_is_409(self, client, store):
        store.add(reg_num=NEW_VEHICLE["reg_num"])
        response = client.post("/vehicles", json=NEW_VEHICLE)
        assert response.status_code == 409 and error(response) == "vehicle_exists"

    def test_existing_plate_is_409(self, client, store):
        store.add(reg_num="OTHER", plate=NEW_VEHICLE["plate"])
        response = client.post("/vehicles", json=NEW_VEHICLE)
        assert response.status_code == 409 and "commit" not in store.events


# ---------------------------------------------------------------------------
# PATCH /vehicles/<reg_num>
# ---------------------------------------------------------------------------

class TestUpdateVehicle:
    def test_update(self, client, store):
        store.add(reg_num="A1")
        response = client.patch("/vehicles/A1", json={
            "daily_rate": 45.567, "status": "maintenance", "category": "luxury"})

        body = response.get_json()
        assert response.status_code == 200
        assert (body["daily_rate"], body["status"], body["category"]) == (
            45.57, "maintenance", "luxury")
        assert "commit" in store.events

    @pytest.mark.parametrize("body, code", [
        ({"location": "sevilla"}, "invalid_field"),   # only a transport moves a vehicle
        ({"km": 5}, "invalid_field"),
        ({"status": "sold"}, "invalid_value"),
        ({"daily_rate": -1}, "invalid_value"),
    ])
    def test_invalid_update_is_400(self, client, store, body, code):
        store.add(reg_num="A1")
        response = client.patch("/vehicles/A1", json=body)
        assert response.status_code == 400 and error(response) == code
        assert store.vehicles["A1"]["status"] == "active" and "commit" not in store.events

    def test_unknown_vehicle_is_404(self, client):
        response = client.patch("/vehicles/NOPE", json={"status": "maintenance"})
        assert response.status_code == 404 and error(response) == "vehicle_not_found"


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

class TestTransport:
    def test_first_vehicle_is_queued(self, client, store):
        store.add(reg_num="A")
        response = client.post("/transport", json={"reg_num": "A", "destination": "barcelona"})
        assert response.status_code == 202
        assert response.get_json() == {
            "reg_num": "A", "destination": "barcelona", "location": "madrid", "status": "queued"}
        assert client.get("/transport/queue").get_json() == {"trips": [{
            "mode": "truck", "origin": "madrid", "destination": "barcelona",
            "queued": 1, "needed": 4}]}

    def test_fourth_vehicle_sends_the_truck(self, client, store):
        for reg_num in "ABCD":
            store.add(reg_num=reg_num)
        for reg_num in "ABC":
            client.post("/transport", json={"reg_num": reg_num, "destination": "barcelona"})

        last = client.post("/transport", json={"reg_num": "D", "destination": "barcelona"})

        assert last.get_json()["status"] == "arrived"
        assert {v["location"] for v in store.vehicles.values()} == {"barcelona"}
        assert client.get("/transport/queue").get_json() == {"trips": []}

    @pytest.mark.parametrize("setup, body, status, code", [
        ({}, {"reg_num": "NOPE", "destination": "barcelona"}, 404, "vehicle_not_found"),
        ({"status": "maintenance"}, {"reg_num": "A", "destination": "barcelona"}, 409,
         "vehicle_not_active"),
        ({}, {"reg_num": "A", "destination": "madrid"}, 400, "same_location"),
        ({}, {"reg_num": "A", "destination": "paris"}, 400, "invalid_value"),
        ({}, {"reg_num": "A"}, 400, "invalid_value"),
        ({}, {"reg_num": "A", "destination": "barcelona", "x": 1}, 400, "invalid_field"),
    ])
    def test_refused_requests(self, client, store, setup, body, status, code):
        store.add(reg_num="A", **setup)
        response = client.post("/transport", json=body)
        assert response.status_code == status and error(response) == code
        assert store.queue == []

    def test_already_queued_is_409(self, client, store):
        store.add(reg_num="A")
        client.post("/transport", json={"reg_num": "A", "destination": "barcelona"})
        response = client.post("/transport", json={"reg_num": "A", "destination": "valencia"})
        assert response.status_code == 409 and error(response) == "already_queued"

    def test_busy_queue_is_503(self, client, store):
        store.add(reg_num="A")
        store.queue_busy = True
        response = client.post("/transport", json={"reg_num": "A", "destination": "barcelona"})
        assert response.status_code == 503 and error(response) == "queue_busy"


# ---------------------------------------------------------------------------
# Errors, connections, CORS and logs (the same for every route)
# ---------------------------------------------------------------------------

class TestCrossCutting:
    @pytest.mark.parametrize("failure", [
        DatabaseUnavailable("paused"), pymssql.OperationalError("lost"),
        pymssql.InterfaceError("down"),
    ])
    def test_unreachable_database_is_503_json(self, client, store, failure):
        store.fail_with = failure
        response = client.get("/vehicles")
        assert response.status_code == 503 and error(response) == "database_unavailable"

    def test_unexpected_error_is_500_without_details(self, client, store):
        store.fail_with = RuntimeError("secret detail /app/x.py")
        response = client.get("/vehicles")
        assert response.status_code == 500 and error(response) == "internal_error"
        assert "secret" not in response.get_data(as_text=True)

    def test_unknown_route_and_wrong_method_are_json(self, client):
        assert error(client.get("/nope")) == "not_found"
        assert error(client.delete("/vehicles/A")) == "method_not_allowed"

    def test_each_request_closes_its_connection_and_discards_uncommitted_work(
            self, client, store):
        store.add(reg_num="A")
        client.get("/vehicles/A")
        assert store.events == ["rollback", "close"]

    def test_ui_origin_is_allowed(self, client):
        response = client.get("/meta", headers={"Origin": UI_ORIGIN})
        assert response.headers["Access-Control-Allow-Origin"] == UI_ORIGIN

    def test_other_origins_are_not_allowed(self, client):
        response = client.get("/meta", headers={"Origin": "https://evil.example"})
        assert "Access-Control-Allow-Origin" not in response.headers

    def test_every_request_is_logged_without_the_query(self, client, caplog):
        with caplog.at_level(logging.INFO, logger="request"):
            client.get("/vehicles/NOPE?secret=1")
        lines = [r.getMessage() for r in caplog.records if r.name == "request"]
        assert len(lines) == 1 and lines[0].startswith("GET /vehicles/NOPE -> 404 in ")
        assert "secret" not in lines[0]