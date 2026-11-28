"""Tests for app/db.py: reading DATABASE_URL and waiting for a sleeping database.

The clock and sleep are fake, so the 90-second waits run instantly.

Run with:
    uv run pytest tests/test_db.py -v
"""
import pymssql
import pytest

from app.db import Database, DatabaseUnavailable, parse_database_url

URL = "mssql+pymssql://app_user:p%40ss%2Fword@db.example.net:1444/vehicles"


class FakeClock:
    """time.monotonic and time.sleep in one: sleeping just moves the clock forward."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def flaky(failures, error=pymssql.OperationalError):
    """A connector that fails `failures` times, then connects."""
    calls = []

    def connect(**params):
        calls.append(params)
        if len(calls) <= failures:
            raise error("(40613, b'Database is not currently available')")
        return "CONNECTION"

    return connect, calls


class TestParseDatabaseUrl:
    def test_all_parts(self):
        assert parse_database_url(URL) == {
            "server": "db.example.net", "port": 1444, "user": "app_user",
            "password": "p@ss/word",  # percent-encoded in the URL
            "database": "vehicles",
        }

    def test_default_port(self):
        assert parse_database_url("mssql+pymssql://u:p@host/db")["port"] == 1433

    @pytest.mark.parametrize("url", ["", "mssql+pymssql://u:p@host", "mssql+pymssql:///db", "x"])
    def test_incomplete_url_is_refused(self, url):
        with pytest.raises(ValueError, match="must look like"):
            parse_database_url(url)


class TestConnect:
    def test_connects_with_the_azure_settings(self):
        connect, calls = flaky(0)
        clock = FakeClock()

        assert Database(URL, connect, clock.sleep, clock).connect(90) == "CONNECTION"

        assert calls == [{"server": "db.example.net", "port": 1444, "user": "app_user",
                          "password": "p@ss/word", "database": "vehicles",
                          "login_timeout": 10, "timeout": 30, "tds_version": "7.4"}]
        assert clock.sleeps == []

    def test_waits_with_growing_pauses_while_the_database_resumes(self):
        connect, calls = flaky(6)
        clock = FakeClock()

        assert Database(URL, connect, clock.sleep, clock).connect(90) == "CONNECTION"

        assert clock.sleeps == [1, 2, 4, 8, 8, 8] and len(calls) == 7

    def test_gives_up_when_the_time_is_used_up(self):
        connect, calls = flaky(999)
        clock = FakeClock()

        with pytest.raises(DatabaseUnavailable, match="after 6 attempt"):
            Database(URL, connect, clock.sleep, clock).connect(20)

        assert clock.sleeps == [1, 2, 4, 8, 5]  # the last pause is cut to fit 20 s
        assert clock.now == 20

    def test_no_wait_means_one_attempt(self):
        connect, calls = flaky(999)
        clock = FakeClock()
        with pytest.raises(DatabaseUnavailable):
            Database(URL, connect, clock.sleep, clock).connect()
        assert len(calls) == 1 and clock.sleeps == []

    def test_interface_errors_are_retried_too(self):
        connect, calls = flaky(1, error=pymssql.InterfaceError)
        clock = FakeClock()
        assert Database(URL, connect, clock.sleep, clock).connect(10) == "CONNECTION"

    def test_programming_errors_are_not_retried(self):
        connect, calls = flaky(5, error=ValueError)
        clock = FakeClock()
        with pytest.raises(ValueError):
            Database(URL, connect, clock.sleep, clock).connect(90)
        assert len(calls) == 1