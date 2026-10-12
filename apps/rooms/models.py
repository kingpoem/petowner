from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from apps.images import OptimizedImageField
from apps.pets.models import PetSize


class Room(models.Model):
    class RoomType(models.TextChoices):
        STANDARD = "standard", "标准间"
        DELUXE = "deluxe", "豪华间"
        SUITE = "suite", "套间"

    class PetType(models.TextChoices):
        DOG = "dog", "狗"
        CAT = "cat", "猫"
        ANY = "any", "通用"

    class Status(models.TextChoices):
        AVAILABLE = "available", "空闲"
        FULL = "full", "已满"
        MAINTENANCE = "maintenance", "维护停用"

    store = models.ForeignKey(
        "stores.Store",
        verbose_name="所属门店",
        on_delete=models.PROTECT,
        related_name="rooms",
        null=True,
        blank=True,
    )
    number = models.CharField("房间编号", max_length=20)
    name = models.CharField("展示名称", max_length=50, blank=True, help_text="官网展示用，如“阳光大床房”")
    room_type = models.CharField("房间类型", max_length=20, choices=RoomType, default=RoomType.STANDARD)
    pet_type = models.CharField("适用宠物类型", max_length=10, choices=PetType, default=PetType.ANY)
    max_pet_size = models.PositiveSmallIntegerField("最大接待体型", choices=PetSize, default=PetSize.LARGE)
    price = models.DecimalField(
        "寄养价格（元/天）", max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    capacity = models.PositiveSmallIntegerField("房间容量", default=1, validators=[MinValueValidator(1)])
    area = models.DecimalField("面积（㎡）", max_digits=5, decimal_places=1, null=True, blank=True)
    amenities = models.CharField(
        "设施", max_length=200, blank=True, help_text="用逗号分隔，如：空调,24h监控,独立活动区"
    )
    photo = OptimizedImageField("房间照片", upload_to="rooms/", blank=True)
    description = models.TextField("房间介绍", blank=True)
    status = models.CharField("房间状态", max_length=20, choices=Status, default=Status.AVAILABLE)
    is_listed = models.BooleanField("官网展示", default=True)

    class Meta:
        verbose_name = "寄养房间"
        verbose_name_plural = verbose_name
        ordering = ["number"]
        unique_together = ("store", "number")

    def __str__(self):
        return f"{self.number}（{self.get_room_type_display()}/{self.get_pet_type_display()}）"

    @property
    def display_name(self) -> str:
        return self.name or f"{self.get_room_type_display()} {self.number}"

    @property
    def amenity_list(self) -> list[str]:
        return [a.strip() for a in self.amenities.replace("，", ",").split(",") if a.strip()]

    def accepts(self, species: str) -> bool:
        return self.pet_type == self.PetType.ANY or self.pet_type == species

    def fits(self, pet) -> bool:
        return self.accepts(pet.species) and pet.size <= self.max_pet_size

    def current_occupancy(self) -> int:
        from apps.bookings.models import Order

        return self.orders.filter(status=Order.Status.CHECKED_IN).count()

    def refresh_status(self):
        """根据入住中订单数刷新空闲/已满；维护停用状态需人工解除。"""
        if self.status == self.Status.MAINTENANCE:
            return
        new_status = self.Status.FULL if self.current_occupancy() >= self.capacity else self.Status.AVAILABLE
        if new_status != self.status:
            self.status = new_status
            self.save(update_fields=["status"])


class PriceRule(models.Model):
    name = models.CharField("规则名称", max_length=50, help_text="如：国庆假期")
    start_date = models.DateField("开始日期")
    end_date = models.DateField("结束日期", help_text="含当天")
    multiplier = models.DecimalField(
        "价格倍率",
        max_digits=4,
        decimal_places=2,
        default=Decimal("1.20"),
        validators=[MinValueValidator(Decimal("0.10"))],
        help_text="1.20 表示上浮 20%，0.90 表示九折",
    )
    is_active = models.BooleanField("启用", default=True)

    class Meta:
        verbose_name = "价格规则"
        verbose_name_plural = verbose_name
        ordering = ["start_date"]

    def __str__(self):
        return f"{self.name}（{self.start_date:%m-%d}~{self.end_date:%m-%d} ×{self.multiplier}）"

    def clean(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "结束日期不能早于开始日期"})
