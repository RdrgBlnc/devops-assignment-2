import csv
import logging
from decimal import Decimal
from pathlib import Path

from .repository import COLUMNS

log = logging.getLogger("seed")

CHUNK = 100  # rows per INSERT (SQL Server allows at most 1000 per statement)
CONVERTERS = {"daily_rate": Decimal, "seat_num": int, "km": int}


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


def load_seed(conn, seed_dir):
    """Load seed/vehicles.csv into an empty vehicles table. Safe to run on every boot.

    Idempotent: if the table already has rows (seeded before, or changed by users)
    nothing is touched. The whole load is one transaction: all of it or none.
    """
    path = Path(seed_dir) / "vehicles.csv"
    if not path.exists():
        log.info("no seed file %s, skipping", path.name)
        return 0
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM vehicles")
        if cur.fetchone()[0] > 0:
            log.info("seed: vehicles already present, skipping")
            return 0
        rows = _read_csv(path, COLUMNS)
        _insert_rows(cur, "vehicles", COLUMNS, rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    log.info("seed: loaded %d vehicles", len(rows))
    return len(rows)