from flask import Blueprint, jsonify

from ..deps import get_repo
from ..domain.transport import TransportQueueManager
from ..domain.vehicle import Location
from ..errors import ApiError
from ..repository import QueueBusy
from .vehicles import _enum_value, _json_object, _text

bp = Blueprint("transport", __name__)


@bp.post("/transport")
def request_transport():
    """Put a vehicle in the queue for a truck or ship to another city."""
    data = _json_object()
    unknown = [key for key in data if key not in ("reg_num", "destination")]
    if unknown:
        raise ApiError(400, "invalid_field", f"Unknown fields: {', '.join(unknown)}")
    reg_num = _text("reg_num", data.get("reg_num"))
    destination = Location(_enum_value(Location, "destination", data.get("destination")))

    repo = get_repo()
    try:
        repo.lock_queue()
    except QueueBusy:
        raise ApiError(503, "queue_busy", "The transport queue is busy, try again in a moment")

    vehicle = repo.get_vehicle(reg_num)
    if vehicle is None:
        raise ApiError(404, "vehicle_not_found", f"No vehicle with reg_num '{reg_num}'")
    if vehicle["status"] != "active":
        raise ApiError(
            409, "vehicle_not_active",
            f"Vehicle '{reg_num}' is {vehicle['status']}; only active vehicles can be transported",
        )
    if repo.is_queued(reg_num):
        raise ApiError(
            409, "already_queued", f"Vehicle '{reg_num}' is already in a transport queue"
        )
    origin = Location(vehicle["location"])
    if origin == destination:
        raise ApiError(
            400, "same_location", f"Vehicle '{reg_num}' is already in {destination.value}"
        )

    TransportQueueManager(repo).request_transport(reg_num, origin, destination)
    repo.commit()

    queued = repo.is_queued(reg_num)
    response = jsonify({
        "reg_num": reg_num,
        "destination": destination.value,
        "location": repo.get_vehicle(reg_num)["location"],
        "status": "queued" if queued else "arrived",
    })
    response.status_code = 202
    return response


@bp.get("/transport/queue")
def transport_queue():
    """The trips that are waiting for enough vehicles to depart."""
    return jsonify({"trips": TransportQueueManager(get_repo()).pending_trips()})