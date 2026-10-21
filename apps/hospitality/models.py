from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.bookings.models import Order
from apps.pets.models import Species


class Billing(models.TextChoices):
    ONCE = "once", "每次"
    NIGHT = "night", "每晚"


class AddonService(models.Model):
    code = models.SlugField("服务编码", max_length=32, unique=True)
    name = models.CharField("服务名称", max_length=40)
    summary = models.CharField("一句话介绍", max_length=80)
    description = models.TextField("服务说明", blank=True)
    icon = models.CharField("图标", max_length=40, default="bi-stars")
    price = models.DecimalField(
        "价格（元）", max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    billing = models.CharField("计费方式", max_length=10, choices=Billing, default=Billing.ONCE)
    species = models.CharField("适用宠物", max_length=10, choices=[*Species.choices, ("any", "全部")], default="any")
    is_active = models.BooleanField("在售", default=True)
    sort = models.PositiveSmallIntegerField("排序", default=0)

    class Meta:
        verbose_name = "增值服务"
        verbose_name_plural = verbose_name
        ordering = ["sort", "pk"]

    def __str__(self):
        unit = "晚" if self.billing == Billing.NIGHT else "次"
        return f"{self.name}（¥{self.price}/{unit}）"

    def fits(self, species: str) -> bool:
        return self.species in {species, "any"}


class OrderAddon(models.Model):
    order = models.ForeignKey(Order, verbose_name="订单", on_delete=models.CASCADE, related_name="addons")
    service = models.ForeignKey(AddonService, verbose_name="增值服务", on_delete=models.PROTECT, related_name="lines")
    quantity = models.PositiveSmallIntegerField("数量", default=1, validators=[MinValueValidator(1)])
    unit_price = models.DecimalField("成交单价", max_digits=8, decimal_places=2)
    nights = models.PositiveSmallIntegerField("计费晚数", default=1)
    line_total = models.DecimalField("小计", max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = "订单增值项"
        verbose_name_plural = verbose_name
        unique_together = ("order", "service")

    def __str__(self):
        return f"{self.order} · {self.service.name}"


class CareTask(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "待办"
        DONE = "done", "已完成"
        SKIPPED = "skipped", "已跳过"

    order = models.ForeignKey(Order, verbose_name="订单", on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField("任务", max_length=80)
    due_date = models.DateField("截止日期")
    status = models.CharField("状态", max_length=10, choices=Status, default=Status.PENDING)
    note = models.CharField("说明", max_length=200, blank=True)

    class Meta:
        verbose_name = "护理任务"
        verbose_name_plural = verbose_name
        ordering = ["due_date", "pk"]

    def __str__(self):
        return self.title


class Supply(models.Model):
    name = models.CharField("物资", max_length=40, unique=True)
    unit = models.CharField("单位", max_length=10, default="件")
    stock = models.DecimalField("库存", max_digits=10, decimal_places=1, default=0)
    reorder_level = models.DecimalField("补货线", max_digits=10, decimal_places=1, default=0)
    note = models.CharField("备注", max_length=120, blank=True)

    class Meta:
        verbose_name = "物资库存"
        verbose_name_plural = verbose_name
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} {self.stock}{self.unit}"

    @property
    def low(self) -> bool:
        return self.stock <= self.reorder_level


class SupplyMovement(models.Model):
    supply = models.ForeignKey(Supply, verbose_name="物资", on_delete=models.PROTECT, related_name="movements")
    quantity = models.DecimalField("数量", max_digits=10, decimal_places=1, help_text="入库为正，领用为负")
    order = models.ForeignKey(
        Order, verbose_name="关联订单", on_delete=models.SET_NULL, null=True, blank=True, related_name="supply_uses"
    )
    note = models.CharField("说明", max_length=120, blank=True)
    created_at = models.DateTimeField("时间", auto_now_add=True)

    class Meta:
        verbose_name = "库存流水"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.supply.name} {self.quantity}"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new:
            self.supply.stock = (self.supply.stock or 0) + self.quantity
            self.supply.save(update_fields=["stock"])


class HolidayRate(models.Model):
    day = models.DateField("日期", unique=True)
    label = models.CharField("名称", max_length=20, default="旺季")
    multiplier = models.DecimalField(
        "房价系数",
        max_digits=4,
        decimal_places=2,
        default=Decimal("1.20"),
        validators=[MinValueValidator(Decimal("0.50"))],
        help_text="1.20 表示在日价上加价 20%",
    )
    is_active = models.BooleanField("启用", default=True)

    class Meta:
        verbose_name = "日历房价"
        verbose_name_plural = verbose_name
        ordering = ["day"]

    def __str__(self):
        return f"{self.day} {self.label} ×{self.multiplier}"


def local_today():
    return timezone.localdate()