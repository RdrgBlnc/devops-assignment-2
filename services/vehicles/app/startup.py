import logging
from pathlib import Path

from .migrate import apply_migrations

log = logging.getLogger("startup")

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def initialise_database(database, wait_s, migrations_dir=MIGRATIONS_DIR):
    """Bring this service's own database up to date before it accepts requests.

    Waits up to wait_s seconds for the database (an Azure SQL serverless database
    that auto-paused needs up to about a minute to resume), then applies any
    pending migrations. A fresh, empty database gets the whole schema here, so
    nothing has to be created by hand and no database file is committed.
    """
    try:
        conn = database.connect(wait_s)
    except Exception as exc:
        log.error("database not available at startup: %s", exc)
        raise
    try:
        apply_migrations(conn, migrations_dir)
    finally:
        conn.close()