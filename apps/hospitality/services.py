"""预约计价：增值服务。副作用只在确认下单时发生。"""

from dataclasses import dataclass, field
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.bookings.models import Order
from apps.pets.models import Owner, Pet
from apps.rooms.models import Room
from apps.rooms.pricing import Quote, quote

from .models import (
    AddonService,
    Billing,
    CareTask,
    OrderAddon,
)

CENT = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(value or 0).quantize(CENT)


@dataclass
class AddonLine:
    service: AddonService
    quantity: int
    nights: int
    unit_price: Decimal
    line_total: Decimal


@dataclass
class StayPrice:
    room_quote: Quote
    lines: list[AddonLine] = field(default_factory=list)
    addon_total: Decimal = Decimal("0.00")
    errors: list[str] = field(default_factory=list)

    @property
    def payable(self) -> Decimal:
        return max(self.room_quote.total + self.addon_total, Decimal("0.00"))


def _lines_for(services, nights: int, pet: Pet | None) -> tuple[list[AddonLine], list[str]]:
    lines: list[AddonLine] = []
    errors: list[str] = []
    for service in services:
        if pet is not None and not service.fits(pet.species):
            errors.append(f"「{service.name}」不适用于{pet.get_species_display()}")
            continue
        billed_nights = nights if service.billing == Billing.NIGHT else 1
        total = (service.price * billed_nights).quantize(CENT)
        lines.append(
            AddonLine(
                service=service,
                quantity=1,
                nights=billed_nights,
                unit_price=service.price,
                line_total=total,
            )
        )
    return lines, errors


def price_booking(
    *,
    room: Room,
    check_in,
    check_out,
    addon_ids,
    owner: Owner | None = None,
    pet: Pet | None = None,
) -> StayPrice:
    room_quote = quote(room, check_in, check_out)
    services = AddonService.objects.filter(pk__in=list(addon_ids or []), is_active=True).order_by("sort", "pk")
    lines, errors = _lines_for(services, room_quote.days, pet)
    addon_total = sum((line.line_total for line in lines), Decimal("0.00"))
    return StayPrice(room_quote=room_quote, lines=lines, addon_total=addon_total, errors=errors)


def preview_reschedule(order: Order, room_quote: Quote) -> StayPrice:
    """改期试算：按新晚数重算按晚计价的增值服务。"""
    lines: list[AddonLine] = []
    for line in order.addons.select_related("service"):
        units = room_quote.days if line.service.billing == Billing.NIGHT else 1
        total = (line.unit_price * line.quantity * units).quantize(CENT)
        lines.append(
            AddonLine(
                service=line.service,
                quantity=line.quantity,
                nights=room_quote.days,
                unit_price=line.unit_price,
                line_total=total,
            )
        )
    addon_total = sum((line.line_total for line in lines), Decimal("0.00"))
    return StayPrice(room_quote=room_quote, lines=lines, addon_total=addon_total)


def retarget_addons(order: Order):
    """入住晚数变化后，重写按晚计价的增值项，并刷新订单上的增值金额。"""
    total = Decimal("0.00")
    for line in order.addons.select_related("service"):
        units = order.days if line.service.billing == Billing.NIGHT else 1
        line.nights = order.days
        line.line_total = (line.unit_price * line.quantity * units).quantize(CENT)
        line.save(update_fields=["nights", "line_total"])
        total += line.line_total
    order.addon_amount = total


@transaction.atomic
def apply_stay(order: Order, stay: StayPrice):
    if stay.errors:
        raise ValidationError(stay.errors)
    order.addon_amount = stay.addon_total
    order.save()
    OrderAddon.objects.filter(order=order).delete()
    OrderAddon.objects.bulk_create(
        [
            OrderAddon(
                order=order,
                service=line.service,
                quantity=line.quantity,
                unit_price=line.unit_price,
                nights=line.nights,
                line_total=line.line_total,
            )
            for line in stay.lines
        ]
    )


def open_care_tasks(order: Order):
    if order.tasks.exists():
        return
    CareTask.objects.create(order=order, title="入住核验：体重与随身物品", due_date=order.check_in)
    for line in order.addons.select_related("service"):
        CareTask.objects.create(
            order=order,
            title=line.service.name,
            due_date=order.check_in,
            note=line.service.summary,
        )
