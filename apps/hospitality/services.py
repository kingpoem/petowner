"""预约计价：增值服务、优惠券、会员折扣与积分。副作用只在确认下单时发生。"""

from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.bookings.models import Order
from apps.pets.models import Owner, Pet
from apps.rooms.models import Room
from apps.rooms.pricing import Quote, quote

from .models import (
    AddonService,
    Billing,
    CareTask,
    Coupon,
    MemberAccount,
    OrderAddon,
    PointLedger,
    ensure_member,
)

CENT = Decimal("0.01")
POINTS_PER_YUAN = Decimal("100")


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
    coupon_code: str = ""
    coupon_label: str = ""
    coupon_discount: Decimal = Decimal("0.00")
    member_label: str = ""
    member_discount: Decimal = Decimal("0.00")
    points_redeemed: int = 0
    points_discount: Decimal = Decimal("0.00")
    errors: list[str] = field(default_factory=list)

    @property
    def payable(self) -> Decimal:
        total = self.room_quote.total + self.addon_total
        off = self.coupon_discount + self.member_discount + self.points_discount
        return max(total - off, Decimal("0.00"))


def _lines_for(services, nights: int, pet: Pet | None) -> tuple[list[AddonLine], list[str]]:
    lines: list[AddonLine] = []
    errors: list[str] = []
    for service in services:
        if pet is not None and not service.fits(pet.species):
            errors.append(f"「{service.name}」不适用于{pet.get_species_display()}")
            continue
        units = nights if service.billing == Billing.NIGHT else 1
        total = (service.price * units).quantize(CENT)
        lines.append(AddonLine(service=service, quantity=1, nights=nights, unit_price=service.price, line_total=total))
    return lines, errors


def price_booking(
    *,
    room: Room,
    check_in,
    check_out,
    addon_ids,
    coupon_code: str = "",
    redeem_points: int = 0,
    use_member: bool = False,
    owner: Owner | None = None,
    pet: Pet | None = None,
) -> StayPrice:
    room_quote = quote(room, check_in, check_out)
    services = AddonService.objects.filter(pk__in=list(addon_ids or []), is_active=True).order_by("sort", "pk")
    lines, errors = _lines_for(services, room_quote.days, pet)
    addon_total = sum((line.line_total for line in lines), Decimal("0.00"))
    gross = room_quote.total + addon_total
    stay = StayPrice(room_quote=room_quote, lines=lines, addon_total=addon_total, errors=errors)

    code = (coupon_code or "").strip()
    if code:
        coupon = Coupon.objects.filter(code__iexact=code).first()
        if coupon is None:
            stay.errors.append("优惠码不存在")
        else:
            reason = coupon.usable_on(timezone.localdate(), gross)
            if reason:
                stay.errors.append(reason)
            else:
                stay.coupon_code = coupon.code
                stay.coupon_label = coupon.name
                stay.coupon_discount = min(coupon.discount_for(gross), gross)

    remaining = gross - stay.coupon_discount
    if use_member and owner is not None:
        account = ensure_member(owner)
        if account.rate < 1:
            raw = (room_quote.total * (Decimal("1") - account.rate)).quantize(CENT)
            stay.member_discount = min(raw, remaining)
            stay.member_label = f"{account.tier_name}会员"
            remaining -= stay.member_discount

    points = int(redeem_points or 0)
    if points < 0:
        stay.errors.append("抵扣积分不能为负数")
    elif points and owner is not None:
        account = ensure_member(owner)
        if points > account.points:
            stay.errors.append(f"可用积分只有 {account.points}")
        else:
            requested = (Decimal(points) / POINTS_PER_YUAN).quantize(CENT, rounding=ROUND_DOWN)
            stay.points_discount = min(requested, remaining)
            stay.points_redeemed = int(stay.points_discount * POINTS_PER_YUAN)
            if stay.points_redeemed <= 0:
                stay.errors.append("积分不足 1 元，暂不能抵扣")
    elif points and owner is None:
        stay.errors.append("请先登录后再使用积分")
    return stay


def preview_reschedule(order: Order, room_quote: Quote) -> StayPrice:
    """改期试算：沿用已锁定的优惠，按新晚数重算按晚计价的增值服务。"""
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
    return StayPrice(
        room_quote=room_quote,
        lines=lines,
        addon_total=addon_total,
        coupon_code=order.coupon_code,
        coupon_label=order.coupon_code,
        coupon_discount=money(order.coupon_discount),
        member_label="会员折扣" if money(order.member_discount) else "",
        member_discount=money(order.member_discount),
        points_redeemed=order.points_redeemed or 0,
        points_discount=money(order.points_discount),
    )


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
    order.coupon_code = stay.coupon_code
    order.coupon_discount = stay.coupon_discount
    order.member_discount = stay.member_discount
    order.points_redeemed = stay.points_redeemed
    order.points_discount = stay.points_discount
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
    if stay.coupon_code:
        coupon = Coupon.objects.select_for_update().get(code=stay.coupon_code)
        reason = coupon.usable_on(timezone.localdate(), stay.room_quote.total + stay.addon_total)
        if reason:
            raise ValidationError(reason)
        coupon.used_count += 1
        coupon.save(update_fields=["used_count"])
    if stay.points_redeemed:
        account = MemberAccount.objects.select_for_update().get(owner=order.pet.owner)
        if account.points < stay.points_redeemed:
            raise ValidationError("积分不足")
        PointLedger.objects.create(account=account, order=order, delta=-stay.points_redeemed, reason="redeem")
        account.points -= stay.points_redeemed
        account.save(update_fields=["points"])


def release_commerce(order: Order):
    """取消订单时退回积分，并归还优惠码次数。"""
    if order.points_redeemed:
        account = MemberAccount.objects.filter(owner=order.owner).first()
        if account is not None:
            _entry, created = PointLedger.objects.get_or_create(
                account=account,
                order=order,
                reason="redeem_refund",
                defaults={"delta": order.points_redeemed},
            )
            if created:
                account.points += order.points_redeemed
                account.save(update_fields=["points"])
    if order.coupon_code:
        coupon = Coupon.objects.filter(code=order.coupon_code).first()
        if coupon and coupon.used_count:
            coupon.used_count -= 1
            coupon.save(update_fields=["used_count"])


def award_stay_points(order: Order):
    yuan = int(money(order.amount))
    if yuan <= 0:
        return
    account = ensure_member(order.owner)
    _entry, created = PointLedger.objects.get_or_create(
        account=account, order=order, reason="stay", defaults={"delta": yuan}
    )
    if created:
        account.points += yuan
        account.lifetime_points += yuan
        account.save(update_fields=["points", "lifetime_points"])


def open_care_tasks(order: Order):
    if order.tasks.exists():
        return
    CareTask.objects.create(order=order, title="入住核验：疫苗、体重与随身物品", due_date=order.check_in)
    for line in order.addons.select_related("service"):
        CareTask.objects.create(
            order=order,
            title=line.service.name,
            due_date=order.check_in,
            note=line.service.summary,
        )
    meds = order.pet.medications.filter(is_active=True)
    for med in meds:
        CareTask.objects.create(
            order=order,
            title=f"用药：{med.drug} {med.dosage}",
            due_date=order.check_in,
            note=med.frequency,
        )
