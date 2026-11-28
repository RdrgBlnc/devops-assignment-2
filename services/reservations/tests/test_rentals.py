"""Tests for app/domain/rental.py: RentalBuilder, RentalStatus and the status rules.

The builder no longer looks anything up: the booking route asks the vehicles service
for the car (over HTTP) and passes its daily rate in. So these tests need no patching,
no database and no network; the vehicle checks are tested with the routes instead.

Run with:
    uv run pytest tests/test_rentals.py -v
"""
from datetime import date, timedelta

import pytest

from app.domain.rental import (
    ALLOWED_TRANSITIONS, MAX_TOTAL_PRICE, Rental, RentalBuilder, RentalStatus, check_transition,
    new_total_price,
)

TODAY = date(2026, 11, 28)  # fixed "today", so the tests give the same result on any day
REG_NUM = "1HGCM82633A004352"
DAILY_RATE = 20.0


def days(n):
    return TODAY + timedelta(days=n)


@pytest.fixture
def valid_builder():
    """A builder filled with valid data: 4 days at 20.0 a day."""
    return (
        RentalBuilder(today=TODAY)
        .with_customer_id(1)
        .with_car_reg_num(REG_NUM)
        .with_start_date(days(1))
        .with_end_date(days(5))
        .with_daily_rate(DAILY_RATE)
    )


# ---------------------------------------------------------------------------
# Required fields
# ---------------------------------------------------------------------------

class TestRequiredFields:
    @pytest.mark.parametrize("missing", [
        "customer_id", "car_reg_num", "start_date", "end_date", "daily_rate",
    ])
    def test_each_missing_field_is_named(self, valid_builder, missing):
        setattr(valid_builder, missing, None)
        with pytest.raises(ValueError, match=f"Missing required fields: .*{missing}"):
            valid_builder.build()

    def test_all_missing_fields_are_listed_together(self):
        with pytest.raises(ValueError, match="customer_id, car_reg_num, start_date"):
            RentalBuilder(today=TODAY).build()


# ---------------------------------------------------------------------------
# Field values
# ---------------------------------------------------------------------------

class TestFieldValues:
    @pytest.mark.parametrize("customer_id", [0, -1, "1", 1.5, True])
    def test_customer_id_must_be_a_positive_whole_number(self, valid_builder, customer_id):
        valid_builder.with_customer_id(customer_id)
        with pytest.raises(ValueError, match="customer_id"):
            valid_builder.build()

    @pytest.mark.parametrize("reg_num", ["", "   ", 123])
    def test_car_reg_num_must_be_text(self, valid_builder, reg_num):
        valid_builder.with_car_reg_num(reg_num)
        with pytest.raises(ValueError, match="car_reg_num"):
            valid_builder.build()

    def test_car_reg_num_is_trimmed(self, valid_builder):
        valid_builder.with_car_reg_num(f"  {REG_NUM} ")
        assert valid_builder.build().car_reg_num == REG_NUM

    @pytest.mark.parametrize("rate", [0, -5, "20", True])
    def test_daily_rate_must_be_a_positive_number(self, valid_builder, rate):
        valid_builder.with_daily_rate(rate)
        with pytest.raises(ValueError, match="daily_rate"):
            valid_builder.build()


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

class TestDateValidation:
    def test_end_date_not_a_date_object_raises(self, valid_builder):
        valid_builder.with_end_date("2026-12-05")  # text, not a date
        with pytest.raises(ValueError, match="date objects"):
            valid_builder.build()

    def test_end_date_equal_to_start_date_raises(self, valid_builder):
        valid_builder.with_start_date(days(1)).with_end_date(days(1))
        with pytest.raises(ValueError, match="end_date must be after start_date"):
            valid_builder.build()

    def test_end_date_before_start_date_raises(self, valid_builder):
        valid_builder.with_start_date(days(5)).with_end_date(days(1))
        with pytest.raises(ValueError, match="end_date must be after start_date"):
            valid_builder.build()

    def test_start_date_in_the_past_raises(self, valid_builder):
        valid_builder.with_start_date(days(-1))
        with pytest.raises(ValueError, match="cannot be in the past"):
            valid_builder.build()

    def test_start_date_today_is_allowed(self, valid_builder):
        valid_builder.with_start_date(TODAY).with_end_date(days(2))
        assert valid_builder.build().start_date == TODAY

    def test_today_defaults_to_the_real_date(self):
        assert RentalBuilder().today == date.today()


# ---------------------------------------------------------------------------
# Successful build: price and defaults
# ---------------------------------------------------------------------------

class TestSuccessfulBuild:
    def test_build_returns_a_rental_with_the_given_fields(self, valid_builder):
        rental = valid_builder.build()
        assert rental == Rental(
            customer_id=1, car_reg_num=REG_NUM, start_date=days(1), end_date=days(5),
            total_price=80.0, status=RentalStatus.pending,
        )

    def test_total_price_is_days_times_daily_rate(self, valid_builder):
        assert valid_builder.build().total_price == 80.0  # 4 days x 20.0

    def test_single_day_rental_price(self, valid_builder):
        valid_builder.with_start_date(days(1)).with_end_date(days(2))
        assert valid_builder.build().total_price == 20.0

    def test_total_price_is_rounded_to_cents(self, valid_builder):
        valid_builder.with_daily_rate(33.333)  # 4 x 33.333 = 133.332
        assert valid_builder.build().total_price == 133.33

    def test_price_too_large_for_the_database_is_refused(self, valid_builder):
        valid_builder.with_daily_rate(MAX_TOTAL_PRICE)
        with pytest.raises(ValueError, match="too large"):
            valid_builder.build()

    def test_default_status_is_pending(self, valid_builder):
        assert valid_builder.build().status == RentalStatus.pending

    def test_explicit_status_is_respected(self, valid_builder):
        valid_builder.with_status("confirmed")
        assert valid_builder.build().status == RentalStatus.confirmed


# ---------------------------------------------------------------------------
# RentalStatus and the allowed status changes
# ---------------------------------------------------------------------------

class TestRentalStatus:
    def test_invalid_status_string_raises(self):
        with pytest.raises(ValueError):
            RentalBuilder().with_status("completed")  # "returned" is the real value

    @pytest.mark.parametrize("value", ["pending", "confirmed", "active", "returned", "canceled"])
    def test_valid_statuses_accepted(self, value):
        assert RentalBuilder().with_status(value).status == RentalStatus(value)

    def test_status_str_returns_plain_value(self):
        assert str(RentalStatus.confirmed) == "confirmed"

    def test_every_status_has_transition_rules(self):
        assert set(ALLOWED_TRANSITIONS) == set(RentalStatus)

    @pytest.mark.parametrize("current, new", [
        ("pending", "confirmed"), ("pending", "canceled"),
        ("confirmed", "active"), ("confirmed", "canceled"),
        ("active", "returned"), ("active", "canceled"),
    ])
    def test_allowed_changes(self, current, new):
        check_transition(current, new)  # no error

    @pytest.mark.parametrize("current, new", [
        ("pending", "active"), ("pending", "returned"), ("pending", "pending"),
        ("confirmed", "pending"), ("active", "confirmed"),
        ("returned", "canceled"), ("canceled", "pending"),
    ])
    def test_refused_changes(self, current, new):
        with pytest.raises(ValueError, match=f"cannot become {new}"):
            check_transition(current, new)

    def test_final_statuses_say_so(self):
        with pytest.raises(ValueError, match="it is final"):
            check_transition("returned", "active")

    def test_unknown_status_raises(self):
        with pytest.raises(ValueError):
            check_transition("pending", "lost")


# ---------------------------------------------------------------------------
# New price when the end date changes
# ---------------------------------------------------------------------------

class TestNewTotalPrice:
    def test_longer_rental_costs_more_at_the_same_rate(self):
        # 3 days for 61.50 is 20.50 a day; 5 days is 102.50
        assert new_total_price(61.5, days(1), days(4), days(6)) == 102.5

    def test_shorter_rental_costs_less(self):
        assert new_total_price(61.5, days(1), days(4), days(2)) == 20.5

    @pytest.mark.parametrize("new_end", [days(1), days(0)])
    def test_new_end_must_be_after_start(self, new_end):
        with pytest.raises(ValueError, match="end_date must be after start_date"):
            new_total_price(61.5, days(1), days(4), new_end)

    def test_too_long_is_refused(self):
        with pytest.raises(ValueError, match="too large"):
            new_total_price(MAX_TOTAL_PRICE, days(1), days(2), days(10))