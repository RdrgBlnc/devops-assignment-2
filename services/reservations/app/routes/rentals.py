from datetime import date

from flask import Blueprint, jsonify, request

from ..deps import get_repo
from ..domain.rental import Location, RentalBuilder, RentalStatus
from ..errors import ApiError
from .customers import DEFAULT_LIMIT, MAX_LIMIT, enum_arg, int_arg

bp = Blueprint("rentals", __name__)

RENTAL_FIELDS = ("customer_id", "car_reg_num", "start_date", "end_date")
MAX_REG_NUM = 32


def _json_object():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "invalid_json", "The request body must be a JSON object")
    return data


def _iso_date(field, value):
    if not isinstance(value, str):
        raise ApiError(400, "invalid_value", f"{field} must be a date written as YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ApiError(400, "invalid_value", f"{field} must be a date written as YYYY-MM-DD")


def build_rental(data, daily_rate, today=None):
    """Check the request body, then let RentalBuilder apply the business rules.

    Anything wrong raises ApiError(400); nothing reaches the database unchecked.
    The client may only send who, which vehicle and when: the price and the status
    are decided here, never taken from the request.
    """
    unknown = [key for key in data if key not in RENTAL_FIELDS]
    if unknown:
        raise ApiError(400, "invalid_field", f"Unknown fields: {', '.join(unknown)}")
    missing = [key for key in RENTAL_FIELDS if data.get(key) in (None, "")]
    if missing:
        raise ApiError(400, "missing_field", f"Missing fields: {', '.join(missing)}")

    customer_id = data["customer_id"]
    if isinstance(customer_id, bool) or not isinstance(customer_id, int) or customer_id < 1:
        raise ApiError(400, "invalid_value", "customer_id must be a whole number of 1 or more")
    reg_num = data["car_reg_num"]
    if not isinstance(reg_num, str) or not reg_num.strip() or len(reg_num.strip()) > MAX_REG_NUM:
        raise ApiError(
            400, "invalid_value", f"car_reg_num must be a text of 1 to {MAX_REG_NUM} characters"
        )

    try:
        return (
            RentalBuilder(today)
            .with_customer_id(customer_id)
            .with_car_reg_num(reg_num)
            .with_start_date(_iso_date("start_date", data["start_date"]))
            .with_end_date(_iso_date("end_date", data["end_date"]))
            .with_daily_rate(daily_rate)
            .build()
        )
    except ValueError as error:
        raise ApiError(400, "invalid_rental", str(error))


@bp.get("/meta")
def meta():
    """The allowed values of the list fields, so the UI can build its dropdowns."""
    return jsonify({
        "locations": [member.value for member in Location],
        "rental_statuses": [member.value for member in RentalStatus],
    })


@bp.get("/stats")
def stats():
    return jsonify(get_repo().stats())


@bp.get("/rentals")
def list_rentals():
    filters = {}
    status = enum_arg(RentalStatus, "status")
    if status:
        filters["status"] = status
    if request.args.get("customer_id"):
        filters["customer_id"] = int_arg("customer_id", None, 1, 2_147_483_647)
    if request.args.get("car_reg_num"):
        filters["car_reg_num"] = request.args["car_reg_num"][:32]
    limit = int_arg("limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
    offset = int_arg("offset", 0, 0, 10_000_000)

    repo = get_repo()
    return jsonify({
        "items": repo.list_rentals(filters, limit, offset),
        "total": repo.count_rentals(filters),
        "limit": limit,
        "offset": offset,
    })


@bp.get("/rentals/<int:rental_id>")
def get_rental(rental_id):
    rental = get_repo().get_rental(rental_id)
    if rental is None:
        raise ApiError(404, "rental_not_found", f"No rental with id {rental_id}")
    return jsonify(rental)