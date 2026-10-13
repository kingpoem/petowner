from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from .models import Room

CENT = Decimal("0.01")


@dataclass
class NightPrice:
    day: date
    price: Decimal
    rule: str = ""


@dataclass
class Quote:
    nights: list[NightPrice] = field(default_factory=list)
    subtotal: Decimal = Decimal("0.00")
    discount: Decimal = Decimal("0.00")
    total: Decimal = Decimal("0.00")
    discount_label: str = ""

    @property
    def days(self) -> int:
        return len(self.nights)

    @property
    def surcharged_nights(self) -> list[NightPrice]:
        return [n for n in self.nights if n.rule]


def quote(room: Room, check_in: date, check_out: date) -> Quote:
    """按房间日价 × 晚数计价。"""
    result = Quote()
    day = check_in
    while day < check_out:
        result.nights.append(NightPrice(day, room.price.quantize(CENT, ROUND_HALF_UP)))
        day += timedelta(days=1)
    result.subtotal = sum((n.price for n in result.nights), Decimal("0.00"))
    result.total = result.subtotal
    return result
