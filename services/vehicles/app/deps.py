import logging

from flask import current_app, g

log = logging.getLogger("deps")


def get_repo():
    """The repository for the current request: one database connection per request."""
    if "repo" not in g:
        g.repo = current_app.config["REPO_FACTORY"]()
    return g.repo


def close_repo(exc=None):
    repo = g.pop("repo", None)
    if repo is None:
        return
    try:
        repo.rollback()  # anything a route did not commit explicitly is discarded
    except Exception as error:
        log.warning("rollback failed: %s", error)
    finally:
        repo.close()