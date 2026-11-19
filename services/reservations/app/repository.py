from datetime import date, datetime
from decimal import Decimal

RENTAL_COLUMNS = ("customer_id", "car_reg_num", "start_date", "end_date", "total_price", "status")
RENTAL_SELECT = "id, " + ", ".join(RENTAL_COLUMNS)
RENTAL_FILTERS = ("status", "customer_id", "car_reg_num")
RENTAL_UPDATABLE = ("status", "end_date", "total_price")
CUSTOMER_SELECT = "id, name, surname, email, location"


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


def _like(term):
    """Escape LIKE wildcards so a search for '50%' means a literal 50%."""
    for char in ("[", "%", "_"):
        term = term.replace(char, f"[{char}]")
    return f"%{term}%"


class ReservationRepository:
    """All SQL of the reservations service: the customers and rentals tables.

    car_reg_num is a plain value here, not a foreign key: vehicles live in the
    other service's database, so the link is checked over HTTP, not by SQL.
    """

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

    # -- customers -------------------------------------------------------

    @staticmethod
    def _customer_where(location, search):
        clauses, params = [], []
        if location:
            clauses.append("location = %s")
            params.append(location)
        if search:
            clauses.append("(name LIKE %s OR surname LIKE %s OR email LIKE %s)")
            params.extend([_like(search)] * 3)
        sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return sql, params

    def list_customers(self, location=None, search=None, limit=100, offset=0):
        where, params = self._customer_where(location, search)
        return self._query(
            f"SELECT {CUSTOMER_SELECT} FROM customers{where} "
            "ORDER BY id OFFSET %s ROWS FETCH NEXT %s ROWS ONLY",
            params + [offset, limit],
        )

    def count_customers(self, location=None, search=None):
        where, params = self._customer_where(location, search)
        return self._query(f"SELECT COUNT(*) AS total FROM customers{where}", params)[0]["total"]

    def get_customer(self, customer_id):
        rows = self._query(
            f"SELECT {CUSTOMER_SELECT} FROM customers WHERE id = %s", (customer_id,)
        )
        return rows[0] if rows else None

    # -- rentals ---------------------------------------------------------

    @staticmethod
    def _rental_where(filters):
        clauses, params = [], []
        for column in RENTAL_FILTERS:
            if filters.get(column) not in (None, ""):
                clauses.append(f"{column} = %s")
                params.append(filters[column])
        sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return sql, params

    def list_rentals(self, filters=None, limit=100, offset=0):
        where, params = self._rental_where(filters or {})
        return self._query(
            f"SELECT {RENTAL_SELECT} FROM rentals{where} "
            "ORDER BY id OFFSET %s ROWS FETCH NEXT %s ROWS ONLY",
            params + [offset, limit],
        )

    def count_rentals(self, filters=None):
        where, params = self._rental_where(filters or {})
        return self._query(f"SELECT COUNT(*) AS total FROM rentals{where}", params)[0]["total"]

    def get_rental(self, rental_id):
        rows = self._query(f"SELECT {RENTAL_SELECT} FROM rentals WHERE id = %s", (rental_id,))
        return rows[0] if rows else None

    def insert_rental(self, data):
        """Insert a rental and return its new id (IDENTITY column)."""
        placeholders = ", ".join(["%s"] * len(RENTAL_COLUMNS))
        rows = self._query(
            f"INSERT INTO rentals ({', '.join(RENTAL_COLUMNS)}) OUTPUT INSERTED.id "
            f"VALUES ({placeholders})",
            [data.get(column) for column in RENTAL_COLUMNS],
        )
        return rows[0]["id"]

    def update_rental(self, rental_id, fields):
        if not fields:
            raise ValueError("update requires at least one field to change")
        unknown = [key for key in fields if key not in RENTAL_UPDATABLE]
        if unknown:
            raise ValueError(f"cannot update: {', '.join(unknown)}")
        assignments = ", ".join(f"{key} = %s" for key in fields)
        return self._execute(
            f"UPDATE rentals SET {assignments} WHERE id = %s",
            list(fields.values()) + [rental_id],
        )

    def stats(self):
        rentals = self._query(
            "SELECT SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active FROM rentals"
        )[0]
        customers = self._query("SELECT COUNT(*) AS total FROM customers")[0]
        return {
            "active_rentals": rentals["active"] or 0,
            "total_customers": customers["total"],
        }
