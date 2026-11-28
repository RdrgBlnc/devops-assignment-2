"""Shared test set-up for the reservations service.

The repository tests run against a real SQL Server, the same engine as Azure SQL: a
SQLite stand-in would hide the differences that broke the old tests. Each test run
creates a throwaway database on the server, applies this service's migrations to it,
and drops it at the end. Point TEST_SQLSERVER_URL at a server login that may create
databases, for example the sa login of the compose SQL Server:

    TEST_SQLSERVER_URL=mssql+pymssql://sa:<password>@localhost:1433/master

Without it, the database tests are skipped and the other tests still run.
"""
import os
import pathlib
import sys
import uuid

import pytest

SERVICE_DIR = pathlib.Path(__file__).resolve().parent.parent
# Let the tests import the service as `app`, whichever folder pytest is started from.
sys.path.insert(0, str(SERVICE_DIR))

SERVER_URL_ENV = "TEST_SQLSERVER_URL"
TABLES = ("rentals", "customers")  # emptied before each test, children first


@pytest.fixture(scope="session")
def database_url():
    """URL of a fresh, migrated database that is dropped when the test run ends."""
    server_url = os.environ.get(SERVER_URL_ENV)
    if not server_url:
        pytest.skip(f"{SERVER_URL_ENV} is not set: the database tests need a SQL Server")

    import pymssql
    from app.db import Database, parse_database_url
    from app.migrate import apply_migrations

    name = f"test_reservations_{uuid.uuid4().hex[:8]}"
    params = dict(parse_database_url(server_url), database="master")
    admin = pymssql.connect(**params, autocommit=True, login_timeout=10, tds_version="7.4")
    try:
        admin.cursor().execute(f"CREATE DATABASE [{name}]")
        url = f"{server_url.rsplit('/', 1)[0]}/{name}"
        conn = Database(url).connect(wait_s=30)
        try:
            apply_migrations(conn, SERVICE_DIR / "migrations")
        finally:
            conn.close()
        yield url
    finally:
        admin.cursor().execute(
            f"IF DB_ID(N'{name}') IS NOT NULL BEGIN "
            f"ALTER DATABASE [{name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
            f"DROP DATABASE [{name}] END"
        )
        admin.close()


@pytest.fixture
def database(database_url):
    from app.db import Database

    return Database(database_url)


@pytest.fixture
def repo(database):
    """A repository on an empty database (the tables exist, the rows are gone)."""
    from app.repository import ReservationRepository

    repo = ReservationRepository(database.connect())
    for table in TABLES:
        repo._execute(f"DELETE FROM {table}")
    repo.commit()
    yield repo
    repo.rollback()
    repo.close()