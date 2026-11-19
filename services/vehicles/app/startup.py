import logging
from pathlib import Path

from .migrate import apply_migrations
from .seed import load_seed

log = logging.getLogger("startup")

SERVICE_DIR = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = SERVICE_DIR / "migrations"
SEED_DIR = SERVICE_DIR / "seed"


def initialise_database(database, wait_s, migrations_dir=MIGRATIONS_DIR, seed_dir=SEED_DIR):
    """Bring this service's own database up to date before it accepts requests.

    Waits up to wait_s seconds for the database (an Azure SQL serverless database
    that auto-paused needs up to about a minute to resume), applies any pending
    migrations, then loads the seed data into any table that is still empty.
    A fresh, empty database ends up with its schema and sample data, with nothing
    created by hand and no database file committed.
    """
    try:
        conn = database.connect(wait_s)
    except Exception as exc:
        log.error("database not available at startup: %s", exc)
        raise
    try:
        apply_migrations(conn, migrations_dir)
        load_seed(conn, seed_dir)
    finally:
        conn.close()