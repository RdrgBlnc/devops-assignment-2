from flask import Blueprint, jsonify, request

from ..deps import get_repo
from ..domain.rental import Location
from ..errors import ApiError

bp = Blueprint("customers", __name__)

DEFAULT_LIMIT = 100
MAX_LIMIT = 500
MAX_SEARCH = 100


def int_arg(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ApiError(400, "invalid_query", f"{name} must be a whole number")
    if not minimum <= value <= maximum:
        raise ApiError(400, "invalid_query", f"{name} must be between {minimum} and {maximum}")
    return value


def enum_arg(enum, name):
    value = request.args.get(name, "")
    if not value:
        return None
    try:
        return enum(value).value
    except ValueError:
        allowed = ", ".join(member.value for member in enum)
        raise ApiError(400, "invalid_query", f"{name} must be one of: {allowed}")


@bp.get("/customers")
def list_customers():
    """Customers, for the 'pick a customer' sign-in screen. Filter by location or search text."""
    location = enum_arg(Location, "location")
    search = request.args.get("search", "").strip()
    if len(search) > MAX_SEARCH:
        raise ApiError(400, "invalid_query", f"search must be at most {MAX_SEARCH} characters")
    limit = int_arg("limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
    offset = int_arg("offset", 0, 0, 10_000_000)

    repo = get_repo()
    return jsonify({
        "items": repo.list_customers(location, search or None, limit, offset),
        "total": repo.count_customers(location, search or None),
        "limit": limit,
        "offset": offset,
    })


@bp.get("/customers/<int:customer_id>")
def get_customer(customer_id):
    customer = get_repo().get_customer(customer_id)
    if customer is None:
        raise ApiError(404, "customer_not_found", f"No customer with id {customer_id}")
    return jsonify(customer)