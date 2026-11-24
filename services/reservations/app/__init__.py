import logging
import sys

from flask import Flask

from .config import load_config
from .clients.vehicles import VehiclesClient
from .db import Database
from .deps import close_repo
from .errors import register_error_handlers
from .observability import register_request_logging
from .repository import ReservationRepository
from .routes.customers import bp as customers_bp
from .routes.health import bp as health_bp
from .routes.rentals import bp as rentals_bp
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


def create_app(config=None, database=None, migrate=True, repo_factory=None, vehicles_client=None):
    """Build the Flask app.

    config, database, repo_factory and vehicles_client can be passed in (tests do this); by default
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
        return ReservationRepository(database.connect(wait))

    app = Flask(__name__)
    app.config["CFG"] = config
    app.config["DATABASE"] = database
    app.config["REPO_FACTORY"] = repo_factory or default_repo_factory
    # how this service asks the vehicles service about a vehicle (the only cross-service call)
    app.config["VEHICLES_CLIENT"] = vehicles_client or VehiclesClient(
        config.vehicles_url, config.vehicles_timeout_s
    )

    log.info("service starting (version %s)", config.git_sha)
    if migrate:
        initialise_database(database, config.db_retry_total_s)

    # No secret key: this service is a stateless JSON API, it has no sessions
    # or cookies to sign.
    app.teardown_appcontext(close_repo)
    register_error_handlers(app)
    register_request_logging(app)
    app.register_blueprint(health_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(rentals_bp)
    return app