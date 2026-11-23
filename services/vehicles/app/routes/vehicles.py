from datetime import date

import pymssql
from flask import Blueprint, jsonify, request

from ..deps import get_repo
from ..domain.vehicle import (
    FuelType, Location, RentalTier, TransmissionType, VehicleBuilder, VehicleStatus, VehicleType,
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
MAX_KM = 10_000_000
MAX_SEATS = 100
# Text lengths of the columns in 001_init.sql: a longer value would fail in the database.
MAX_LENGTH = {"reg_num": 32, "plate": 16, "brand": 50, "model": 100, "color": 30}
CREATE_REQUIRED = (
    "reg_num", "type", "brand", "model", "plate", "location", "fuel", "transmission",
    "seat_num", "manufacture_date", "km", "daily_rate", "category",
)
CREATE_OPTIONAL = ("color", "registration_date", "status")


# -- input checking ------------------------------------------------------------------------


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


def _whole_number(field, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ApiError(
            400, "invalid_value", f"{field} must be a whole number from {minimum} to {maximum}"
        )
    return value


def _text(field, value):
    if not isinstance(value, str) or not value.strip():
        raise ApiError(400, "invalid_value", f"{field} must be a non-empty text")
    value = value.strip()
    if len(value) > MAX_LENGTH[field]:
        raise ApiError(
            400, "invalid_value", f"{field} must be at most {MAX_LENGTH[field]} characters"
        )
    return value


def _date(field, value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ApiError(400, "invalid_value", f"{field} must be a date written as YYYY-MM-DD")


def _json_object():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not data:
        raise ApiError(400, "invalid_body", "The body must be a JSON object")
    return data


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


def build_vehicle(data):
    """Check the request body, then let VehicleBuilder apply the business rules.

    Anything wrong raises ApiError(400); nothing reaches the database unchecked.
    """
    unknown = [key for key in data if key not in CREATE_REQUIRED + CREATE_OPTIONAL]
    if unknown:
        raise ApiError(400, "invalid_field", f"Unknown fields: {', '.join(unknown)}")
    missing = [key for key in CREATE_REQUIRED if data.get(key) in (None, "")]
    if missing:
        raise ApiError(400, "missing_fields", f"Missing required fields: {', '.join(missing)}")

    color = data.get("color")
    registration_date = data.get("registration_date")
    try:
        return (
            VehicleBuilder()
            .with_reg_num(_text("reg_num", data["reg_num"]))
            .with_plate(_text("plate", data["plate"]))
            .with_brand(_text("brand", data["brand"]))
            .with_model(_text("model", data["model"]))
            .with_type(_enum_value(VehicleType, "type", data["type"]))
            .with_category(_enum_value(RentalTier, "category", data["category"]))
            .with_location(_enum_value(Location, "location", data["location"]))
            .with_fuel(_enum_value(FuelType, "fuel", data["fuel"]))
            .with_transmission(_enum_value(TransmissionType, "transmission", data["transmission"]))
            .with_status(_enum_value(VehicleStatus, "status", data.get("status", "active")))
            .with_seat_num(_whole_number("seat_num", data["seat_num"], 1, MAX_SEATS))
            .with_km(_whole_number("km", data["km"], 0, MAX_KM))
            .with_daily_rate(_rate(data["daily_rate"]))
            .with_manufacture_date(_date("manufacture_date", data["manufacture_date"]))
            .with_registration_date(
                _date("registration_date", registration_date) if registration_date else date.today()
            )
            .with_color(None if color in (None, "") else _text("color", color))
            .build()
        )
    except ValueError as exc:  # a business rule of the builder, e.g. a mini with 4 seats
        raise ApiError(400, "invalid_vehicle", str(exc))


# -- routes --------------------------------------------------------------------------------


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


@bp.post("/vehicles")
def create_vehicle():
    vehicle = build_vehicle(_json_object())
    repo = get_repo()
    if repo.get_vehicle(vehicle.reg_num) is not None:
        raise ApiError(
            409, "vehicle_exists", f"A vehicle with reg_num '{vehicle.reg_num}' already exists"
        )
    try:
        repo.insert_vehicle(vehicle.to_dict())
    except pymssql.IntegrityError:  # e.g. the plate is already used by another vehicle
        raise ApiError(409, "vehicle_exists", "A vehicle with this reg_num or plate already exists")
    repo.commit()
    response = jsonify(repo.get_vehicle(vehicle.reg_num))
    response.status_code = 201
    return response


@bp.get("/vehicles/<reg_num>")
def get_vehicle(reg_num):
    vehicle = get_repo().get_vehicle(reg_num)
    if vehicle is None:
        raise ApiError(404, "vehicle_not_found", f"No vehicle with reg_num '{reg_num}'")
    return jsonify(vehicle)


@bp.patch("/vehicles/<reg_num>")
def update_vehicle(reg_num):
    data = _json_object()
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