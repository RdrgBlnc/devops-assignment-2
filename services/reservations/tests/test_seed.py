"""Tests for app/seed.py: the sample customers and rentals loaded into an empty database
at start-up, keeping their ids (rentals refer to customers by id).

Run with:
    uv run pytest tests/test_seed.py -v
"""
from decimal import Decimal

import pytest

from app.seed import load_seed

CUSTOMERS = "id,name,surname,email,location\n1,Liam,Hall,liam@example.com,sevilla\n" \
            "2,Ana,Núñez,ana@example.com,madrid\n"
RENTALS = "id,customer_id,car_reg_num,start_date,end_date,total_price,status\n" \
          "5,2,VIN00000000000001,2026-12-01,2026-12-04,60.99,pending\n"


class FakeConnection:
    def __init__(self, counts=None, fail_on=None):
        self.counts = counts or {"customers": 0, "rentals": 0}
        self.fail_on = fail_on
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
        self.conn, self.row = conn, None

    def execute(self, sql, params=()):
        assert sql.count("%s") == len(params)
        if self.conn.fail_on and self.conn.fail_on in sql:
            raise RuntimeError("insert failed")
        self.conn.statements.append((sql, list(params)))
        if sql.startswith("SELECT COUNT(*) FROM"):
            self.row = (self.conn.counts[sql.split()[-1]],)

    def fetchone(self):
        return self.row

    def close(self):
        pass


@pytest.fixture
def seed_dir(tmp_path):
    (tmp_path / "customers.csv").write_text(CUSTOMERS, encoding="utf-8")
    (tmp_path / "rentals.csv").write_text(RENTALS, encoding="utf-8")
    return tmp_path


def changes(conn):
    return [sql for sql, _ in conn.statements if sql.startswith(("SET", "INSERT"))]


def test_customers_first_then_rentals_with_their_ids(seed_dir):
    conn = FakeConnection()

    assert load_seed(conn, seed_dir) == 3

    sqls = changes(conn)
    assert sqls[0] == "SET IDENTITY_INSERT customers ON"
    assert sqls[1].startswith("INSERT INTO customers")
    assert sqls[2] == "SET IDENTITY_INSERT customers OFF"
    assert sqls[3] == "SET IDENTITY_INSERT rentals ON" and sqls[4].startswith("INSERT INTO rentals")
    assert sqls[5] == "SET IDENTITY_INSERT rentals OFF"
    assert conn.commits == 1


def test_values_are_typed(seed_dir):
    conn = FakeConnection()
    load_seed(conn, seed_dir)
    customers, rentals = [p for s, p in conn.statements if s.startswith("INSERT")]
    assert customers[:5] == [1, "Liam", "Hall", "liam@example.com", "sevilla"]
    assert customers[7] == "Núñez"
    assert rentals == [5, 2, "VIN00000000000001", "2026-12-01", "2026-12-04", Decimal("60.99"),
                       "pending"]


def test_tables_with_rows_are_left_alone(seed_dir):
    conn = FakeConnection({"customers": 100, "rentals": 0})
    assert load_seed(conn, seed_dir) == 1  # only the rentals
    assert not any("INTO customers" in sql for sql in changes(conn))

    conn = FakeConnection({"customers": 100, "rentals": 151})
    assert load_seed(conn, seed_dir) == 0 and changes(conn) == []


def test_missing_files_are_skipped(tmp_path):
    conn = FakeConnection()
    assert load_seed(conn, tmp_path) == 0 and changes(conn) == []


def test_a_failed_load_saves_nothing_and_switches_identity_insert_off(seed_dir):
    conn = FakeConnection(fail_on="INSERT INTO rentals")
    with pytest.raises(RuntimeError):
        load_seed(conn, seed_dir)
    assert conn.rollbacks == 1 and conn.commits == 0
    assert changes(conn)[-1] == "SET IDENTITY_INSERT rentals OFF"


def test_a_file_with_missing_columns_is_refused(tmp_path):
    (tmp_path / "customers.csv").write_text("id,name\n1,A\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing columns"):
        load_seed(FakeConnection(), tmp_path)


def test_the_committed_seed_files_are_valid():
    """The real seed/*.csv, when the repository has them."""
    from conftest import SERVICE_DIR

    if not (SERVICE_DIR / "seed" / "customers.csv").exists():
        pytest.skip("seed/customers.csv is not in this checkout")
    assert load_seed(FakeConnection(), SERVICE_DIR / "seed") > 0