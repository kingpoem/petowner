from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.pets.models import Owner
from apps.stores.models import Store


class PointLedger(models.Model):
    class Kind(models.TextChoices):
        EARN = "earn", "消费积分"
        REDEEM = "redeem", "积分抵扣"
        ADJUST = "adjust", "人工调整"
        EXPIRE = "expire", "过期清零"

    owner = models.ForeignKey(Owner, verbose_name="主人", on_delete=models.CASCADE, related_name="point_ledger")
    kind = models.CharField("类型", max_length=10, choices=Kind)
    points = models.IntegerField("变动积分")  # 正=获得，负=消耗
    balance = models.PositiveIntegerField("变动后余额", default=0)
    note = models.CharField("说明", max_length=200, blank=True)
    order = models.ForeignKey(
        "bookings.Order", verbose_name="关联订单", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField("时间", auto_now_add=True)

    class Meta:
        verbose_name = "积分流水"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.owner} {self.points:+d}"


class Coupon(models.Model):
    class Kind(models.TextChoices):
        FIXED = "fixed", "满减（元）"
        PERCENT = "percent", "折扣（%）"

    code = models.CharField("优惠码", max_length=30, unique=True)
    name = models.CharField("名称", max_length=80)
    kind = models.CharField("类型", max_length=10, choices=Kind, default=Kind.FIXED)
    value = models.DecimalField("面额/折扣", max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    min_amount = models.DecimalField("最低订单金额", max_digits=10, decimal_places=2, default=0)
    store = models.ForeignKey(
        Store, verbose_name="适用门店", null=True, blank=True, on_delete=models.CASCADE, help_text="空=全部门店"
    )
    valid_from = models.DateField("生效日期")
    valid_until = models.DateField("失效日期")
    max_uses = models.PositiveIntegerField("总次数上限", default=0, help_text="0=不限")
    max_per_owner = models.PositiveIntegerField("每人限用", default=1)
    used_count = models.PositiveIntegerField("已使用次数", default=0, editable=False)
    is_active = models.BooleanField("启用", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "优惠券"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code}（{self.name}）"

    def clean(self):
        if self.valid_until and self.valid_from and self.valid_until < self.valid_from:
            raise ValidationError({"valid_until": "失效日期不能早于生效日期"})
        if self.kind == self.Kind.PERCENT and self.value > 100:
            raise ValidationError({"value": "折扣不能超过 100"})

    def is_valid_now(self) -> bool:
        today = timezone.localdate()
        return (
            self.is_active
            and self.valid_from <= today <= self.valid_until
            and (self.max_uses == 0 or self.used_count < self.max_uses)
        )

    def discount_for(self, amount: Decimal) -> Decimal:
        if amount < self.min_amount:
            return Decimal("0.00")
        if self.kind == self.Kind.FIXED:
            return min(self.value, amount)
        return (amount * self.value / Decimal("100")).quantize(Decimal("0.01"))


class CouponRedemption(models.Model):
    coupon = models.ForeignKey(Coupon, verbose_name="优惠券", on_delete=models.PROTECT, related_name="redemptions")
    owner = models.ForeignKey(Owner, verbose_name="主人", on_delete=models.CASCADE, related_name="coupon_redemptions")
    order = models.OneToOneField(
        "bookings.Order", verbose_name="订单", on_delete=models.CASCADE, related_name="coupon_redemption"
    )
    discount = models.DecimalField("优惠金额", max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "优惠券核销"
        verbose_name_plural = verbose_name
