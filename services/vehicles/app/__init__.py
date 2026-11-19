import logging
import sys

from flask import Flask

from .config import load_config
from .db import Database
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


def create_app(config=None, database=None, migrate=True):
    """Build the Flask app.

    config and database can be passed in (tests do this); by default they come
    from the environment. With migrate=True the database schema is brought up
    to date before the app is returned, so it never serves requests without it.
    """
    _configure_logging()
    config = config or load_config()
    database = database or Database(config.database_url)

    app = Flask(__name__)
    app.config["CFG"] = config
    app.config["DATABASE"] = database

    log.info("service starting (version %s)", config.git_sha)
    if migrate:
        initialise_database(database, config.db_retry_total_s)

    # No secret key: this service is a stateless JSON API, it has no sessions
    # or cookies to sign. Routes are registered here as they are rewritten.

    return app