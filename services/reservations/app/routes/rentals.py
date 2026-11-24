from flask import Blueprint, jsonify, request

from ..deps import get_repo
from ..domain.rental import Location, RentalStatus
from ..errors import ApiError
from .customers import DEFAULT_LIMIT, MAX_LIMIT, enum_arg, int_arg

bp = Blueprint("rentals", __name__)


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