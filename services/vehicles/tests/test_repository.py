"""VehicleRepository against a real SQL Server (replaces the old SQLite test_database.py).

Needs TEST_SQLSERVER_URL (see conftest.py); skipped without it.
"""
import pymssql
import pytest

from app.repository import QueueBusy, VehicleRepository


def vehicle(**overrides):
    data = {
        "reg_num": "1HGCM82633A004352", "type": "car", "brand": "Toyota", "model": "Corolla",
        "category": "economy", "daily_rate": 39.99, "seat_num": 5, "plate": "1234 ABC",
        "color": "White", "fuel": "petrol", "transmission": "manual", "km": 18500,
        "status": "active", "location": "madrid", "manufacture_date": "2020-05-01",
        "registration_date": "2020-06-15",
    }
    data.update(overrides)
    return data


def add(repo, count, **overrides):
    """Insert `count` vehicles with distinct reg numbers and plates."""
    for i in range(count):
        repo.insert_vehicle(vehicle(reg_num=f"VIN{i:014d}", plate=f"{i:04d} TST", **overrides))


class TestVehicles:
    def test_insert_and_get_round_trip(self, repo):
        repo.insert_vehicle(vehicle())
        repo.commit()

        row = repo.get_vehicle("1HGCM82633A004352")

        assert row == vehicle()  # Decimal -> float and DATE -> "YYYY-MM-DD" on the way out

    def test_get_unknown_vehicle_returns_none(self, repo):
        assert repo.get_vehicle("NOPE") is None

    def test_nullable_colour(self, repo):
        repo.insert_vehicle(vehicle(color=None))
        assert repo.get_vehicle("1HGCM82633A004352")["color"] is None

    def test_list_and_count_with_filters(self, repo):
        add(repo, 3, location="madrid")
        repo.insert_vehicle(vehicle(reg_num="OTHER", plate="9999 OTH", location="barcelona"))

        madrid = repo.list_vehicles({"location": "madrid"})

        assert len(madrid) == 3 and {v["location"] for v in madrid} == {"madrid"}
        assert repo.count_vehicles({"location": "madrid"}) == 3
        assert repo.count_vehicles() == 4

    def test_filter_without_match_returns_empty(self, repo):
        add(repo, 2)
        assert repo.list_vehicles({"location": "mallorca"}) == []
        assert repo.count_vehicles({"location": "mallorca"}) == 0

    def test_filter_values_are_parameters_not_sql(self, repo):
        add(repo, 2)
        assert repo.list_vehicles({"location": "madrid' OR '1'='1"}) == []

    def test_unknown_filter_names_are_ignored(self, repo):
        add(repo, 2)
        assert len(repo.list_vehicles({"km; DROP TABLE vehicles": "x"})) == 2

    @pytest.mark.parametrize("sort_by, key, reverse", [
        ("price_asc", "daily_rate", False), ("price_desc", "daily_rate", True),
        ("km_asc", "km", False), ("km_desc", "km", True),
    ])
    def test_sorting(self, repo, sort_by, key, reverse):
        for i, (rate, km) in enumerate([(50, 300), (20, 900), (35, 100)]):
            repo.insert_vehicle(vehicle(reg_num=f"S{i}", plate=f"S{i}", daily_rate=rate, km=km))

        values = [v[key] for v in repo.list_vehicles(sort_by=sort_by)]

        assert values == sorted(values, reverse=reverse)

    def test_paging(self, repo):
        add(repo, 5)

        first = repo.list_vehicles(limit=2, offset=0)
        rest = repo.list_vehicles(limit=10, offset=2)

        assert len(first) == 2 and len(rest) == 3
        assert {v["reg_num"] for v in first}.isdisjoint(v["reg_num"] for v in rest)

    def test_update_vehicle(self, repo):
        repo.insert_vehicle(vehicle())

        changed = repo.update_vehicle(
            "1HGCM82633A004352", {"daily_rate": 45.5, "status": "maintenance"}
        )

        row = repo.get_vehicle("1HGCM82633A004352")
        assert changed == 1 and row["daily_rate"] == 45.5 and row["status"] == "maintenance"

    def test_update_unknown_vehicle_changes_nothing(self, repo):
        assert repo.update_vehicle("NOPE", {"status": "maintenance"}) == 0

    def test_update_with_no_fields_raises(self, repo):
        with pytest.raises(ValueError):
            repo.update_vehicle("1HGCM82633A004352", {})

    @pytest.mark.parametrize("field", ["km", "location", "reg_num", "brand"])
    def test_update_of_fixed_fields_is_refused(self, repo, field):
        with pytest.raises(ValueError):
            repo.update_vehicle("1HGCM82633A004352", {field: "x"})

    def test_retiring_keeps_the_row(self, repo):
        """There is no delete: a vehicle is retired, so rentals can still refer to it."""
        repo.insert_vehicle(vehicle())

        repo.update_vehicle("1HGCM82633A004352", {"status": "retired"})

        assert repo.count_vehicles() == 1
        assert repo.get_vehicle("1HGCM82633A004352")["status"] == "retired"

    def test_update_location(self, repo):
        repo.insert_vehicle(vehicle())
        assert repo.update_location("1HGCM82633A004352", "valencia") == 1
        assert repo.get_vehicle("1HGCM82633A004352")["location"] == "valencia"

    def test_duplicate_reg_num_is_rejected(self, repo):
        repo.insert_vehicle(vehicle())
        with pytest.raises(pymssql.IntegrityError):
            repo.insert_vehicle(vehicle(plate="OTHER 1"))

    def test_duplicate_plate_is_rejected(self, repo):
        repo.insert_vehicle(vehicle())
        with pytest.raises(pymssql.IntegrityError):
            repo.insert_vehicle(vehicle(reg_num="ANOTHERVIN"))

    def test_rollback_discards_uncommitted_changes(self, repo):
        repo.insert_vehicle(vehicle())
        repo.rollback()
        assert repo.get_vehicle("1HGCM82633A004352") is None

    def test_committed_changes_are_seen_by_another_connection(self, repo, database):
        repo.insert_vehicle(vehicle())
        repo.commit()

        other = VehicleRepository(database.connect())
        try:
            assert other.get_vehicle("1HGCM82633A004352") is not None
        finally:
            other.close()

    def test_stats(self, repo):
        add(repo, 3)
        repo.insert_vehicle(vehicle(reg_num="BROKEN", plate="0000 BRK", status="maintenance"))

        assert repo.stats() == {"total_vehicles": 4, "available_vehicles": 3, "pending_trips": 0}

    def test_stats_on_empty_table(self, repo):
        assert repo.stats() == {"total_vehicles": 0, "available_vehicles": 0, "pending_trips": 0}

    def test_ping(self, repo):
        assert repo.ping() is True


class TestTransportQueue:
    def test_add_list_and_remove(self, repo):
        add(repo, 3)
        for i in range(3):
            repo.add_to_queue(f"VIN{i:014d}", "madrid", "barcelona", "truck", "barcelona")

        waiting = repo.waiting_in_queue("madrid", "barcelona", "truck")

        # oldest first
        assert [row["reg_num"] for row in waiting] == [f"VIN{i:014d}" for i in range(3)]
        assert repo.is_queued("VIN00000000000000")
        repo.remove_from_queue([row["id"] for row in waiting[:2]])
        left = repo.waiting_in_queue("madrid", "barcelona", "truck")
        assert [row["reg_num"] for row in left] == ["VIN00000000000002"]
        assert not repo.is_queued("VIN00000000000000")

    def test_remove_nothing(self, repo):
        repo.remove_from_queue([])  # no SQL, no error

    def test_groups_and_pending_trips(self, repo):
        add(repo, 3)
        repo.add_to_queue("VIN00000000000000", "madrid", "barcelona", "truck", "barcelona")
        repo.add_to_queue("VIN00000000000001", "madrid", "barcelona", "truck", "barcelona")
        repo.add_to_queue("VIN00000000000002", "malaga", "tenerife", "ship", "tenerife")

        groups = repo.queue_groups()

        assert groups == [
            {"origin": "madrid", "destination": "barcelona", "mode": "truck", "queued": 2},
            {"origin": "malaga", "destination": "tenerife", "mode": "ship", "queued": 1},
        ]
        assert repo.stats()["pending_trips"] == 2

    def test_unknown_vehicle_cannot_be_queued(self, repo):
        with pytest.raises(pymssql.IntegrityError):
            repo.add_to_queue("NOPE", "madrid", "barcelona", "truck", "barcelona")

    def test_vehicle_cannot_be_queued_twice(self, repo):
        add(repo, 1)
        repo.add_to_queue("VIN00000000000000", "madrid", "barcelona", "truck", "barcelona")
        with pytest.raises(pymssql.IntegrityError):
            repo.add_to_queue("VIN00000000000000", "madrid", "valencia", "truck", "valencia")

    def test_lock_queue(self, repo):
        repo.lock_queue()
        repo.lock_queue()  # the same connection may take it again

    def test_lock_is_released_when_the_connection_closes(self, repo, database):
        first = VehicleRepository(database.connect())
        first.lock_queue()
        first.close()

        repo.lock_queue()  # would wait 10 s and raise QueueBusy if the lock were still held


def test_queue_busy_is_an_exception():
    assert issubclass(QueueBusy, Exception)


class TestMigrations:
    def test_schema_is_recorded_and_not_applied_twice(self, repo):
        from conftest import SERVICE_DIR
        from app.migrate import apply_migrations

        recorded = repo._query("SELECT version FROM schema_migrations ORDER BY version")

        assert [row["version"] for row in recorded][0].startswith("001_")
        assert apply_migrations(repo.conn, SERVICE_DIR / "migrations") == []