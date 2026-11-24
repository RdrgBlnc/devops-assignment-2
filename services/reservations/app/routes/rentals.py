from datetime import date

import pymssql
from flask import Blueprint, current_app, jsonify, request

from ..clients.vehicles import VehiclesUnavailable
from ..deps import get_repo
from ..domain.rental import (
    Location, RentalBuilder, RentalStatus, check_transition, new_total_price,
)
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


@bp.post("/rentals")
def create_rental():
    data = _json_object()
    # Dry run with a placeholder rate: every problem in the request itself is reported
    # before the vehicles service is called or the database is touched.
    build_rental(data, daily_rate=1)

    repo = get_repo()
    customer_id = data["customer_id"]
    if repo.get_customer(customer_id) is None:
        raise ApiError(404, "customer_not_found", f"No customer with id {customer_id}")

    reg_num = data["car_reg_num"].strip()
    try:
        vehicle = current_app.config["VEHICLES_CLIENT"].get_vehicle(reg_num)
    except VehiclesUnavailable as error:
        # designed failure: no rental is created while the vehicles service cannot confirm the car
        raise ApiError(
            503, "vehicles_unavailable",
            f"The vehicles service is not available ({error}); try again in a moment",
        )
    if vehicle is None:
        raise ApiError(404, "vehicle_not_found", f"No vehicle with reg_num '{reg_num}'")
    if vehicle["status"] != "active":
        raise ApiError(
            409, "vehicle_not_active",
            f"Vehicle '{reg_num}' is {vehicle['status']}; only active vehicles can be rented",
        )

    rental = build_rental(data, vehicle["daily_rate"])
    try:
        rental_id = repo.insert_rental({
            "customer_id": rental.customer_id,
            "car_reg_num": rental.car_reg_num,
            "start_date": rental.start_date.isoformat(),
            "end_date": rental.end_date.isoformat(),
            "total_price": rental.total_price,
            "status": rental.status.value,
        })
    except pymssql.IntegrityError:  # the customer was deleted between the check and the insert
        raise ApiError(404, "customer_not_found", f"No customer with id {customer_id}")
    repo.commit()

    response = jsonify(repo.get_rental(rental_id))
    response.status_code = 201
    response.headers["Location"] = f"/rentals/{rental_id}"
    return response


def _load_rental(rental_id):
    rental = get_repo().get_rental(rental_id)
    if rental is None:
        raise ApiError(404, "rental_not_found", f"No rental with id {rental_id}")
    return rental


@bp.patch("/rentals/<int:rental_id>")
def update_rental(rental_id):
    """Change a rental's status or end date. Status changes follow the allowed transitions."""
    data = _json_object()
    unknown = [key for key in data if key not in ("status", "end_date")]
    if unknown:
        raise ApiError(
            400, "invalid_field",
            f"Cannot update {', '.join(unknown)}; only status and end_date can be changed",
        )
    if not data:
        raise ApiError(400, "missing_field", "Send status and/or end_date")

    fields = {}
    if "status" in data:
        status = data["status"]
        if status not in [member.value for member in RentalStatus]:
            allowed = ", ".join(member.value for member in RentalStatus)
            raise ApiError(400, "invalid_value", f"status must be one of: {allowed}")
    new_end = _iso_date("end_date", data["end_date"]) if "end_date" in data else None

    rental = _load_rental(rental_id)
    if "status" in data:
        try:
            check_transition(rental["status"], status)
        except ValueError as error:
            raise ApiError(409, "invalid_change", str(error))
        fields["status"] = status
    if new_end is not None:
        if rental["status"] in ("returned", "canceled"):
            raise ApiError(
                409, "invalid_change", f"A {rental['status']} rental can no longer be changed"
            )
        try:
            fields["total_price"] = new_total_price(
                rental["total_price"], date.fromisoformat(rental["start_date"]),
                date.fromisoformat(rental["end_date"]), new_end,
            )
        except ValueError as error:
            raise ApiError(400, "invalid_rental", str(error))
        fields["end_date"] = new_end.isoformat()

    repo = get_repo()
    repo.update_rental(rental_id, fields)
    repo.commit()
    return jsonify(repo.get_rental(rental_id))


@bp.post("/rentals/<int:rental_id>/cancel")
def cancel_rental(rental_id):
    """A customer cancels one of their own rentals."""
    data = _json_object()
    unknown = [key for key in data if key != "customer_id"]
    if unknown:
        raise ApiError(400, "invalid_field", f"Unknown fields: {', '.join(unknown)}")
    customer_id = data.get("customer_id")
    if isinstance(customer_id, bool) or not isinstance(customer_id, int) or customer_id < 1:
        raise ApiError(400, "invalid_value", "customer_id must be a whole number of 1 or more")

    rental = _load_rental(rental_id)
    if rental["customer_id"] != customer_id:
        raise ApiError(403, "not_your_rental", "This rental belongs to another customer")
    try:
        check_transition(rental["status"], "canceled")
    except ValueError as error:
        raise ApiError(409, "invalid_change", str(error))

    repo = get_repo()
    repo.update_rental(rental_id, {"status": "canceled"})
    repo.commit()
    return jsonify(repo.get_rental(rental_id))