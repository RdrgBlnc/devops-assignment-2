import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    port: int
    database_url: str
    cors_origins: list
    git_sha: str
    db_retry_total_s: float
    db_request_wait_s: float
    vehicles_url: str
    vehicles_timeout_s: float


def _number(env, name, default, cast, minimum):
    raw = env.get(name, default)
    try:
        value = cast(raw)
    except (TypeError, ValueError):
        raise RuntimeError(f"{name} must be a number, got {raw!r}") from None
    if value < minimum:
        raise RuntimeError(f"{name} must be >= {minimum}, got {value}")
    return value


def load_config(env=None) -> Config:
    env = os.environ if env is None else env

    # secret: no default, the service refuses to start without it
    database_url = env.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")

    origins = [o.strip() for o in env.get("CORS_ORIGIN", "http://localhost:8080").split(",")]

    return Config(
        port=_number(env, "PORT", 8000, int, 1),
        database_url=database_url,
        cors_origins=[o for o in origins if o],
        git_sha=env.get("GIT_SHA", "dev"),
        db_retry_total_s=_number(env, "DB_RETRY_TOTAL_S", 90, float, 0),
        db_request_wait_s=_number(env, "DB_REQUEST_WAIT_S", 20, float, 0),
        # the seam: where the vehicles service lives, never hardcoded
        vehicles_url=env.get("VEHICLES_URL", "http://vehicles:8000").rstrip("/"),
        vehicles_timeout_s=_number(env, "VEHICLES_TIMEOUT_S", 2, float, 0.1),
    )