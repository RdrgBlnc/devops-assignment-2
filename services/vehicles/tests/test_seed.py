"""Tests for app/seed.py: the sample vehicles loaded into an empty database at start-up.

Run with:
    uv run pytest tests/test_seed.py -v
"""
import csv
from decimal import Decimal

import pytest

from app.repository import COLUMNS
from app.seed import load_seed


class FakeConnection:
    def __init__(self, existing_rows=0, fail_on=None):
        self.existing_rows, self.fail_on = existing_rows, fail_on
        self.statements = []
        self.commits = self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=()):
        assert sql.count("%s") == len(params)
        if self.conn.fail_on and self.conn.fail_on in sql:
            raise RuntimeError("insert failed")
        self.conn.statements.append((sql, list(params)))

    def fetchone(self):
        return (self.conn.existing_rows,)

    def close(self):
        pass


def write_vehicles(folder, count):
    with open(folder / "vehicles.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for i in range(count):
            writer.writerow({
                "reg_num": f"VIN{i:014d}", "type": "car", "brand": "Škoda" if i == 0 else "Seat",
                "model": 'Octavia, 2.0 "TDI"', "category": "economy", "daily_rate": f"{20.33 + i}",
                "seat_num": "5", "plate": f"{i:04d} ABC", "color": "" if i % 2 else "Black",
                "fuel": "diesel", "transmission": "manual", "km": str(1000 + i),
                "status": "active", "location": "madrid", "manufacture_date": "2022-01-02",
                "registration_date": "2022-06-01",
            })


def inserts(conn):
    return [params for sql, params in conn.statements if sql.startswith("INSERT")]


def test_loads_an_empty_table_in_chunks_of_100(tmp_path):
    write_vehicles(tmp_path, 250)
    conn = FakeConnection()

    assert load_seed(conn, tmp_path) == 250

    assert [len(params) // len(COLUMNS) for params in inserts(conn)] == [100, 100, 50]
    assert conn.commits == 1  # one transaction for the whole load


def test_values_are_typed_and_empty_means_null(tmp_path):
    write_vehicles(tmp_path, 2)
    conn = FakeConnection()
    load_seed(conn, tmp_path)

    first, second = (inserts(conn)[0][i:i + len(COLUMNS)] for i in (0, len(COLUMNS)))
    row = dict(zip(COLUMNS, first))
    assert row["brand"] == "Škoda" and row["model"] == 'Octavia, 2.0 "TDI"'
    assert (row["daily_rate"], row["seat_num"], row["km"]) == (Decimal("20.33"), 5, 1000)
    assert row["color"] == "Black" and dict(zip(COLUMNS, second))["color"] is None


def test_a_table_with_rows_is_left_alone(tmp_path):
    write_vehicles(tmp_path, 3)
    conn = FakeConnection(existing_rows=7)
    assert load_seed(conn, tmp_path) == 0
    assert inserts(conn) == [] and conn.commits == 0


def test_no_seed_file_means_nothing_to_load(tmp_path):
    conn = FakeConnection()
    assert load_seed(conn, tmp_path) == 0 and conn.statements == []


def test_a_failed_load_saves_nothing(tmp_path):
    write_vehicles(tmp_path, 150)
    conn = FakeConnection(fail_on="INSERT")
    with pytest.raises(RuntimeError):
        load_seed(conn, tmp_path)
    assert conn.rollbacks == 1 and conn.commits == 0


def test_a_file_with_missing_columns_is_refused(tmp_path):
    (tmp_path / "vehicles.csv").write_text("reg_num,brand\nA,B\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing columns"):
        load_seed(FakeConnection(), tmp_path)


def test_the_committed_seed_file_is_valid():
    """The real seed/vehicles.csv, when the repository has it."""
    from conftest import SERVICE_DIR

    if not (SERVICE_DIR / "seed" / "vehicles.csv").exists():
        pytest.skip("seed/vehicles.csv is not in this checkout")
    conn = FakeConnection()
    assert load_seed(conn, SERVICE_DIR / "seed") > 0