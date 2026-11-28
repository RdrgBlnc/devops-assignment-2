"""ReservationRepository against a real SQL Server (replaces the old SQLite test_database.py).

Needs TEST_SQLSERVER_URL (see conftest.py); skipped without it.
"""
import pymssql
import pytest

from app.repository import ReservationRepository


def add_customer(repo, name="Jane", surname="Doe", email="jane@example.com", location="madrid"):
    rows = repo._query(
        "INSERT INTO customers (name, surname, email, location) OUTPUT INSERTED.id "
        "VALUES (%s, %s, %s, %s)",
        (name, surname, email, location),
    )
    return rows[0]["id"]


def rental(customer_id, **overrides):
    data = {
        "customer_id": customer_id, "car_reg_num": "1HGCM82633A004352",
        "start_date": "2026-11-01", "end_date": "2026-11-05", "total_price": 159.96,
        "status": "pending",
    }
    data.update(overrides)
    return data


class TestCustomers:
    def test_get_customer(self, repo):
        customer_id = add_customer(repo)

        assert repo.get_customer(customer_id) == {
            "id": customer_id, "name": "Jane", "surname": "Doe",
            "email": "jane@example.com", "location": "madrid",
        }
        assert repo.get_customer(customer_id + 1000) is None

    def test_filter_by_location(self, repo):
        add_customer(repo, email="a@example.com", location="madrid")
        add_customer(repo, email="b@example.com", location="sevilla")

        assert [c["email"] for c in repo.list_customers(location="sevilla")] == ["b@example.com"]
        assert repo.count_customers(location="madrid") == 1

    def test_search_matches_name_surname_or_email_ignoring_case(self, repo):
        add_customer(repo, name="Liam", surname="Hall", email="liam.hall@example.com")
        add_customer(repo, name="Ana", surname="Lopez", email="ana@example.com")

        assert [c["name"] for c in repo.list_customers(search="liam")] == ["Liam"]
        assert [c["name"] for c in repo.list_customers(search="LOPEZ")] == ["Ana"]
        assert repo.count_customers(search="example.com") == 2

    def test_search_wildcards_are_literal(self, repo):
        add_customer(repo, email="plain@example.com")
        add_customer(repo, name="Fifty%", email="pct@example.com")

        assert [c["email"] for c in repo.list_customers(search="%")] == ["pct@example.com"]
        assert repo.list_customers(search="_") == []

    def test_paging(self, repo):
        for i in range(5):
            add_customer(repo, email=f"c{i}@example.com")

        first = repo.list_customers(limit=2)
        rest = repo.list_customers(limit=10, offset=2)

        assert len(first) == 2 and len(rest) == 3
        assert first[0]["id"] < first[1]["id"] < rest[0]["id"]  # ordered by id

    def test_duplicate_email_is_rejected(self, repo):
        add_customer(repo)
        with pytest.raises(pymssql.IntegrityError):
            add_customer(repo, name="Other")


class TestRentals:
    def test_insert_returns_id_and_reads_back(self, repo):
        customer_id = add_customer(repo)

        rental_id = repo.insert_rental(rental(customer_id))
        repo.commit()

        assert repo.get_rental(rental_id) == {"id": rental_id, **rental(customer_id)}

    def test_get_unknown_rental_returns_none(self, repo):
        assert repo.get_rental(123456) is None

    def test_list_and_count_with_filters(self, repo):
        jane = add_customer(repo)
        john = add_customer(repo, name="John", email="john@example.com")
        repo.insert_rental(rental(jane))
        repo.insert_rental(rental(jane, status="confirmed", car_reg_num="OTHERCAR"))
        repo.insert_rental(rental(john))

        assert repo.count_rentals() == 3
        assert repo.count_rentals({"customer_id": jane}) == 2
        confirmed = repo.list_rentals({"status": "confirmed"})
        assert [r["car_reg_num"] for r in confirmed] == ["OTHERCAR"]
        assert repo.list_rentals({"car_reg_num": "NOPE"}) == []
        assert len(repo.list_rentals({"status": ""})) == 3  # an empty filter is no filter

    def test_paging(self, repo):
        customer_id = add_customer(repo)
        ids = [repo.insert_rental(rental(customer_id)) for _ in range(4)]

        assert [r["id"] for r in repo.list_rentals(limit=2, offset=2)] == ids[2:]

    def test_update_rental(self, repo):
        rental_id = repo.insert_rental(rental(add_customer(repo)))

        changed = repo.update_rental(
            rental_id, {"status": "confirmed", "end_date": "2026-11-07", "total_price": 239.94}
        )

        row = repo.get_rental(rental_id)
        assert changed == 1
        assert row["status"] == "confirmed"
        assert (row["end_date"], row["total_price"]) == ("2026-11-07", 239.94)

    def test_update_with_no_fields_raises(self, repo):
        with pytest.raises(ValueError):
            repo.update_rental(1, {})

    @pytest.mark.parametrize("field", ["customer_id", "car_reg_num", "start_date", "id"])
    def test_update_of_fixed_fields_is_refused(self, repo, field):
        with pytest.raises(ValueError):
            repo.update_rental(1, {field: "x"})

    def test_canceling_keeps_the_row(self, repo):
        rental_id = repo.insert_rental(rental(add_customer(repo)))

        repo.update_rental(rental_id, {"status": "canceled"})

        assert repo.count_rentals() == 1
        assert repo.get_rental(rental_id)["status"] == "canceled"

    def test_rental_for_unknown_customer_is_rejected(self, repo):
        """customers and rentals live in the same database, so this link IS a foreign key."""
        with pytest.raises(pymssql.IntegrityError):
            repo.insert_rental(rental(customer_id=999999))

    def test_any_car_reg_num_is_accepted(self, repo):
        """The vehicle lives in the other service's database: no foreign key here (ADR-7).
        The booking route checks the vehicle over HTTP instead."""
        rental_id = repo.insert_rental(rental(add_customer(repo), car_reg_num="NOT-IN-THIS-DB"))
        assert repo.get_rental(rental_id)["car_reg_num"] == "NOT-IN-THIS-DB"

    @pytest.mark.parametrize("end_date", ["2026-11-01", "2026-10-30"])
    def test_end_date_must_be_after_start_date(self, repo, end_date):
        with pytest.raises(pymssql.IntegrityError):
            repo.insert_rental(rental(add_customer(repo), end_date=end_date))

    def test_rollback_discards_uncommitted_rental(self, repo):
        customer_id = add_customer(repo)
        repo.commit()
        rental_id = repo.insert_rental(rental(customer_id))
        repo.rollback()
        assert repo.get_rental(rental_id) is None

    def test_committed_rental_is_seen_by_another_connection(self, repo, database):
        rental_id = repo.insert_rental(rental(add_customer(repo)))
        repo.commit()

        other = ReservationRepository(database.connect())
        try:
            assert other.get_rental(rental_id)["status"] == "pending"
        finally:
            other.close()


class TestStatsAndHealth:
    def test_stats(self, repo):
        customer_id = add_customer(repo)
        repo.insert_rental(rental(customer_id, status="active"))
        repo.insert_rental(rental(customer_id, status="returned"))

        assert repo.stats() == {"active_rentals": 1, "total_customers": 1}

    def test_stats_on_empty_tables(self, repo):
        assert repo.stats() == {"active_rentals": 0, "total_customers": 0}

    def test_ping(self, repo):
        assert repo.ping() is True


class TestMigrations:
    def test_schema_is_recorded_and_not_applied_twice(self, repo):
        from conftest import SERVICE_DIR
        from app.migrate import apply_migrations

        recorded = repo._query("SELECT version FROM schema_migrations ORDER BY version")

        assert [row["version"] for row in recorded][0].startswith("001_")
        assert apply_migrations(repo.conn, SERVICE_DIR / "migrations") == []