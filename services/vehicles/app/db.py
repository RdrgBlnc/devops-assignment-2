import logging
import time
from urllib.parse import unquote, urlparse

import pymssql

log = logging.getLogger("db")

FIRST_DELAY_S = 1.0
MAX_DELAY_S = 8.0


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

    def __init__(self, url, connector=pymssql.connect, sleep=time.sleep, clock=time.monotonic):
        self._params = parse_database_url(url)
        self._connector = connector
        self._sleep = sleep
        self._clock = clock

    def _open(self):
        return self._connector(
            **self._params,
            login_timeout=10,   # seconds to establish one connection attempt
            timeout=30,         # seconds for a single query
            tds_version="7.4",  # needed for Azure SQL
        )

    def connect(self, wait_s=0):
        """Open a connection, retrying for up to wait_s seconds.

        An Azure SQL serverless database that auto-paused refuses connections
        (error 40613 or a timeout) for up to about a minute while it resumes.
        We retry with exponential backoff (1s, 2s, 4s, then 8s between tries)
        until the time budget is used up, then raise DatabaseUnavailable.
        wait_s=0 means a single attempt, no retry.
        """
        deadline = self._clock() + wait_s
        delay = FIRST_DELAY_S
        attempt = 0
        while True:
            attempt += 1
            try:
                return self._open()
            except (pymssql.OperationalError, pymssql.InterfaceError) as exc:
                remaining = deadline - self._clock()
                reason = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
                if remaining <= 0:
                    raise DatabaseUnavailable(
                        f"database unreachable after {attempt} attempt(s): {reason}"
                    ) from exc
                pause = min(delay, remaining)
                log.warning(
                    "database not reachable (attempt %d): %s; retrying in %.1fs",
                    attempt, reason, pause,
                )
                self._sleep(pause)
                delay = min(delay * 2, MAX_DELAY_S)