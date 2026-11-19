"""Export the Assignment 1 SQLite database into the seed files the services load.

Run once from the repository root, with the old database still at src/vehicles.db:

    python tools/export_seed.py

Writes:
    services/vehicles/seed/vehicles.csv
    services/reservations/seed/customers.csv
    services/reservations/seed/rentals.csv

Development tool only: it is not copied into any image. Standard library only.
"""
import argparse
import csv
import sqlite3
import sys
from pathlib import Path

# table -> (service, columns in the order written)
EXPORTS = {
    "vehicles": ("vehicles", [
        "reg_num", "type", "brand", "model", "category", "daily_rate", "seat_num", "plate",
        "color", "fuel", "transmission", "km", "status", "location",
        "manufacture_date", "registration_date",
    ]),
    "customers": ("reservations", ["id", "name", "surname", "email", "location"]),
    "rentals": ("reservations", [
        "id", "customer_id", "car_reg_num", "start_date", "end_date", "total_price", "status",
    ]),
}
ORDER_BY = {"vehicles": "reg_num", "customers": "id", "rentals": "id"}

# Maximum text lengths of the columns in each service's 001_init.sql.
MAX_LENGTH = {
    "vehicles": {
        "reg_num": 32, "type": 10, "brand": 50, "model": 100, "category": 10, "plate": 16,
        "color": 30, "fuel": 10, "transmission": 10, "status": 12, "location": 12,
    },
    "customers": {"name": 50, "surname": 50, "email": 100, "location": 12},
    "rentals": {"car_reg_num": 32, "status": 12},
}


def export_table(conn, table, root):
    service, columns = EXPORTS[table]
    rows = conn.execute(
        f"SELECT {', '.join(columns)} FROM {table} ORDER BY {ORDER_BY[table]}"
    ).fetchall()

    problems = []
    for row in rows:
        record = dict(zip(columns, row))
        for column, limit in MAX_LENGTH[table].items():
            value = record[column]
            if value is not None and len(str(value)) > limit:
                problems.append(
                    f"{table}.{column}: {value!r} is {len(str(value))} chars, limit {limit}"
                )
        if table == "rentals" and not record["end_date"] > record["start_date"]:
            problems.append(f"rentals id {record['id']}: end_date is not after start_date")
    if problems:
        return None, problems

    out = root / "services" / service / "seed" / f"{table}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow(["" if value is None else value for value in row])
    return (out, len(rows)), []


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default="src/vehicles.db", help="SQLite file to read")
    parser.add_argument("--root", default=".", help="repository root to write into")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"error: {db_path} not found (run this from the repository root)", file=sys.stderr)
        return 1

    conn = sqlite3.connect(db_path)
    failed = False
    for table in EXPORTS:
        result, problems = export_table(conn, table, Path(args.root))
        if problems:
            failed = True
            for problem in problems[:10]:
                print(f"error: {problem}", file=sys.stderr)
            if len(problems) > 10:
                print(f"error: ... and {len(problems) - 10} more in {table}", file=sys.stderr)
            continue
        out, count = result
        print(f"{table}: {count} rows -> {out}")
    conn.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())