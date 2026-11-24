import logging
import sys

from flask import Flask
from flask_cors import CORS

from .config import load_config
from .db import Database
from .deps import close_repo
from .errors import register_error_handlers
from .observability import register_request_logging
from .repository import VehicleRepository
from .routes.health import bp as health_bp
from .routes.transport import bp as transport_bp
from .routes.vehicles import bp as vehicles_bp
from .startup import initialise_database

log = logging.getLogger("app")


def _configure_logging():
    # Logs go to stdout: Docker shows them and Azure Container Apps collects them.
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            stream=sys.stdout,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )


def create_app(config=None, database=None, migrate=True, repo_factory=None):
    """Build the Flask app.

    config, database and repo_factory can be passed in (tests do this); by default
    they come from the environment. With migrate=True the database schema is
    brought up to date before the app is returned, so it never serves requests
    without it.
    """
    _configure_logging()
    config = config or load_config()
    database = database or Database(config.database_url)

    def default_repo_factory(wait_s=None):
        # one connection per request; a request waits at most DB_REQUEST_WAIT_S
        wait = config.db_request_wait_s if wait_s is None else wait_s
        return VehicleRepository(database.connect(wait))

    app = Flask(__name__)
    app.config["CFG"] = config
    app.config["DATABASE"] = database
    app.config["REPO_FACTORY"] = repo_factory or default_repo_factory

    log.info("service starting (version %s)", config.git_sha)
    if migrate:
        initialise_database(database, config.db_retry_total_s)

    # No secret key: this service is a stateless JSON API, it has no sessions
    # or cookies to sign.
    app.teardown_appcontext(close_repo)
    # Only the UI's own address may call this API from a browser; no cookies are involved.
    CORS(
        app,
        origins=config.cors_origins,
        methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type"],
        max_age=600,
    )
    register_error_handlers(app)
    register_request_logging(app)
    app.register_blueprint(health_bp)
    app.register_blueprint(vehicles_bp)
    app.register_blueprint(transport_bp)
    return app