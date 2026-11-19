from urllib.parse import unquote, urlparse

import pymssql


class DatabaseUnavailable(Exception):
    """The database cannot be reached (down, paused or wrong address)."""


def parse_database_url(url):
    """Split mssql+pymssql://user:password@host:1433/database into connect arguments.

    Special characters in the password must be percent-encoded in the URL.
    """
    parsed = urlparse(url)
    database = parsed.path.lstrip("/")
    if not parsed.hostname or not database:
        raise ValueError(
            "DATABASE_URL must look like mssql+pymssql://user:password@host:1433/database"
        )
    return {
        "server": parsed.hostname,
        "port": parsed.port or 1433,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": database,
    }


class Database:
    """Knows how to open a connection to this service's own database.

    No shared global connection: each caller gets its own connection and
    closes it, so a paused or restarted database never leaves a dead one behind.
    """

    def __init__(self, url, connector=pymssql.connect):
        self._params = parse_database_url(url)
        self._connector = connector

    def connect(self):
        try:
            return self._connector(
                **self._params,
                login_timeout=10,   # seconds to establish the connection
                timeout=30,         # seconds for a single query
                tds_version="7.4",  # needed for Azure SQL
            )
        except (pymssql.OperationalError, pymssql.InterfaceError) as exc:
            raise DatabaseUnavailable(str(exc)) from exc
