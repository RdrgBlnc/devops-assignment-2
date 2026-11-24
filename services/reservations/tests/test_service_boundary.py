"""The reservations service must never reach into the vehicles database.

Vehicles are owned by the other service: reservations learns about a vehicle only
through its HTTP API (app/clients/vehicles.py). These tests fail if someone adds
direct access to vehicle data, so the boundary is checked on every run.
"""
import pathlib
import re

SERVICE = pathlib.Path(__file__).resolve().parent.parent
APP_FILES = sorted((SERVICE / "app").rglob("*.py"))
MIGRATIONS = sorted((SERVICE / "migrations").glob("*.sql"))
# SQL that reads or changes a table called "vehicles" (a column named car_reg_num is fine)
VEHICLES_TABLE_SQL = re.compile(
    r"\b(from|join|into|update|delete\s+from|table|references)\s+\[?(dbo\.)?vehicles\b",
    re.IGNORECASE,
)


def test_there_is_code_to_check():
    assert APP_FILES and MIGRATIONS


def test_no_python_file_queries_the_vehicles_table():
    offenders = [
        path.name for path in APP_FILES if VEHICLES_TABLE_SQL.search(path.read_text())
    ]
    assert offenders == []


def test_no_migration_creates_or_references_a_vehicles_table():
    offenders = [
        path.name for path in MIGRATIONS if VEHICLES_TABLE_SQL.search(path.read_text())
    ]
    assert offenders == []


def test_rentals_has_no_foreign_key_to_another_service():
    for path in MIGRATIONS:
        sql = path.read_text().lower()
        # the only foreign key allowed is rentals -> customers (same service)
        for target in re.findall(r"references\s+\[?(?:dbo\.)?(\w+)", sql):
            assert target == "customers", f"{path.name} references {target}"


def test_no_code_opens_the_vehicles_database_or_uses_its_url():
    for path in APP_FILES:
        text = path.read_text()
        assert "VEHICLES_DATABASE" not in text, path.name
        assert "vehicles.db" not in text, path.name


HTTP_LIBRARY = re.compile(
    r"^\s*(import|from)\s+(requests|httpx|urllib\.request|http\.client)\b", re.MULTILINE
)


def test_the_only_module_that_makes_http_calls_is_the_vehicles_client():
    callers = [
        path.relative_to(SERVICE).as_posix()
        for path in APP_FILES
        if HTTP_LIBRARY.search(path.read_text())
    ]
    assert callers == ["app/clients/vehicles.py"]