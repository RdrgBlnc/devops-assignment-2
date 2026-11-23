import logging

import pymssql
from flask import jsonify
from werkzeug.exceptions import HTTPException

from .db import DatabaseUnavailable

log = logging.getLogger("errors")


class ApiError(Exception):
    """An error the client caused or can act on: becomes a JSON response."""

    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def error_response(status, code, message):
    response = jsonify({"error": code, "message": message})
    response.status_code = status
    return response


def register_error_handlers(app):
    """Every error leaves the service as JSON, never as an HTML page or a stack trace."""

    @app.errorhandler(ApiError)
    def api_error(exc):
        return error_response(exc.status, exc.code, exc.message)

    def database_unavailable(exc):
        log.warning("database unavailable: %s", exc)
        return error_response(
            503, "database_unavailable", "The database is starting up, try again in a few seconds."
        )

    # a failed connection (paused database) or one lost in the middle of a request
    for error_class in (DatabaseUnavailable, pymssql.OperationalError, pymssql.InterfaceError):
        app.register_error_handler(error_class, database_unavailable)

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return error_response(exc.code, exc.name.lower().replace(" ", "_"), exc.description)

    @app.errorhandler(Exception)
    def unexpected(exc):
        log.exception("unhandled error")  # the stack trace goes to the log, not to the client
        return error_response(500, "internal_error", "Something went wrong.")