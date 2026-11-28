"""In-memory stand-ins for the route tests: the repository and the vehicles service client."""
from app.clients.vehicles import VehiclesUnavailable


class FakeStore:
    """The data and the record of what happened, shared by every request of a test."""

    def __init__(self):
        self.customers = {}
        self.rentals = {}
        self.events = []          # "commit", "rollback", "close", in order
        self.ping_result = True
        self.fail_with = None     # an exception every request raises when opening the repo
        self.insert_error = None  # an exception insert_rental raises

    def add_customer(self, customer_id, **overrides):
        row = {"id": customer_id, "name": "Jane", "surname": "Doe",
               "email": f"c{customer_id}@example.com", "location": "madrid"}
        row.update(overrides)
        self.customers[customer_id] = row
        return row

    def add_rental(self, rental_id, **overrides):
        row = {"id": rental_id, "customer_id": 1, "car_reg_num": "A1",
               "start_date": "2026-12-01", "end_date": "2026-12-04", "total_price": 61.5,
               "status": "pending"}
        row.update(overrides)
        self.rentals[rental_id] = row
        return row

    def repo(self):
        return FakeReservationRepo(self)


class FakeReservationRepo:
    def __init__(self, store):
        if store.fail_with:
            raise store.fail_with
        self.store = store

    def commit(self):
        self.store.events.append("commit")

    def rollback(self):
        self.store.events.append("rollback")

    def close(self):
        self.store.events.append("close")

    def ping(self):
        if isinstance(self.store.ping_result, Exception):
            raise self.store.ping_result
        return self.store.ping_result

    def _customers(self, location, search):
        rows = self.store.customers.values()
        return [c for c in rows
                if (not location or c["location"] == location)
                and (not search or search.lower() in
                     (c["name"] + " " + c["surname"] + " " + c["email"]).lower())]

    def list_customers(self, location=None, search=None, limit=100, offset=0):
        return [dict(c) for c in self._customers(location, search)[offset:offset + limit]]

    def count_customers(self, location=None, search=None):
        return len(self._customers(location, search))

    def get_customer(self, customer_id):
        row = self.store.customers.get(customer_id)
        return dict(row) if row else None

    def _rentals(self, filters):
        return [r for r in self.store.rentals.values()
                if all(r.get(k) == v for k, v in (filters or {}).items())]

    def list_rentals(self, filters=None, limit=100, offset=0):
        return [dict(r) for r in self._rentals(filters)[offset:offset + limit]]

    def count_rentals(self, filters=None):
        return len(self._rentals(filters))

    def get_rental(self, rental_id):
        row = self.store.rentals.get(rental_id)
        return dict(row) if row else None

    def insert_rental(self, data):
        if self.store.insert_error:
            raise self.store.insert_error
        new_id = max(self.store.rentals, default=0) + 1
        self.store.rentals[new_id] = {"id": new_id, **data}
        return new_id

    def update_rental(self, rental_id, fields):
        self.store.rentals[rental_id].update(fields)
        return 1

    def stats(self):
        return {"active_rentals": sum(r["status"] == "active" for r in self.store.rentals.values()),
                "total_customers": len(self.store.customers)}


class FakeVehiclesClient:
    """Answers like the vehicles service would, and records which vehicles were asked for."""

    def __init__(self):
        self.vehicles = {}
        self.calls = []
        self.down = None  # a reason: every call raises VehiclesUnavailable

    def add(self, reg_num, status="active", daily_rate=20.5):
        self.vehicles[reg_num] = {"reg_num": reg_num, "status": status, "daily_rate": daily_rate}

    def get_vehicle(self, reg_num):
        self.calls.append(reg_num)
        if self.down:
            raise VehiclesUnavailable(self.down)
        return self.vehicles.get(reg_num)