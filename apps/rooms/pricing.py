from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings

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
    """逐晚计价：按房间日价计费，满足连住天数再整体打折。"""
    result = Quote()
    day = check_in
    while day < check_out:
        result.nights.append(NightPrice(day, room.price.quantize(CENT, ROUND_HALF_UP)))
        day += timedelta(days=1)

    result.subtotal = sum((n.price for n in result.nights), Decimal("0.00"))
    min_days, rate = settings.LONG_STAY_DAYS, Decimal(str(settings.LONG_STAY_RATE))
    if result.days >= min_days and rate < 1:
        result.discount = (result.subtotal * (1 - rate)).quantize(CENT, ROUND_HALF_UP)
        result.discount_label = f"连住 {min_days} 晚及以上 {float(rate) * 10:g} 折"
    result.total = result.subtotal - result.discount
    return result
