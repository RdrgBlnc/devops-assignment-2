"""Cross-service test: the reservations app with its REAL HTTP client, talking over a real
network connection to a stand-in vehicles service (a small HTTP server started here).

Everything on the reservations side is real: config, VehiclesClient (requests, timeout,
URL encoding), the booking route and the error handling. Only the vehicles service is
replaced, so each of its possible answers can be produced on purpose: a vehicle, 404,
a 500, a slow answer, a broken body, or no service at all.

Run with:
    uv run pytest tests/test_vehicles_integration.py -v
"""
import json
import threading
import time
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

import pytest
import requests

from app import create_app
from app.clients.vehicles import VehiclesClient, VehiclesUnavailable
from app.config import load_config

TIMEOUT_S = 0.5


class StubVehicles:
    """A stand-in vehicles service on a free local port.

    `answers` maps a reg_num to (HTTP status, body, delay in seconds); a reg_num that is
    not listed gets the real service's 404 answer.
    """

    def __init__(self):
        self.answers = {}
        self.requests = []  # (method, raw path) of every request received
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                stub.requests.append(("GET", self.path))
                reg_num = unquote(self.path.removeprefix("/vehicles/"))
                status, body, delay = stub.answers.get(reg_num, (
                    404, {"error": "vehicle_not_found",
                          "message": f"No vehicle with reg_num '{reg_num}'"}, 0))
                time.sleep(delay)
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except ConnectionError:  # broken pipe, reset, or aborted on Windows
                    pass  # the client gave up waiting (the timeout test)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        ).start()

    def vehicle(self, reg_num, status="active", daily_rate=20.5, delay=0):
        """Answer like the real GET /vehicles/<reg_num> (same fields)."""
        self.answers[reg_num] = (200, {
            "reg_num": reg_num, "type": "car", "brand": "Toyota", "model": "Corolla",
            "category": "economy", "daily_rate": daily_rate, "seat_num": 5, "plate": "1234 ABC",
            "color": "White", "fuel": "petrol", "transmission": "manual", "km": 18500,
            "status": status, "location": "madrid", "manufacture_date": "2023-05-01",
            "registration_date": "2023-06-15",
        }, delay)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def stub():
    server = StubVehicles()
    yield server
    server.stop()


def make_client(store, vehicles_url):
    config = load_config({
        "DATABASE_URL": "mssql+pymssql://user:pass@db:1433/reservations",
        "VEHICLES_URL": vehicles_url,
        "VEHICLES_TIMEOUT_S": str(TIMEOUT_S),
    })
    # no vehicles_client passed: the app builds the real VehiclesClient from the config
    app = create_app(config, database=object(), migrate=False, repo_factory=store.repo)
    return app.test_client()


@pytest.fixture
def client(store, stub):
    store.add_customer(1)
    return make_client(store, stub.url)


def booking(reg_num="A1"):
    start = date.today() + timedelta(days=3)
    return {"customer_id": 1, "car_reg_num": reg_num, "start_date": start.isoformat(),
            "end_date": (start + timedelta(days=3)).isoformat()}


class TestBookingAcrossTheSeam:
    def test_rental_is_priced_from_the_vehicles_service(self, client, stub, store):
        stub.vehicle("A1", daily_rate=33.4)

        response = client.post("/rentals", json=booking())

        assert response.status_code == 201
        assert response.get_json()["total_price"] == 100.2  # 3 days x 33.40
        assert stub.requests == [("GET", "/vehicles/A1")]

    def test_reg_num_is_url_encoded(self, client, stub):
        stub.vehicle("AB/12 3")

        response = client.post("/rentals", json=booking("AB/12 3"))

        assert response.status_code == 201
        assert stub.requests == [("GET", "/vehicles/AB%2F12%203")]  # not /vehicles/AB/12 3

    def test_vehicles_404_becomes_404(self, client, store):
        response = client.post("/rentals", json=booking("NOPE"))
        assert response.status_code == 404
        assert response.get_json()["error"] == "vehicle_not_found"
        assert store.rentals == {}

    def test_vehicle_in_maintenance_becomes_409(self, client, stub, store):
        stub.vehicle("M1", status="maintenance")
        response = client.post("/rentals", json=booking("M1"))
        assert response.status_code == 409 and store.rentals == {}


class TestDesignedFailure:
    """When vehicles cannot answer, the booking fails fast with 503 and saves nothing."""

    def assert_unavailable(self, response, store, reason):
        assert response.status_code == 503
        body = response.get_json()
        assert body["error"] == "vehicles_unavailable" and reason in body["message"]
        assert store.rentals == {} and "commit" not in store.events

    def test_vehicles_server_error(self, client, stub, store):
        stub.answers["A1"] = (500, {"error": "internal_error", "message": "x"}, 0)
        self.assert_unavailable(client.post("/rentals", json=booking()), store, "answered 500")

    def test_slow_vehicles_service_times_out(self, client, stub, store):
        stub.vehicle("A1", delay=3 * TIMEOUT_S)

        started = time.monotonic()
        response = client.post("/rentals", json=booking())
        waited = time.monotonic() - started

        self.assert_unavailable(response, store, "timed out")
        assert waited < 2 * TIMEOUT_S, f"waited {waited:.2f}s for a {TIMEOUT_S}s timeout"

    @pytest.mark.parametrize("body", [b"<html>gateway</html>", {"reg_num": "A1"}, [1, 2]])
    def test_unexpected_answer(self, client, stub, store, body):
        stub.answers["A1"] = (200, body, 0)
        self.assert_unavailable(client.post("/rentals", json=booking()), store, "unexpected")

    def test_vehicles_service_not_running(self, store, stub):
        stub.stop()  # nothing listens on that port any more
        client = make_client(store, stub.url)
        store.add_customer(1)

        response = client.post("/rentals", json=booking())

        self.assert_unavailable(response, store, "not reachable")

    def test_other_routes_keep_working_while_vehicles_is_down(self, store, stub):
        stub.stop()
        client = make_client(store, stub.url)
        store.add_customer(1)

        assert client.get("/customers").status_code == 200
        assert client.get("/health").status_code == 200


class TestClient:
    def test_trailing_slash_in_the_address_is_ignored(self, stub):
        stub.vehicle("A1")
        assert VehiclesClient(stub.url + "/", TIMEOUT_S).get_vehicle("A1")["reg_num"] == "A1"
        assert stub.requests == [("GET", "/vehicles/A1")]

    def test_404_is_none(self, stub):
        assert VehiclesClient(stub.url, TIMEOUT_S).get_vehicle("NOPE") is None

    def test_no_connection_in_time_is_not_reachable(self):
        """What a closed port looks like on Windows: the connection attempt times out."""
        class NoConnection:
            def get(self, url, timeout):
                raise requests.ConnectTimeout("no answer")

        with pytest.raises(VehiclesUnavailable, match="not reachable"):
            client = VehiclesClient("http://vehicles:8000", TIMEOUT_S, session=NoConnection())
            client.get_vehicle("A1")

    def test_unavailable_is_an_exception_the_route_can_catch(self, stub):
        stub.answers["A1"] = (503, {"error": "database_unavailable", "message": "x"}, 0)
        with pytest.raises(VehiclesUnavailable, match="answered 503"):
            VehiclesClient(stub.url, TIMEOUT_S).get_vehicle("A1")