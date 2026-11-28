"""Tests for app/domain/transport.py: the trucks and ships (Factory Method), the routes
between cities, and the TransportQueueManager.

The old tests used a FakeVehicle with an update() method that the real Vehicle never had,
so they passed while the real code crashed. These tests use the real Vehicle class, and
moving a vehicle is reported through the on_move callback, as in the service.

Run with:
    uv run pytest tests/test_transport.py -v
"""
from datetime import date

import pytest

from app.domain.transport import (
    Ship, Transport, TransportCreator, TransportQueueManager, Truck, ShipCreator, TruckCreator,
    island_link, island_locations, resolve_route,
)
from app.domain.vehicle import (
    FuelType, Location, RentalTier, TransmissionType, Vehicle, VehicleStatus, VehicleType,
)


def make_vehicle(reg_num, location):
    """A real Vehicle (not a stand-in), parked at `location`."""
    return Vehicle(
        type=list(VehicleType)[0], brand="Toyota", model="Corolla", plate=f"P-{reg_num}",
        location=location, fuel=list(FuelType)[0], transmission=list(TransmissionType)[0],
        seat_num=5, manufacture_date=date(2022, 3, 1), registration_date=date(2022, 6, 15),
        km=18500, daily_rate=39.99, status=VehicleStatus.active, reg_num=reg_num,
        category=list(RentalTier)[0],
    )


def make_vehicles(n, location, prefix="V"):
    return [make_vehicle(f"{prefix}{i}", location) for i in range(n)]


MADRID_TO_BARCELONA = (Location.madrid, Location.barcelona)


def loaded(transport, vehicles):
    for vehicle in vehicles:
        transport.enqueue(vehicle)
    return transport


class InMemoryStore:
    """The part of VehicleRepository the manager uses, kept in memory.

    It keeps only plain values, like the database does, so the manager cannot rely on
    objects surviving between requests.
    """

    def __init__(self, locations):
        self.locations = dict(locations)  # reg_num -> location value
        self.rows = []
        self._next_id = 0

    def add_to_queue(self, reg_num, origin, destination, mode, final_destination):
        self._next_id += 1
        self.rows.append({
            "id": self._next_id, "reg_num": reg_num, "origin": origin,
            "destination": destination, "mode": mode, "final_destination": final_destination,
        })

    def waiting_in_queue(self, origin, destination, mode):
        return [dict(row) for row in self.rows
                if (row["origin"], row["destination"], row["mode"]) == (origin, destination, mode)]

    def remove_from_queue(self, ids):
        self.rows = [row for row in self.rows if row["id"] not in ids]

    def update_location(self, reg_num, location):
        self.locations[reg_num] = location

    def queue_groups(self):
        groups = {}
        for row in self.rows:
            key = (row["origin"], row["destination"], row["mode"])
            groups[key] = groups.get(key, 0) + 1
        return [{"origin": o, "destination": d, "mode": m, "queued": n}
                for (o, d, m), n in groups.items()]


def request(store, reg_num, destination):
    """What the POST /transport route does: a new manager each time, origin from the store."""
    TransportQueueManager(store).request_transport(
        reg_num, Location(store.locations[reg_num]), destination
    )


# ---------------------------------------------------------------------------
# Abstract base classes cannot be instantiated directly
# ---------------------------------------------------------------------------

class TestAbstractness:
    def test_transport_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            Transport(Location.madrid, Location.barcelona)

    def test_transport_creator_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            TransportCreator()


# ---------------------------------------------------------------------------
# Truck / Ship: the concrete products
# ---------------------------------------------------------------------------

class TestTruck:
    def test_mode_and_threshold(self):
        truck = Truck(Location.madrid, Location.barcelona)
        assert truck.mode == "truck"
        assert truck.min_vehicles_to_depart == 4

    def test_not_ready_below_threshold(self):
        truck = loaded(Truck(*MADRID_TO_BARCELONA), make_vehicles(3, Location.madrid))
        assert truck.is_ready_to_depart() is False

    def test_ready_at_threshold(self):
        truck = loaded(Truck(*MADRID_TO_BARCELONA), make_vehicles(4, Location.madrid))
        assert truck.is_ready_to_depart() is True

    def test_depart_raises_if_not_ready(self):
        truck = loaded(Truck(*MADRID_TO_BARCELONA), make_vehicles(2, Location.madrid))
        with pytest.raises(ValueError, match="needs at least 4"):
            truck.depart()

    def test_depart_moves_exactly_threshold_and_leaves_remainder(self):
        truck = loaded(Truck(*MADRID_TO_BARCELONA), make_vehicles(5, Location.madrid))

        batch = truck.depart()

        assert len(batch) == 4
        assert all(v.location == Location.barcelona for v in batch)
        assert len(truck.queue) == 1
        assert truck.queue[0].location == Location.madrid  # 5th vehicle untouched

    def test_depart_reports_each_move(self):
        """Replaces the old update() check: the real Vehicle has no update(); the
        service saves each new location through this callback instead."""
        vehicles = make_vehicles(4, Location.madrid)
        truck = loaded(Truck(Location.madrid, Location.barcelona), vehicles)
        moves = []

        truck.depart(on_move=lambda reg_num, place: moves.append((reg_num, place)))

        assert moves == [(v.reg_num, Location.barcelona) for v in vehicles]

    def test_depart_without_callback_still_moves_vehicles(self):
        vehicles = make_vehicles(4, Location.madrid)
        loaded(Truck(Location.madrid, Location.barcelona), vehicles).depart()
        assert all(v.location == Location.barcelona for v in vehicles)


class TestShip:
    def test_mode_and_threshold(self):
        ship = Ship(Location.malaga, Location.tenerife)
        assert ship.mode == "ship"
        assert ship.min_vehicles_to_depart == 2

    def test_not_ready_with_one_vehicle(self):
        ship = loaded(Ship(Location.malaga, Location.tenerife), make_vehicles(1, Location.malaga))
        assert ship.is_ready_to_depart() is False

    def test_ready_with_two_vehicles(self):
        ship = loaded(Ship(Location.malaga, Location.tenerife), make_vehicles(2, Location.malaga))
        assert ship.is_ready_to_depart() is True


class TestEnqueueValidation:
    def test_enqueue_rejects_vehicle_at_wrong_origin(self):
        truck = Truck(Location.madrid, Location.barcelona)
        with pytest.raises(ValueError, match="not madrid"):
            truck.enqueue(make_vehicle("X1", Location.sevilla))


# ---------------------------------------------------------------------------
# Factory Method: creators
# ---------------------------------------------------------------------------

class TestCreators:
    def test_truck_creator_builds_truck(self):
        transport = TruckCreator().get_transport(Location.madrid, Location.sevilla)
        assert isinstance(transport, Truck)
        assert (transport.origin, transport.destination) == (Location.madrid, Location.sevilla)

    def test_ship_creator_builds_ship(self):
        assert isinstance(ShipCreator().get_transport(Location.malaga, Location.tenerife), Ship)

    def test_factory_method_directly_matches_get_transport(self):
        creator = TruckCreator()
        a = creator.factory_method(Location.madrid, Location.sevilla)
        b = creator.get_transport(Location.madrid, Location.sevilla)
        assert type(a) is type(b)


# ---------------------------------------------------------------------------
# resolve_route
# ---------------------------------------------------------------------------

def legs(trips):
    return [(type(t).__name__, t.origin.value, t.destination.value) for t in trips]


class TestResolveRoute:
    def test_mainland_to_mainland_is_single_truck_trip(self):
        assert legs(resolve_route(Location.barcelona, Location.sevilla)) == [
            ("Truck", "barcelona", "sevilla")]

    def test_direct_ship_link_malaga_tenerife(self):
        assert legs(resolve_route(Location.malaga, Location.tenerife)) == [
            ("Ship", "malaga", "tenerife")]

    def test_direct_ship_link_valencia_mallorca(self):
        assert legs(resolve_route(Location.valencia, Location.mallorca)) == [
            ("Ship", "valencia", "mallorca")]

    def test_island_to_its_link_city_is_one_ship(self):
        assert legs(resolve_route(Location.mallorca, Location.valencia)) == [
            ("Ship", "mallorca", "valencia")]

    def test_mainland_to_island_via_non_link_city_is_two_trips(self):
        assert legs(resolve_route(Location.madrid, Location.tenerife)) == [
            ("Truck", "madrid", "malaga"), ("Ship", "malaga", "tenerife")]

    def test_island_to_mainland_via_non_link_city_is_two_trips(self):
        assert legs(resolve_route(Location.tenerife, Location.barcelona)) == [
            ("Ship", "tenerife", "malaga"), ("Truck", "malaga", "barcelona")]

    def test_island_to_island_is_three_trips(self):
        assert legs(resolve_route(Location.tenerife, Location.mallorca)) == [
            ("Ship", "tenerife", "malaga"), ("Truck", "malaga", "valencia"),
            ("Ship", "valencia", "mallorca")]

    def test_same_origin_and_destination_raises(self):
        with pytest.raises(ValueError, match="must be different"):
            resolve_route(Location.madrid, Location.madrid)

    def test_every_island_link_is_consistent(self):
        """Sanity check on the lookup tables themselves."""
        for island in island_locations:
            assert island in island_link
            assert island_link[island] not in island_locations


# ---------------------------------------------------------------------------
# TransportQueueManager (the queue is kept in the store, i.e. the database)
# ---------------------------------------------------------------------------

class TestTransportQueueManager:
    def test_vehicles_stay_put_below_truck_threshold(self):
        store = InMemoryStore({f"V{i}": "madrid" for i in range(3)})

        for reg_num in list(store.locations):
            request(store, reg_num, Location.barcelona)

        assert set(store.locations.values()) == {"madrid"}
        assert len(store.rows) == 3

    def test_truck_departs_exactly_at_threshold(self):
        store = InMemoryStore({f"V{i}": "madrid" for i in range(4)})

        for reg_num in list(store.locations):
            request(store, reg_num, Location.barcelona)

        assert set(store.locations.values()) == {"barcelona"}
        assert store.rows == []  # the queue is emptied when the truck leaves

    def test_single_vehicle_ship_trip_stalls(self):
        store = InMemoryStore({"S1": "malaga"})
        request(store, "S1", Location.tenerife)
        assert store.locations["S1"] == "malaga"  # a ship needs 2, still waiting

    def test_full_chain_madrid_to_tenerife(self):
        """4 vehicles fully chain: a truck to Malaga, then ships to Tenerife."""
        store = InMemoryStore({f"V{i}": "madrid" for i in range(4)})

        for reg_num in list(store.locations):
            request(store, reg_num, Location.tenerife)

        assert set(store.locations.values()) == {"tenerife"}
        assert store.rows == []

    def test_island_to_island_takes_three_legs(self):
        store = InMemoryStore({"A": "tenerife", "B": "tenerife", "C": "malaga", "D": "malaga"})

        for reg_num in ("A", "B", "C", "D"):
            request(store, reg_num, Location.mallorca)

        assert set(store.locations.values()) == {"mallorca"}
        assert store.rows == []

    def test_queue_survives_between_requests(self):
        """Each request builds a new manager (the container may even restart in between):
        the vehicles still batch together because the queue lives in the store."""
        store = InMemoryStore({f"V{i}": "sevilla" for i in range(4)})

        request(store, "V0", Location.madrid)
        request(store, "V1", Location.madrid)
        assert store.locations["V0"] == "sevilla"  # still waiting after 2

        request(store, "V2", Location.madrid)
        request(store, "V3", Location.madrid)
        assert set(store.locations.values()) == {"madrid"}  # departs on the 4th

    def test_oldest_vehicles_leave_first(self):
        store = InMemoryStore({f"V{i}": "madrid" for i in range(5)})

        for reg_num in ("V0", "V1", "V2", "V3", "V4"):
            request(store, reg_num, Location.barcelona)

        assert store.locations["V4"] == "madrid"
        assert [row["reg_num"] for row in store.rows] == ["V4"]

    def test_pending_trips_reports_partial_queue(self):
        store = InMemoryStore({"V0": "madrid", "V1": "madrid"})
        for reg_num in ("V0", "V1"):
            request(store, reg_num, Location.barcelona)

        assert TransportQueueManager(store).pending_trips() == [
            {"mode": "truck", "origin": "madrid", "destination": "barcelona", "queued": 2,
             "needed": 4},
        ]

    def test_pending_ship_trip_needs_two(self):
        store = InMemoryStore({"S1": "malaga"})
        request(store, "S1", Location.tenerife)
        assert TransportQueueManager(store).pending_trips()[0]["needed"] == 2

    def test_pending_trips_empty_after_departure(self):
        store = InMemoryStore({f"V{i}": "madrid" for i in range(4)})
        for reg_num in list(store.locations):
            request(store, reg_num, Location.barcelona)

        assert TransportQueueManager(store).pending_trips() == []

    def test_origin_is_where_the_vehicle_is(self):
        store = InMemoryStore({"M1": "sevilla"})
        request(store, "M1", Location.madrid)
        assert store.rows[0]["origin"] == "sevilla"
        assert store.rows[0]["final_destination"] == "madrid"

    def test_same_city_is_refused(self):
        store = InMemoryStore({"M1": "madrid"})
        with pytest.raises(ValueError, match="must be different"):
            request(store, "M1", Location.madrid)
        assert store.rows == []