"""Tests for app/migrate.py: versioned, forward-only migrations that run once.

A fake connection stands in for SQL Server and keeps what was committed, like a real
database would (the real migrations are run against SQL Server in test_repository.py).

Run with:
    uv run pytest tests/test_migrate.py -v
"""
import logging

import pytest

from app.migrate import CREATE_TABLE, MigrationError, apply_migrations, discover, split_batches


class FakeServer:
    """What the database keeps between connections."""

    def __init__(self):
        self.applied = {}   # version -> checksum (the schema_migrations table)
        self.schema = []    # every committed statement
        self.lock_status = 0


class FakeConnection:
    def __init__(self, server):
        self.server = server
        self.pending_schema, self.pending_applied = [], {}
        self.released = self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.server.schema += self.pending_schema
        self.server.applied.update(self.pending_applied)
        self.pending_schema, self.pending_applied = [], {}

    def rollback(self):
        self.pending_schema, self.pending_applied = [], {}
        self.rollbacks += 1


class FakeCursor:
    def __init__(self, conn):
        self.conn, self.rows = conn, []

    def execute(self, sql, params=()):
        assert sql.count("%s") == len(params)
        if "sp_getapplock" in sql:
            self.rows = [(self.conn.server.lock_status,)]
        elif "sp_releaseapplock" in sql:
            self.conn.released += 1
        elif sql == CREATE_TABLE:
            pass
        elif sql.startswith("SELECT version"):
            self.rows = list(self.conn.server.applied.items())
        elif sql.startswith("INSERT INTO schema_migrations"):
            self.conn.pending_applied[params[0]] = params[1]
        elif "BOOM" in sql:
            raise RuntimeError("syntax error near BOOM")
        else:
            self.conn.pending_schema.append(sql)

    def fetchone(self):
        return self.rows[0]

    def fetchall(self):
        return self.rows

    def close(self):
        pass


@pytest.fixture
def folder(tmp_path):
    (tmp_path / "001_init.sql").write_text(
        "CREATE TABLE a (id INT);\nGO\nCREATE TABLE b (id INT);\n"
    )
    (tmp_path / "README.txt").write_text("not a migration")
    return tmp_path


@pytest.fixture
def server():
    return FakeServer()


def run(server, folder):
    conn = FakeConnection(server)
    return apply_migrations(conn, folder), conn


def test_only_a_line_with_just_go_splits_batches():
    assert split_batches("A;\nGO\nB;\n  go  \nC;\nGOTO x") == ["A;", "B;", "C;\nGOTO x"]


def test_first_boot_applies_everything(server, folder):
    applied, conn = run(server, folder)
    assert applied == ["001_init.sql"]
    assert server.schema == ["CREATE TABLE a (id INT);", "CREATE TABLE b (id INT);"]
    assert conn.released == 1  # the lock is given back


def test_second_boot_applies_nothing(server, folder, caplog):
    run(server, folder)
    with caplog.at_level(logging.INFO, logger="migrations"):
        applied, _ = run(server, folder)
    assert applied == [] and len(server.schema) == 2
    assert "no pending migrations (1 already applied)" in caplog.messages


def test_only_new_migrations_run(server, folder, caplog):
    run(server, folder)
    (folder / "002_add_due_date.sql").write_text("ALTER TABLE a ADD due DATE NULL;\n")
    with caplog.at_level(logging.INFO, logger="migrations"):
        applied, _ = run(server, folder)
    assert applied == ["002_add_due_date.sql"] and len(server.schema) == 3
    assert "migration applied: 002_add_due_date.sql" in caplog.messages


def test_windows_line_endings_are_not_an_edit(server, folder):
    run(server, folder)
    (folder / "001_init.sql").write_bytes(
        b"CREATE TABLE a (id INT);\r\nGO\r\nCREATE TABLE b (id INT);\r\n"
    )
    assert run(server, folder)[0] == []


def test_editing_an_applied_migration_is_refused(server, folder):
    run(server, folder)
    (folder / "001_init.sql").write_text("CREATE TABLE a (id INT, extra INT);\n")
    with pytest.raises(MigrationError, match="edited after it was applied"):
        run(server, folder)


def test_failed_migration_saves_nothing(server, folder):
    run(server, folder)
    (folder / "002_bad.sql").write_text("CREATE TABLE ok (id INT);\nGO\nBOOM;\n")
    before = (list(server.schema), dict(server.applied))
    conn = FakeConnection(server)

    with pytest.raises(MigrationError, match="002_bad.sql"):
        apply_migrations(conn, folder)

    assert (server.schema, server.applied) == before
    assert conn.rollbacks == 1 and conn.released == 1


def test_lock_timeout_is_an_error(server, folder):
    server.lock_status = -1
    with pytest.raises(MigrationError, match="migration lock"):
        run(server, folder)


def test_database_ahead_of_the_code_is_only_a_warning(server, folder, caplog):
    run(server, folder)
    server.applied["009_newer.sql"] = "x"
    with caplog.at_level(logging.WARNING, logger="migrations"):
        assert run(server, folder)[0] == []
    assert any("009_newer.sql" in message for message in caplog.messages)


def test_discover_orders_by_number(folder):
    (folder / "010_later.sql").write_text("SELECT 1;")
    (folder / "002_next.sql").write_text("SELECT 1;")
    assert [m.name for m in discover(folder)] == ["001_init.sql", "002_next.sql", "010_later.sql"]


def test_two_migrations_with_the_same_number_are_refused(folder):
    (folder / "001_other.sql").write_text("SELECT 1;")
    with pytest.raises(MigrationError, match="share number 001"):
        discover(folder)


@pytest.mark.parametrize("name", ["bad name.sql", "1_short.sql", "002-dash.sql", "003_Upper.sql"])
def test_badly_named_files_are_refused(folder, name):
    (folder / name).write_text("SELECT 1;")
    with pytest.raises(MigrationError, match="bad migration file name"):
        discover(folder)


def test_the_real_migrations_folder_is_valid():
    from conftest import SERVICE_DIR

    migrations = discover(SERVICE_DIR / "migrations")
    assert migrations[0].name == "001_init.sql"
    assert all(m.batches for m in migrations)