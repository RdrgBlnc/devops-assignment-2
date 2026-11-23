from flask import Blueprint, jsonify, request

from ..deps import get_repo
from ..domain.vehicle import (
    FuelType, Location, RentalTier, TransmissionType, VehicleStatus, VehicleType,
)
from ..errors import ApiError
from ..repository import SORTS, UPDATABLE

bp = Blueprint("vehicles", __name__)

COLORS = ["Black", "White", "Silver", "Grey", "Blue", "Red", "Green"]
FILTER_ENUMS = {
    "status": VehicleStatus,
    "location": Location,
    "type": VehicleType,
    "category": RentalTier,
    "fuel": FuelType,
}
DEFAULT_LIMIT = 100
MAX_LIMIT = 500
MAX_RATE = 99999999.99  # the largest value the DECIMAL(10,2) column can hold


def _values(enum):
    return [member.value for member in enum]


def _enum_value(enum, field, value):
    try:
        return enum(value).value
    except ValueError:
        raise ApiError(400, "invalid_value", f"{field} must be one of: {', '.join(_values(enum))}")


def _rate(value):
    is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
    if not is_number or not 0 < value <= MAX_RATE:
        raise ApiError(400, "invalid_value", "daily_rate must be a number greater than 0")
    return round(value, 2)


def _int_arg(name, default, minimum, maximum):
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


@bp.get("/meta")
def meta():
    """The allowed values of every list field, so the UI can build its dropdowns."""
    return jsonify({
        "locations": _values(Location),
        "types": _values(VehicleType),
        "statuses": _values(VehicleStatus),
        "categories": _values(RentalTier),
        "fuels": _values(FuelType),
        "transmissions": _values(TransmissionType),
        "colors": COLORS,
        "sort_options": list(SORTS),
    })


@bp.get("/stats")
def stats():
    return jsonify(get_repo().stats())


@bp.get("/vehicles")
def list_vehicles():
    filters = {}
    for name, enum in FILTER_ENUMS.items():
        value = request.args.get(name, "")
        if value:
            filters[name] = _enum_value(enum, name, value)
    if request.args.get("color"):
        filters["color"] = request.args["color"]

    sort_by = request.args.get("sort_by", "")
    if sort_by and sort_by not in SORTS:
        raise ApiError(400, "invalid_query", f"sort_by must be one of: {', '.join(SORTS)}")

    limit = _int_arg("limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
    offset = _int_arg("offset", 0, 0, 10_000_000)

    repo = get_repo()
    return jsonify({
        "items": repo.list_vehicles(filters, sort_by or None, limit, offset),
        "total": repo.count_vehicles(filters),
        "limit": limit,
        "offset": offset,
    })


@bp.get("/vehicles/<reg_num>")
def get_vehicle(reg_num):
    vehicle = get_repo().get_vehicle(reg_num)
    if vehicle is None:
        raise ApiError(404, "vehicle_not_found", f"No vehicle with reg_num '{reg_num}'")
    return jsonify(vehicle)


@bp.patch("/vehicles/<reg_num>")
def update_vehicle(reg_num):
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not data:
        raise ApiError(400, "invalid_body", "The body must be a JSON object with fields to change")
    unknown = [key for key in data if key not in UPDATABLE]
    if unknown:
        raise ApiError(
            400, "invalid_field",
            f"Cannot update {', '.join(unknown)}; only {', '.join(UPDATABLE)} can be changed",
        )

    fields = {}
    if "category" in data:
        fields["category"] = _enum_value(RentalTier, "category", data["category"])
    if "status" in data:
        fields["status"] = _enum_value(VehicleStatus, "status", data["status"])
    if "daily_rate" in data:
        fields["daily_rate"] = _rate(data["daily_rate"])

    repo = get_repo()
    if repo.update_vehicle(reg_num, fields) == 0:
        raise ApiError(404, "vehicle_not_found", f"No vehicle with reg_num '{reg_num}'")
    repo.commit()
    return jsonify(repo.get_vehicle(reg_num))