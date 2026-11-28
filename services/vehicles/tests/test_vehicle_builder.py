"""Tests for app/domain/vehicle.py: VehicleBuilder's rules and Vehicle.to_dict().

The builder only builds: it does not save (the repository does), so no database is
needed. POST /vehicles turns every ValueError raised here into a 400 answer.

Run with:
    uv run pytest tests/test_vehicle_builder.py -v
"""
from datetime import date, timedelta

import pytest

from app.domain.vehicle import (
    FuelType, Location, RentalTier, TransmissionType, Vehicle, VehicleBuilder, VehicleStatus,
    VehicleType,
)

MANUFACTURED = date(2022, 3, 1)
REGISTERED = date(2022, 6, 15)


@pytest.fixture
def builder():
    """A builder filled with valid data for a 5-seat car."""
    return (
        VehicleBuilder()
        .with_reg_num("1HGCM82633A004352")
        .with_type("car")
        .with_brand("Toyota")
        .with_model("Corolla")
        .with_plate("3242 NRS")
        .with_location("madrid")
        .with_fuel("hybrid")
        .with_transmission("automatic")
        .with_seat_num(5)
        .with_manufacture_date(MANUFACTURED)
        .with_registration_date(REGISTERED)
        .with_km(18500)
        .with_daily_rate(39.99)
        .with_status("active")
        .with_category("economy")
        .with_color("Silver")
    )


class TestSuccessfulBuild:
    def test_builds_a_vehicle_with_typed_fields(self, builder):
        vehicle = builder.build()

        assert isinstance(vehicle, Vehicle)
        assert vehicle.type is VehicleType.car
        assert vehicle.location is Location.madrid
        assert vehicle.fuel is FuelType.hybrid
        assert vehicle.transmission is TransmissionType.automatic
        assert vehicle.status is VehicleStatus.active
        assert vehicle.category is RentalTier.economy
        assert (vehicle.reg_num, vehicle.seat_num, vehicle.km) == ("1HGCM82633A004352", 5, 18500)

    def test_build_does_not_save_anything(self, builder):
        """The old builder saved to the database inside build(); now it only builds."""
        assert not hasattr(Vehicle, "save") and not hasattr(Vehicle, "update")
        builder.build()

    def test_colour_is_optional(self, builder):
        builder.with_color(None)
        assert builder.build().color is None

    def test_whole_number_rate_is_accepted(self, builder):
        builder.with_daily_rate(40)
        assert builder.build().daily_rate == 40

    def test_to_dict_gives_plain_values(self, builder):
        assert builder.build().to_dict() == {
            "type": "car", "brand": "Toyota", "model": "Corolla", "plate": "3242 NRS",
            "location": "madrid", "fuel": "hybrid", "transmission": "automatic",
            "seat_num": 5, "manufacture_date": "2022-03-01", "registration_date": "2022-06-15",
            "km": 18500, "daily_rate": 39.99, "status": "active",
            "reg_num": "1HGCM82633A004352", "category": "economy", "color": "Silver",
        }

    def test_enum_str_is_the_plain_value(self):
        assert str(Location.madrid) == "madrid" and str(VehicleType.van) == "van"


class TestRequiredFields:
    @pytest.mark.parametrize("field", [
        "type", "brand", "model", "plate", "location", "fuel", "transmission", "seat_num",
        "manufacture_date", "registration_date", "km", "daily_rate", "status", "reg_num",
        "category",
    ])
    def test_each_missing_field_is_named(self, builder, field):
        setattr(builder, field, None)
        with pytest.raises(ValueError, match=f"Missing required fields: .*{field}"):
            builder.build()

    def test_empty_builder_lists_every_missing_field(self):
        with pytest.raises(ValueError, match="type, brand, model, plate"):
            VehicleBuilder().build()


class TestListValues:
    @pytest.mark.parametrize("method, value", [
        ("with_type", "truck"), ("with_location", "paris"), ("with_fuel", "coal"),
        ("with_transmission", "cvt"), ("with_status", "sold"), ("with_category", "premium"),
    ])
    def test_unknown_values_are_refused_straight_away(self, method, value):
        with pytest.raises(ValueError):
            getattr(VehicleBuilder(), method)(value)


class TestSeats:
    @pytest.mark.parametrize("seats", [4, 5])
    def test_car_with_4_or_5_seats(self, builder, seats):
        assert builder.with_seat_num(seats).build().seat_num == seats

    @pytest.mark.parametrize("seats", [2, 3, 6, 7])
    def test_car_with_other_seat_counts_is_refused(self, builder, seats):
        with pytest.raises(ValueError, match="'car' must have 4 or 5 seats"):
            builder.with_seat_num(seats).build()

    def test_mini_needs_exactly_2_seats(self, builder):
        builder.with_type("mini")
        assert builder.with_seat_num(2).build().seat_num == 2
        with pytest.raises(ValueError, match="'mini' must have exactly 2 seats"):
            builder.with_seat_num(4).build()

    @pytest.mark.parametrize("vehicle_type, seats", [("van", 9), ("suv", 7), ("van", 2)])
    def test_vans_and_suvs_have_no_seat_rule(self, builder, vehicle_type, seats):
        assert builder.with_type(vehicle_type).with_seat_num(seats).build().seat_num == seats

    @pytest.mark.parametrize("seats", [0, -1, 4.5, "5", True])
    def test_seats_must_be_a_positive_whole_number(self, builder, seats):
        builder.with_type("van").with_seat_num(seats)
        with pytest.raises(ValueError, match="seat_num must be a positive integer"):
            builder.build()


class TestDates:
    def test_manufacture_date_must_be_a_date(self, builder):
        builder.with_manufacture_date("2022-03-01")
        with pytest.raises(ValueError, match="manufacture_date must be a date"):
            builder.build()

    def test_manufacture_date_cannot_be_in_the_future(self, builder):
        tomorrow = date.today() + timedelta(days=1)
        builder.with_manufacture_date(tomorrow).with_registration_date(tomorrow)
        with pytest.raises(ValueError, match="cannot be in the future"):
            builder.build()

    def test_registration_date_must_be_a_date(self, builder):
        builder.with_registration_date("2022-06-15")
        with pytest.raises(ValueError, match="registration_date must be a date"):
            builder.build()

    def test_registration_before_manufacture_is_refused(self, builder):
        builder.with_registration_date(MANUFACTURED - timedelta(days=1))
        with pytest.raises(ValueError, match="cannot be before manufacture_date"):
            builder.build()

    def test_registration_on_the_manufacture_day_is_allowed(self, builder):
        vehicle = builder.with_registration_date(MANUFACTURED).build()
        assert vehicle.registration_date == MANUFACTURED

    def test_registration_up_to_five_years_later_is_allowed(self, builder):
        builder.with_registration_date(MANUFACTURED + timedelta(days=5 * 365))
        builder.build()

    def test_registration_more_than_five_years_later_is_refused(self, builder):
        builder.with_registration_date(MANUFACTURED + timedelta(days=5 * 365 + 1))
        with pytest.raises(ValueError, match="cannot exceed 5 years"):
            builder.build()


class TestNumbersAndText:
    def test_zero_km_is_allowed(self, builder):
        assert builder.with_km(0).build().km == 0

    @pytest.mark.parametrize("km", [-1, 10.5, "100", True])
    def test_km_must_be_a_non_negative_whole_number(self, builder, km):
        with pytest.raises(ValueError, match="km must be a non-negative integer"):
            builder.with_km(km).build()

    @pytest.mark.parametrize("rate", [0, -10, "39.99", True])
    def test_daily_rate_must_be_a_positive_number(self, builder, rate):
        with pytest.raises(ValueError, match="daily_rate must be a positive number"):
            builder.with_daily_rate(rate).build()

    @pytest.mark.parametrize("reg_num", ["", 12345])
    def test_reg_num_must_be_non_empty_text(self, builder, reg_num):
        with pytest.raises(ValueError, match="reg_num must be a non-empty string"):
            builder.with_reg_num(reg_num).build()

    @pytest.mark.parametrize("plate", ["", 1234])
    def test_plate_must_be_non_empty_text(self, builder, plate):
        with pytest.raises(ValueError, match="plate must be a non-empty string"):
            builder.with_plate(plate).build()