import csv
import logging
from decimal import Decimal
from pathlib import Path

from .repository import RENTAL_COLUMNS

log = logging.getLogger("seed")

CHUNK = 100  # rows per INSERT (SQL Server allows at most 1000 per statement)
CUSTOMER_COLUMNS = ("id", "name", "surname", "email", "location")
# id is included: rentals refer to customers by id, so the seed must keep the same ids.
RENTAL_SEED_COLUMNS = ("id",) + RENTAL_COLUMNS
CONVERTERS = {"id": int, "customer_id": int, "total_price": Decimal}


def _read_csv(path, columns):
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in columns if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path.name} is missing columns: {', '.join(missing)}")
        return [
            {c: (CONVERTERS.get(c, str)(row[c]) if row[c] != "" else None) for c in columns}
            for row in reader
        ]


def _insert_rows(cur, table, columns, rows):
    names = ", ".join(columns)
    one = "(" + ", ".join(["%s"] * len(columns)) + ")"
    for start in range(0, len(rows), CHUNK):
        chunk = rows[start:start + CHUNK]
        params = [row[c] for row in chunk for c in columns]
        values = ", ".join([one] * len(chunk))
        cur.execute(f"INSERT INTO {table} ({names}) VALUES {values}", params)


def _seed_table(cur, seed_dir, table, columns):
    path = Path(seed_dir) / f"{table}.csv"
    if not path.exists():
        log.info("no seed file %s, skipping", path.name)
        return 0
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    if cur.fetchone()[0] > 0:
        log.info("seed: %s already present, skipping", table)
        return 0
    rows = _read_csv(path, columns)
    # The id column is IDENTITY (auto-numbered); to keep the exported ids we must
    # switch that off while inserting. New rows after this continue from the highest id.
    cur.execute(f"SET IDENTITY_INSERT {table} ON")
    try:
        _insert_rows(cur, table, columns, rows)
    finally:
        cur.execute(f"SET IDENTITY_INSERT {table} OFF")
    log.info("seed: loaded %d %s", len(rows), table)
    return len(rows)


def load_seed(conn, seed_dir):
    """Load customers, then rentals (they refer to customers), each only into an empty table.

    Idempotent and safe to run on every boot. One transaction: all of it or none.
    """
    cur = conn.cursor()
    try:
        loaded = _seed_table(cur, seed_dir, "customers", CUSTOMER_COLUMNS)
        loaded += _seed_table(cur, seed_dir, "rentals", RENTAL_SEED_COLUMNS)
        conn.commit()
        return loaded
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()