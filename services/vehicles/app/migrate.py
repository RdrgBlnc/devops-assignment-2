import hashlib
import logging
import re
from pathlib import Path

log = logging.getLogger("migrations")

LOCK_RESOURCE = "schema_migrations"
LOCK_TIMEOUT_MS = 60000
FILE_PATTERN = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")
# SQL Server batch separator: a line containing only GO (it is not real SQL,
# the driver cannot send it, so we split the file on it ourselves).
_GO = re.compile(r"^[ \t]*GO[ \t]*$", re.IGNORECASE | re.MULTILINE)

CREATE_TABLE = (
    "IF OBJECT_ID('schema_migrations', 'U') IS NULL "
    "CREATE TABLE schema_migrations ("
    "version NVARCHAR(100) NOT NULL PRIMARY KEY, "
    "checksum NVARCHAR(64) NOT NULL, "
    "applied_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())"
)


class MigrationError(Exception):
    """A migration cannot be applied, or the migration folder is inconsistent."""


class Migration:
    def __init__(self, name, sql):
        self.name = name
        self.batches = split_batches(sql)
        # line endings are normalised so Windows (CRLF) and Linux (LF) agree
        self.checksum = hashlib.sha256(sql.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def split_batches(sql):
    return [batch.strip() for batch in _GO.split(sql) if batch.strip()]


def discover(directory):
    """Read migrations/NNN_name.sql in numeric order. Fails on bad names or repeated numbers."""
    migrations, seen = [], {}
    for path in sorted(Path(directory).glob("*.sql")):
        match = FILE_PATTERN.match(path.name)
        if not match:
            raise MigrationError(f"bad migration file name {path.name!r}: use NNN_name.sql")
        number = match.group(1)
        if number in seen:
            raise MigrationError(f"migrations {seen[number]} and {path.name} share number {number}")
        seen[number] = path.name
        migrations.append(Migration(path.name, path.read_text(encoding="utf-8-sig")))
    return migrations


def _acquire_lock(cur):
    # Two copies of the service can overlap for a moment during a deploy (the new
    # revision starts before the old one stops). The lock makes the second one wait.
    cur.execute(
        "DECLARE @r INT; "
        "EXEC @r = sp_getapplock @Resource = %s, @LockMode = 'Exclusive', "
        "@LockOwner = 'Session', @LockTimeout = " + str(LOCK_TIMEOUT_MS) + "; "
        "SELECT @r AS status",
        (LOCK_RESOURCE,),
    )
    status = cur.fetchone()[0]
    if status < 0:
        raise MigrationError(f"could not get the migration lock (status {status})")


def _release_lock(cur):
    try:
        cur.execute(
            "EXEC sp_releaseapplock @Resource = %s, @LockOwner = 'Session'", (LOCK_RESOURCE,)
        )
    except Exception as exc:  # the connection may already be broken: nothing more to do
        log.warning("could not release migration lock: %s", exc)


def _apply_one(conn, cur, migration):
    try:
        for batch in migration.batches:
            cur.execute(batch)
        cur.execute(
            "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
            (migration.name, migration.checksum),
        )
        conn.commit()  # the schema change and its record are saved together, or not at all
    except Exception as exc:
        conn.rollback()
        raise MigrationError(
            f"migration {migration.name} failed and was rolled back: {exc}"
        ) from exc
    log.info("migration applied: %s", migration.name)


def apply_migrations(conn, directory):
    """Apply every migration not yet recorded in schema_migrations, in order.

    Each migration runs exactly once. Returns the names applied (empty on a second boot).
    An already-applied file that was edited is an error: corrections go in a new migration.
    """
    migrations = discover(directory)  # check the folder before touching the database
    cur = conn.cursor()
    try:
        _acquire_lock(cur)
        try:
            cur.execute(CREATE_TABLE)
            conn.commit()
            cur.execute("SELECT version, checksum FROM schema_migrations")
            applied = {version: checksum for version, checksum in cur.fetchall()}

            known = {m.name for m in migrations}
            for version in sorted(set(applied) - known):
                log.warning("database has migration %s that this version does not have", version)

            pending = []
            for migration in migrations:
                if migration.name not in applied:
                    pending.append(migration)
                elif applied[migration.name] != migration.checksum:
                    raise MigrationError(
                        f"{migration.name} was edited after it was applied; "
                        "add a new migration instead of changing an applied one"
                    )

            for migration in pending:
                _apply_one(conn, cur, migration)

            if not pending:
                log.info("no pending migrations (%d already applied)", len(applied))
            return [m.name for m in pending]
        finally:
            _release_lock(cur)
    finally:
        cur.close()
