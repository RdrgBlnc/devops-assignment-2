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