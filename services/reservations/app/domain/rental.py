from dataclasses import dataclass
from datetime import date
from enum import Enum


class StrValueEnum(str, Enum):
    def __str__(self):
        return self.value


class RentalStatus(StrValueEnum):
    pending = 'pending'      # created, not yet confirmed
    confirmed = 'confirmed'  # confirmed, car not yet picked up
    active = 'active'        # car picked up, currently rented
    returned = 'returned'    # car returned, rental complete
    canceled = 'canceled'    # canceled before or during the rental


# From which status a rental may move to which. returned and canceled are final.
ALLOWED_TRANSITIONS = {
    RentalStatus.pending: (RentalStatus.confirmed, RentalStatus.canceled),
    RentalStatus.confirmed: (RentalStatus.active, RentalStatus.canceled),
    RentalStatus.active: (RentalStatus.returned, RentalStatus.canceled),
    RentalStatus.returned: (),
    RentalStatus.canceled: (),
}


def check_transition(current: str, new: str) -> None:
    """Raise ValueError if a rental may not go from status `current` to status `new`."""
    allowed = ALLOWED_TRANSITIONS[RentalStatus(current)]
    if RentalStatus(new) not in allowed:
        options = ", ".join(status.value for status in allowed) or "nothing (it is final)"
        raise ValueError(f"A {current} rental cannot become {new}; it can become: {options}")


def new_total_price(total_price: float, start_date: date, old_end: date, new_end: date) -> float:
    """The price after changing the end date, at the same daily rate as before."""
    if new_end <= start_date:
        raise ValueError("end_date must be after start_date")
    daily_rate = total_price / (old_end - start_date).days
    total = round(daily_rate * (new_end - start_date).days, 2)
    if total > MAX_TOTAL_PRICE:
        raise ValueError("the rental is too long: the total price is too large")
    return total


class Location(StrValueEnum):
    """The cities a customer can be based in (the same seven cities as the vehicles)."""
    madrid = 'madrid'
    barcelona = 'barcelona'
    valencia = 'valencia'
    sevilla = 'sevilla'
    malaga = 'malaga'
    tenerife = 'tenerife'
    mallorca = 'mallorca'


@dataclass
class Rental:
    customer_id: int  # id of a row in the customers table, e.g. 12
    car_reg_num: str  # reg_num of a vehicle in the vehicles service, e.g. "1HCM82633A004352"
    start_date: date  # e.g. date(2026, 11, 1)
    end_date: date  # e.g. date(2026, 11, 5)
    total_price: float  # e.g. 199.95
    status: RentalStatus  # RentalStatus.pending


MAX_TOTAL_PRICE = 99999999.99  # the largest value the DECIMAL(10,2) column can hold


class RentalBuilder:
    """Builds a valid Rental. It knows nothing about the database or the vehicles service:

    the caller looks the vehicle up (over HTTP) and passes its daily rate in, so every
    business rule can be tested without a network or a database.
    """

    def __init__(self, today=None):
        self.today = today or date.today()
        self.customer_id = None
        self.car_reg_num = None
        self.start_date = None
        self.end_date = None
        self.daily_rate = None
        self.status = None

    def with_customer_id(self, customer_id: int):
        self.customer_id = customer_id
        return self

    def with_car_reg_num(self, car_reg_num: str):
        self.car_reg_num = car_reg_num
        return self

    def with_start_date(self, start_date: date):
        self.start_date = start_date
        return self

    def with_end_date(self, end_date: date):
        self.end_date = end_date
        return self

    def with_daily_rate(self, daily_rate: float):
        self.daily_rate = daily_rate
        return self

    def with_status(self, status: str):
        self.status = RentalStatus(status)
        return self

    def build(self) -> Rental:
        required = ["customer_id", "car_reg_num", "start_date", "end_date", "daily_rate"]
        missing = [f for f in required if getattr(self, f) is None]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")

        if isinstance(self.customer_id, bool) or not isinstance(self.customer_id, int) \
                or self.customer_id < 1:
            raise ValueError("customer_id must be a whole number of 1 or more")
        if not isinstance(self.car_reg_num, str) or not self.car_reg_num.strip():
            raise ValueError("car_reg_num must be a non-empty text")
        if not isinstance(self.start_date, date) or not isinstance(self.end_date, date):
            raise ValueError("start_date and end_date must be date objects")
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        if self.start_date < self.today:
            raise ValueError("start_date cannot be in the past")
        rate = self.daily_rate
        if isinstance(rate, bool) or not isinstance(rate, (int, float)) or rate <= 0:
            raise ValueError("daily_rate must be a number greater than 0")

        days = (self.end_date - self.start_date).days
        total_price = round(days * self.daily_rate, 2)
        if total_price > MAX_TOTAL_PRICE:
            raise ValueError("the rental is too long: the total price is too large")

        return Rental(
            customer_id=self.customer_id,
            car_reg_num=self.car_reg_num.strip(),
            start_date=self.start_date,
            end_date=self.end_date,
            total_price=total_price,
            status=self.status or RentalStatus.pending,
        )