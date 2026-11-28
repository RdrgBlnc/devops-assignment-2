"""An in-memory stand-in for VehicleRepository, for the route tests.

It keeps plain values like the database does and records commits, rollbacks and closes,
so the tests can check that a route saves only when it should.
"""
import pymssql

from app.repository import QueueBusy, SORTS

SORT_KEYS = {"price_asc": ("daily_rate", False), "price_desc": ("daily_rate", True),
             "km_asc": ("km", False), "km_desc": ("km", True)}
assert set(SORT_KEYS) == set(SORTS)


def vehicle_row(reg_num="1HGCM82633A004352", **overrides):
    row = {
        "reg_num": reg_num, "type": "car", "brand": "Toyota", "model": "Corolla",
        "category": "economy", "daily_rate": 39.99, "seat_num": 5, "plate": f"P-{reg_num}"[:16],
        "color": "White", "fuel": "petrol", "transmission": "manual", "km": 18500,
        "status": "active", "location": "madrid", "manufacture_date": "2023-05-01",
        "registration_date": "2023-06-15",
    }
    row.update(overrides)
    return row


class FakeStore:
    """The data and the record of what happened, shared by every request of a test."""

    def __init__(self):
        self.vehicles = {}
        self.queue = []
        self.next_id = 0
        self.events = []          # "commit", "rollback", "close", in order
        self.queue_busy = False   # lock_queue() raises QueueBusy
        self.ping_result = True
        self.fail_with = None     # an exception every repository call raises

    def add(self, **overrides):
        row = vehicle_row(**overrides)
        self.vehicles[row["reg_num"]] = row
        return row

    def repo(self):
        return FakeVehicleRepo(self)


class FakeVehicleRepo:
    def __init__(self, store):
        if store.fail_with:
            raise store.fail_with
        self.store = store

    # transactions
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

    # vehicles
    def _matching(self, filters):
        return [v for v in self.store.vehicles.values()
                if all(v.get(key) == value for key, value in (filters or {}).items())]

    def list_vehicles(self, filters=None, sort_by=None, limit=100, offset=0):
        rows = self._matching(filters)
        if sort_by:
            key, reverse = SORT_KEYS[sort_by]
            rows.sort(key=lambda v: v[key], reverse=reverse)
        return [dict(v) for v in rows[offset:offset + limit]]

    def count_vehicles(self, filters=None):
        return len(self._matching(filters))

    def get_vehicle(self, reg_num):
        row = self.store.vehicles.get(reg_num)
        return dict(row) if row else None

    def insert_vehicle(self, data):
        if any(v["plate"] == data["plate"] for v in self.store.vehicles.values()):
            raise pymssql.IntegrityError("duplicate plate")
        self.store.vehicles[data["reg_num"]] = dict(data)

    def update_vehicle(self, reg_num, fields):
        if reg_num not in self.store.vehicles:
            return 0
        self.store.vehicles[reg_num].update(fields)
        return 1

    def update_location(self, reg_num, location):
        self.store.vehicles[reg_num]["location"] = location
        return 1

    def stats(self):
        rows = self.store.vehicles.values()
        groups = {(r["origin"], r["destination"], r["mode"]) for r in self.store.queue}
        return {"total_vehicles": len(rows),
                "available_vehicles": sum(v["status"] == "active" for v in rows),
                "pending_trips": len(groups)}

    # transport queue
    def lock_queue(self):
        if self.store.queue_busy:
            raise QueueBusy()

    def add_to_queue(self, reg_num, origin, destination, mode, final_destination):
        self.store.next_id += 1
        self.store.queue.append({"id": self.store.next_id, "reg_num": reg_num, "origin": origin,
                                 "destination": destination, "mode": mode,
                                 "final_destination": final_destination})

    def waiting_in_queue(self, origin, destination, mode):
        return [dict(r) for r in self.store.queue
                if (r["origin"], r["destination"], r["mode"]) == (origin, destination, mode)]

    def remove_from_queue(self, ids):
        self.store.queue = [r for r in self.store.queue if r["id"] not in ids]

    def queue_groups(self):
        counts = {}
        for r in self.store.queue:
            key = (r["origin"], r["destination"], r["mode"])
            counts[key] = counts.get(key, 0) + 1
        return [{"origin": o, "destination": d, "mode": m, "queued": n}
                for (o, d, m), n in counts.items()]

    def is_queued(self, reg_num):
        return any(r["reg_num"] == reg_num for r in self.store.queue)