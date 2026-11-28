"""Tests for app/config.py (settings from the environment) and app/startup.py (migrations
and seed before the first request).

Run with:
    uv run pytest tests/test_config_startup.py -v
"""
import logging

import pytest

from app import create_app
from app.config import load_config
from app.db import DatabaseUnavailable

URL = "mssql+pymssql://u:p@db:1433/db"


class TestConfig:
    def test_defaults(self):
        config = load_config({"DATABASE_URL": URL})
        assert (config.port, config.git_sha) == (8000, "dev")
        assert config.cors_origins == ["http://localhost:8080"]
        assert (config.db_retry_total_s, config.db_request_wait_s) == (90, 20)

    def test_values_from_the_environment(self):
        config = load_config({
            "DATABASE_URL": f" {URL} ", "PORT": "9000", "GIT_SHA": "abc123",
            "CORS_ORIGIN": "https://ui.example.net/, http://localhost:8080",
            "DB_RETRY_TOTAL_S": "75", "DB_REQUEST_WAIT_S": "5.5",
        })
        assert (config.port, config.database_url, config.git_sha) == (9000, URL, "abc123")
        assert config.cors_origins == ["https://ui.example.net", "http://localhost:8080"]
        assert (config.db_retry_total_s, config.db_request_wait_s) == (75, 5.5)

    def test_reads_the_real_environment_by_default(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", URL)
        monkeypatch.setenv("GIT_SHA", "fromenv")
        assert load_config().git_sha == "fromenv"

    @pytest.mark.parametrize("env, message", [
        ({}, "DATABASE_URL is not set"),
        ({"DATABASE_URL": "  "}, "DATABASE_URL is not set"),
        ({"DATABASE_URL": URL, "CORS_ORIGIN": "*"}, "not \\* \\(any website\\)"),
        ({"DATABASE_URL": URL, "PORT": "eighty"}, "PORT must be a number"),
        ({"DATABASE_URL": URL, "PORT": "0"}, "PORT must be >= 1"),
        ({"DATABASE_URL": URL, "DB_RETRY_TOTAL_S": "-1"}, "DB_RETRY_TOTAL_S must be >= 0"),
    ])
    def test_bad_settings_stop_the_service(self, env, message):
        with pytest.raises(RuntimeError, match=message):
            load_config(env)


class TestStartup:
    """create_app() connects (waiting up to DB_RETRY_TOTAL_S), migrates and seeds."""

    def make_database(self, available=True):
        from test_migrate import FakeConnection, FakeServer

        class FakeDatabase:
            def __init__(self):
                self.server = FakeServer()
                self.waits = []
                self.closed = 0

            def connect(self, wait_s=0):
                self.waits.append(wait_s)
                if not available:
                    raise DatabaseUnavailable("database unreachable after 3 attempt(s): paused")
                conn = FakeConnection(self.server)
                conn.close = lambda: setattr(self, "closed", self.closed + 1)
                return conn

        return FakeDatabase()

    def test_first_boot_migrates_and_logs_the_version(self, caplog, monkeypatch):
        monkeypatch.setattr("app.startup.load_seed", lambda conn, folder: 0)
        database = self.make_database()
        config = load_config({"DATABASE_URL": URL, "GIT_SHA": "abc123", "DB_RETRY_TOTAL_S": "75"})

        with caplog.at_level(logging.INFO):
            app = create_app(config, database)

        assert database.waits == [75]            # the start-up wait comes from DB_RETRY_TOTAL_S
        assert "001_init.sql" in database.server.applied
        assert database.closed == 1              # the start-up connection is not kept
        assert "service starting (version abc123)" in caplog.messages
        assert app.config["CFG"] is config and app.config["DATABASE"] is database

    def test_tests_can_skip_the_database(self):
        database = self.make_database()
        create_app(load_config({"DATABASE_URL": URL}), database, migrate=False)
        assert database.waits == []

    def test_database_that_never_wakes_stops_the_service(self, caplog):
        with caplog.at_level(logging.ERROR, logger="startup"):
            with pytest.raises(DatabaseUnavailable):
                create_app(load_config({"DATABASE_URL": URL}), self.make_database(available=False))
        assert any("database not available at startup" in m for m in caplog.messages)