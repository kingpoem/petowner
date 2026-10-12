"""积分发放、抵扣与优惠券核销。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Q, Sum
from django.utils import timezone

from apps.bookings.models import Payment
from apps.pets.models import Owner

from .models import Coupon, CouponRedemption, PointLedger

TIERS = (
    ("bronze", "青铜会员", 0, Decimal("0")),
    ("silver", "白银会员", 500, Decimal("500")),
    ("gold", "黄金会员", 2000, Decimal("2000")),
    ("diamond", "钻石会员", 5000, Decimal("5000")),
)


@dataclass
class MembershipTier:
    key: str
    name: str
    threshold: Decimal
    spent: Decimal
    next_name: str = ""
    next_need: Decimal = Decimal("0")
    progress: float = 100.0


def _rate_earn() -> int:
    return max(0, settings.LOYALTY_POINTS_PER_YUAN)


def _rate_redeem() -> int:
    return max(1, settings.LOYALTY_POINTS_PER_YUAN_REDEEM)


def lifetime_spent(owner: Owner) -> Decimal:
    paid = (
        Payment.objects.filter(
            order__pet__owner=owner, kind=Payment.Kind.PAY, status=Payment.Status.SUCCESS
        ).aggregate(t=Sum("amount"))["t"]
        or Decimal("0")
    )
    refunded = (
        Payment.objects.filter(
            order__pet__owner=owner, kind=Payment.Kind.REFUND, status=Payment.Status.SUCCESS
        ).aggregate(t=Sum("amount"))["t"]
        or Decimal("0")
    )
    return max(paid - refunded, Decimal("0"))


def membership_tier(owner: Owner) -> MembershipTier:
    spent = lifetime_spent(owner)
    current = TIERS[0]
    nxt = None
    for i, tier in enumerate(TIERS):
        if spent >= tier[3]:
            current = tier
            nxt = TIERS[i + 1] if i + 1 < len(TIERS) else None
    if nxt:
        span = nxt[3] - current[3]
        progress = float((spent - current[3]) * 100 / span) if span else 100.0
        return MembershipTier(
            key=current[0],
            name=current[1],
            threshold=current[3],
            spent=spent,
            next_name=nxt[1],
            next_need=max(nxt[3] - spent, Decimal("0")),
            progress=min(max(progress, 0.0), 100.0),
        )
    return MembershipTier(key=current[0], name=current[1], threshold=current[3], spent=spent)


def available_coupons(owner: Owner, store=None):
    """顾客可见的有效优惠券（未超每人限次）。"""
    today = timezone.localdate()
    qs = Coupon.objects.filter(is_active=True, valid_from__lte=today, valid_until__gte=today)
    if store is not None:
        qs = qs.filter(Q(store__isnull=True) | Q(store=store))
    result = []
    for coupon in qs.order_by("valid_until", "code"):
        if coupon.max_uses and coupon.used_count >= coupon.max_uses:
            continue
        used = coupon.redemptions.filter(owner=owner).count()
        if coupon.max_per_owner and used >= coupon.max_per_owner:
            continue
        result.append(coupon)
    return result


def preview_loyalty_discount(owner: Owner, base: Decimal, *, coupon_code: str = "", redeem_points: int = 0, store=None):
    """试算优惠码与积分抵扣，供报价预览（不落库）。"""
    coupon_discount = Decimal("0.00")
    coupon_error = ""
    points_discount = Decimal("0.00")
    points_error = ""
    code = (coupon_code or "").strip()
    if code:
        try:
            _, coupon_discount = lookup_coupon(code, owner, base, store=store)
        except ValidationError as exc:
            coupon_error = exc.messages[0] if getattr(exc, "messages", None) else str(exc)
    points = max(0, int(redeem_points or 0))
    rate = _rate_redeem()
    if points:
        if points % rate:
            points_error = f"积分须为 {rate} 的整数倍"
        elif points > owner.points:
            points_error = f"积分不足，当前可用 {owner.points}"
        else:
            points_discount = Decimal(points // rate).quantize(Decimal("0.01"))
            if coupon_discount + points_discount > base:
                points_error = "优惠合计不能超过订单金额"
                points_discount = Decimal("0.00")
    extra = coupon_discount + points_discount
    return {
        "coupon_discount": coupon_discount,
        "points_discount": points_discount,
        "extra_discount": extra,
        "payable": max(base - extra, Decimal("0.00")),
        "coupon_error": coupon_error,
        "points_error": points_error,
    }


@transaction.atomic
def award_points(owner: Owner, amount: Decimal, order=None, note: str = "") -> PointLedger | None:
    points = int(amount) * _rate_earn()
    if points <= 0 or owner is None:
        return None
    if order is not None and PointLedger.objects.filter(order=order, kind=PointLedger.Kind.EARN).exists():
        return None
    owner = Owner.objects.select_for_update().get(pk=owner.pk)
    owner.points = F("points") + points
    owner.save(update_fields=["points"])
    owner.refresh_from_db(fields=["points"])
    return PointLedger.objects.create(
        owner=owner,
        kind=PointLedger.Kind.EARN,
        points=points,
        balance=owner.points,
        note=note or f"消费积分 +{points}",
        order=order,
    )


@transaction.atomic
def redeem_points(owner: Owner, points: int, order=None) -> tuple[Decimal, PointLedger | None]:
    """用积分抵现，返回（抵扣金额, 流水）。"""
    points = max(0, int(points or 0))
    if points <= 0:
        return Decimal("0.00"), None
    if points % _rate_redeem():
        raise ValidationError(f"积分须为 {_rate_redeem()} 的整数倍")
    owner = Owner.objects.select_for_update().get(pk=owner.pk)
    if owner.points < points:
        raise ValidationError(f"积分不足，当前可用 {owner.points}")
    money = Decimal(points // _rate_redeem()).quantize(Decimal("0.01"))
    owner.points -= points
    owner.save(update_fields=["points"])
    ledger = PointLedger.objects.create(
        owner=owner,
        kind=PointLedger.Kind.REDEEM,
        points=-points,
        balance=owner.points,
        note=f"积分抵扣 ¥{money}",
        order=order,
    )
    return money, ledger


def lookup_coupon(code: str, owner: Owner, amount: Decimal, store=None) -> tuple[Coupon, Decimal]:
    try:
        coupon = Coupon.objects.get(code__iexact=(code or "").strip())
    except Coupon.DoesNotExist as exc:
        raise ValidationError("优惠码无效") from exc
    if not coupon.is_valid_now():
        raise ValidationError("优惠码已失效或已用完")
    if coupon.store_id and store and coupon.store_id != getattr(store, "pk", store):
        raise ValidationError("该优惠码不适用于当前门店")
    used = coupon.redemptions.filter(owner=owner).count()
    if coupon.max_per_owner and used >= coupon.max_per_owner:
        raise ValidationError("您已使用过该优惠码")
    discount = coupon.discount_for(amount)
    if discount <= 0:
        raise ValidationError(f"订单未满 ¥{coupon.min_amount}，无法使用该优惠码")
    return coupon, discount


@transaction.atomic
def apply_coupon(coupon: Coupon, owner: Owner, order, discount: Decimal) -> CouponRedemption:
    coupon = Coupon.objects.select_for_update().get(pk=coupon.pk)
    if not coupon.is_valid_now():
        raise ValidationError("优惠码已失效")
    coupon.used_count = F("used_count") + 1
    coupon.save(update_fields=["used_count"])
    return CouponRedemption.objects.create(coupon=coupon, owner=owner, order=order, discount=discount)


def _unique_code(prefix: str) -> str:
    import secrets

    for _ in range(8):
        code = f"{prefix}{secrets.token_hex(3).upper()}"
        if not Coupon.objects.filter(code=code).exists():
            return code
    return f"{prefix}{timezone.now():%Y%m%d%H%M%S}"


@transaction.atomic
def issue_checkout_coupon(owner: Owner, order=None) -> Coupon | None:
    """离店后自动发放复购券（每单最多一张）。"""
    if order is not None and Coupon.objects.filter(code__startswith=f"BACK{order.pk}-").exists():
        return None
    today = timezone.localdate()
    prefix = f"BACK{order.pk}-" if order else "BACK-"
    coupon = Coupon.objects.create(
        code=_unique_code(prefix),
        name="离店复购满减",
        kind=Coupon.Kind.FIXED,
        value=Decimal("30"),
        min_amount=Decimal("150"),
        store=getattr(order, "store", None) if order else None,
        valid_from=today,
        valid_until=today + timedelta(days=90),
        max_uses=1,
        max_per_owner=1,
    )
    from apps.notifications.services import notify_owner

    notify_owner(
        owner,
        "复购优惠券已到账",
        f"优惠码 {coupon.code}，满 ¥{coupon.min_amount} 减 ¥{coupon.value}，有效期至 {coupon.valid_until}",
        "/me/loyalty/",
    )
    return coupon


@transaction.atomic
def issue_review_coupon(owner: Owner, order=None) -> Coupon | None:
    """好评（≥4 星）额外发放感谢券。"""
    if order is None:
        return None
    review = getattr(order, "review", None)
    if review is None or review.rating < 4:
        return None
    if Coupon.objects.filter(code__startswith=f"THANKS{order.pk}-").exists():
        return None
    today = timezone.localdate()
    coupon = Coupon.objects.create(
        code=_unique_code(f"THANKS{order.pk}-"),
        name="好评感谢券",
        kind=Coupon.Kind.FIXED,
        value=Decimal("15"),
        min_amount=Decimal("100"),
        store=order.store,
        valid_from=today,
        valid_until=today + timedelta(days=60),
        max_uses=1,
        max_per_owner=1,
    )
    from apps.notifications.services import notify_owner

    notify_owner(
        owner,
        "感谢评价，送您一张优惠券",
        f"优惠码 {coupon.code}，满 ¥{coupon.min_amount} 减 ¥{coupon.value}",
        "/me/loyalty/",
        "success",
    )
    return coupon
