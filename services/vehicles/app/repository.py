from datetime import date, datetime
from decimal import Decimal

COLUMNS = (
    "reg_num", "type", "brand", "model", "category", "daily_rate", "seat_num",
    "plate", "color", "fuel", "transmission", "km", "status", "location",
    "manufacture_date", "registration_date",
)
# Only these may be used as filters, updates or sort orders. Column names are
# put into the SQL text, so they must never come straight from the request.
FILTERABLE = ("status", "location", "type", "category", "fuel", "color")
UPDATABLE = ("category", "daily_rate", "status")
SORTS = {
    "price_asc": "daily_rate ASC, reg_num",
    "price_desc": "daily_rate DESC, reg_num",
    "km_asc": "km ASC, reg_num",
    "km_desc": "km DESC, reg_num",
}
DEFAULT_SORT = "reg_num"


def _clean(row):
    """SQL Server types -> JSON-friendly Python values."""
    out = {}
    for key, value in row.items():
        if isinstance(value, Decimal):
            value = float(value)
        elif isinstance(value, (date, datetime)):
            value = value.isoformat()
        out[key] = value
    return out


class VehicleRepository:
    """All SQL of the vehicles service: the vehicles table and the transport queue."""

    def __init__(self, conn):
        self.conn = conn

    # -- plumbing --------------------------------------------------------

    def _query(self, sql, params=()):
        cur = self.conn.cursor(as_dict=True)
        try:
            cur.execute(sql, params)
            return [_clean(row) for row in cur.fetchall()]
        finally:
            cur.close()

    def _execute(self, sql, params=()):
        cur = self.conn.cursor()
        try:
            cur.execute(sql, params)
            return cur.rowcount
        finally:
            cur.close()

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()

    # -- health ----------------------------------------------------------

    def ping(self):
        """Write and read back one row: proves the database is readable AND writable."""
        self._execute("UPDATE service_health SET checked_at = SYSUTCDATETIME() WHERE id = 1")
        rows = self._query("SELECT checked_at FROM service_health WHERE id = 1")
        self.commit()
        return bool(rows)

    # -- vehicles --------------------------------------------------------

    @staticmethod
    def _where(filters):
        clauses, params = [], []
        for column in FILTERABLE:
            if filters.get(column):
                clauses.append(f"{column} = %s")
                params.append(filters[column])
        sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return sql, params

    def list_vehicles(self, filters=None, sort_by=None, limit=100, offset=0):
        where, params = self._where(filters or {})
        order = SORTS.get(sort_by, DEFAULT_SORT)
        sql = (
            f"SELECT {', '.join(COLUMNS)} FROM vehicles{where} "
            f"ORDER BY {order} OFFSET %s ROWS FETCH NEXT %s ROWS ONLY"
        )
        return self._query(sql, params + [offset, limit])

    def count_vehicles(self, filters=None):
        where, params = self._where(filters or {})
        return self._query(f"SELECT COUNT(*) AS total FROM vehicles{where}", params)[0]["total"]

    def get_vehicle(self, reg_num):
        rows = self._query(
            f"SELECT {', '.join(COLUMNS)} FROM vehicles WHERE reg_num = %s", (reg_num,)
        )
        return rows[0] if rows else None

    def insert_vehicle(self, data):
        placeholders = ", ".join(["%s"] * len(COLUMNS))
        self._execute(
            f"INSERT INTO vehicles ({', '.join(COLUMNS)}) VALUES ({placeholders})",
            [data.get(column) for column in COLUMNS],
        )

    def update_vehicle(self, reg_num, fields):
        if not fields:
            raise ValueError("update requires at least one field to change")
        unknown = [key for key in fields if key not in UPDATABLE]
        if unknown:
            raise ValueError(f"cannot update: {', '.join(unknown)}")
        assignments = ", ".join(f"{key} = %s" for key in fields)
        return self._execute(
            f"UPDATE vehicles SET {assignments} WHERE reg_num = %s",
            list(fields.values()) + [reg_num],
        )

    def update_location(self, reg_num, location):
        return self._execute(
            "UPDATE vehicles SET location = %s WHERE reg_num = %s", (location, reg_num)
        )

    def stats(self):
        totals = self._query(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS available "
            "FROM vehicles"
        )[0]
        pending = self._query(
            "SELECT COUNT(*) AS pending FROM "
            "(SELECT 1 AS x FROM transport_queue GROUP BY origin, destination, mode) AS g"
        )[0]
        return {
            "total_vehicles": totals["total"],
            "available_vehicles": totals["available"] or 0,
            "pending_trips": pending["pending"],
        }

    # -- transport queue (persisted so it survives scale-to-zero) ---------

    def add_to_queue(self, reg_num, origin, destination, mode, final_destination):
        self._execute(
            "INSERT INTO transport_queue (reg_num, origin, destination, mode, final_destination) "
            "VALUES (%s, %s, %s, %s, %s)",
            (reg_num, origin, destination, mode, final_destination),
        )

    def waiting_in_queue(self, origin, destination, mode):
        return self._query(
            "SELECT id, reg_num, final_destination FROM transport_queue "
            "WHERE origin = %s AND destination = %s AND mode = %s ORDER BY id",
            (origin, destination, mode),
        )

    def remove_from_queue(self, ids):
        if not ids:
            return
        placeholders = ", ".join(["%s"] * len(ids))
        self._execute(f"DELETE FROM transport_queue WHERE id IN ({placeholders})", list(ids))

    def queue_groups(self):
        return self._query(
            "SELECT origin, destination, mode, COUNT(*) AS queued FROM transport_queue "
            "GROUP BY origin, destination, mode ORDER BY MIN(id)"
        )

    def is_queued(self, reg_num):
        return bool(self._query(
            "SELECT 1 AS found FROM transport_queue WHERE reg_num = %s", (reg_num,)
        ))