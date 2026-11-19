from flask import Flask

from .config import load_config


def create_app(config=None):
    config = config or load_config()

    app = Flask(__name__)
    app.config["CFG"] = config

    # No secret key: this service is a stateless JSON API, it has no sessions
    # or cookies to sign. Routes are registered here as they are rewritten.

    return app