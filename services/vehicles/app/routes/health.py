import logging

from flask import Blueprint, current_app, jsonify

from ..deps import get_repo

log = logging.getLogger("health")
bp = Blueprint("health", __name__)
SERVICE = "vehicles"


@bp.get("/health")
def health():
    """200 when the service can read and write its own database, 503 when it cannot.

    The other service is deliberately not checked: if it is down, this service is still
    healthy, and it answers its own 503s for requests that need it.
    """
    body = {"service": SERVICE, "version": current_app.config["CFG"].git_sha}
    try:
        healthy = get_repo().ping()
    except Exception as error:
        log.warning("health check failed: %s", error)
        healthy = False
    body.update(status="ok" if healthy else "unavailable", database="ok" if healthy else "down")
    response = jsonify(body)
    response.status_code = 200 if healthy else 503
    return response