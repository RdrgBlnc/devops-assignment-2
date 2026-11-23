from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from typing import List

from .vehicle import Location, Vehicle


# Which locations are islands, and which single mainland city each one
# links to by ship.
island_locations = {Location.tenerife, Location.mallorca}
island_link = {
    Location.tenerife: Location.malaga,
    Location.mallorca: Location.valencia,
}


class Transport(ABC):
    def __init__(self, origin: Location, destination: Location):
        self.origin = origin
        self.destination = destination
        self.queue: deque = deque()

    @property
    @abstractmethod
    def mode(self) -> str:
        # 'truck' or 'ship'
        ...

    @property
    @abstractmethod
    def min_vehicles_to_depart(self) -> int:
        ...

    def enqueue(self, vehicle: Vehicle) -> None:
        if vehicle.location != self.origin:
            raise ValueError(
                f'Vehicle {vehicle.reg_num} is at {vehicle.location}, '
                f'not {self.origin} - cannot queue it for this trip'
            )
        self.queue.append(vehicle)

    def is_ready_to_depart(self) -> bool:
        return len(self.queue) >= self.min_vehicles_to_depart

    def depart(self, on_move=None) -> List[Vehicle]:
        # on_move(reg_num, destination) is called once per vehicle that leaves, so the
        # caller can save the new location. The vehicle itself knows nothing about the
        # database: Vehicle is a plain dataclass with no update() method.
        if not self.is_ready_to_depart():
            raise ValueError(
                f'{self.mode} needs at least {self.min_vehicles_to_depart} '
                f'vehicles to depart ({len(self.queue)} queued)'
            )

        batch = [self.queue.popleft() for _ in range(self.min_vehicles_to_depart)]
        for vehicle in batch:
            vehicle.location = self.destination
            if on_move is not None:
                on_move(vehicle.reg_num, self.destination)

        return batch


class Truck(Transport):
    @property
    def mode(self) -> str:
        return 'truck'

    @property
    def min_vehicles_to_depart(self) -> int:
        return 4


class Ship(Transport):
    @property
    def mode(self) -> str:
        return 'ship'

    @property
    def min_vehicles_to_depart(self) -> int:
        return 2


class TransportCreator(ABC):
    @abstractmethod
    def factory_method(self, origin: Location, destination: Location) -> Transport:
        ...

    def get_transport(self, origin: Location, destination: Location) -> Transport:
        return self.factory_method(origin, destination)


class TruckCreator(TransportCreator):
    def factory_method(self, origin: Location, destination: Location) -> Transport:
        return Truck(origin, destination)


class ShipCreator(TransportCreator):
    def factory_method(self, origin: Location, destination: Location) -> Transport:
        return Ship(origin, destination)


_truck_creator = TruckCreator()
_ship_creator = ShipCreator()


def resolve_route(origin: Location, destination: Location) -> List[Transport]:
    if origin == destination:
        raise ValueError('origin and destination must be different')

    origin_is_island = origin in island_locations
    dest_is_island = destination in island_locations

    # island -> island: ship to origin's link city, truck between the two
    # link cities (unless they're the same city), ship to the destination
    if origin_is_island and dest_is_island:
        origin_link = island_link[origin]
        dest_link = island_link[destination]
        trips = [_ship_creator.get_transport(origin, origin_link)]
        if origin_link != dest_link:
            trips.append(_truck_creator.get_transport(origin_link, dest_link))
        trips.append(_ship_creator.get_transport(dest_link, destination))
        return trips

    # mainland -> island
    if dest_is_island:
        link_city = island_link[destination]
        if origin == link_city:
            return [_ship_creator.get_transport(origin, destination)]
        return [
            _truck_creator.get_transport(origin, link_city),
            _ship_creator.get_transport(link_city, destination),
        ]

    # island -> mainland
    if origin_is_island:
        link_city = island_link[origin]
        if destination == link_city:
            return [_ship_creator.get_transport(origin, destination)]
        return [
            _ship_creator.get_transport(origin, link_city),
            _truck_creator.get_transport(link_city, destination),
        ]

    # mainland -> mainland
    return [_truck_creator.get_transport(origin, destination)]


@dataclass
class QueuedVehicle:
    """What the queue needs to know about a waiting vehicle, and no more."""
    reg_num: str
    location: Location
    final_destination: Location


_CREATORS = {"truck": _truck_creator, "ship": _ship_creator}


class TransportQueueManager:
    """Batches vehicles into trucks and ships, keeping the queues in a store.

    The store is the database (VehicleRepository): the queue survives the container
    scaling to zero, and a vehicle waiting at a stop is a row, not a Python object.
    A trip is rebuilt from the stored rows each time, so no state lives in memory.
    The store must offer add_to_queue, waiting_in_queue, remove_from_queue,
    queue_groups and update_location.
    """

    def __init__(self, store):
        self.store = store

    def request_transport(
        self, reg_num: str, location: Location, final_destination: Location
    ) -> None:
        self._enqueue(reg_num, location, final_destination)

    def _enqueue(self, reg_num, location, final_destination):
        # the next leg is always the first leg of the route from where the vehicle is now
        trip = resolve_route(location, final_destination)[0]
        self.store.add_to_queue(
            reg_num, trip.origin.value, trip.destination.value, trip.mode, final_destination.value
        )
        self._depart_if_ready(trip)

    def _depart_if_ready(self, trip):
        rows = self.store.waiting_in_queue(trip.origin.value, trip.destination.value, trip.mode)
        for row in rows:
            trip.enqueue(
                QueuedVehicle(row["reg_num"], trip.origin, Location(row["final_destination"]))
            )
        if not trip.is_ready_to_depart():
            return

        def on_move(reg_num, place):
            self.store.update_location(reg_num, place.value)

        batch = trip.depart(on_move=on_move)
        self.store.remove_from_queue([row["id"] for row in rows[:len(batch)]])
        for vehicle in batch:
            if vehicle.location != vehicle.final_destination:  # the journey has another leg
                self._enqueue(vehicle.reg_num, vehicle.location, vehicle.final_destination)

    def pending_trips(self) -> List[dict]:
        return [
            {
                "mode": group["mode"],
                "origin": group["origin"],
                "destination": group["destination"],
                "queued": group["queued"],
                "needed": _CREATORS[group["mode"]].get_transport(
                    Location(group["origin"]), Location(group["destination"])
                ).min_vehicles_to_depart,
            }
            for group in self.store.queue_groups()
        ]