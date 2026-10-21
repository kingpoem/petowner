from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

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
