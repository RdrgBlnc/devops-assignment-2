import logging
import time

from flask import g, request

log = logging.getLogger("request")


def register_request_logging(app):
    """One log line per request, on stdout: method, path, status and how long it took.

    The query string is left out on purpose: it can carry search text or ids.
    """

    @app.before_request
    def start_timer():
        g.started_at = time.perf_counter()

    @app.after_request
    def log_request(response):
        started_at = g.get("started_at")
        ms = (time.perf_counter() - started_at) * 1000 if started_at is not None else 0.0
        log.info("%s %s -> %s in %.1f ms", request.method, request.path, response.status_code, ms)
        return response