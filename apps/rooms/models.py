from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from apps.images import OptimizedImageField
from apps.pets.models import PetSize


class Room(models.Model):
    class RoomType(models.TextChoices):
        STANDARD = "standard", "标准间"
        DELUXE = "deluxe", "豪华间"
        SUITE = "suite", "套房"
        VIP = "vip", "VIP套房"

    # 官网房型说明：对应真实寄养里的犬舍 / 豪华房 / 独立套房 / 带院 VIP
    ROOM_TYPE_GUIDES = {
        RoomType.STANDARD: {
            "title": "标准间",
            "subtitle": "传统犬舍 / 独立笼位风格",
            "blurb": "空间紧凑实用，含基础喂养、清洁与定时遛放（或猫区陪玩）。适合短期寄养、预算友好，以及性格稳定的中小型宠物。",
            "price_hint": "约 ¥50–120 / 晚",
            "icon": "bi-house",
        },
        RoomType.DELUXE: {
            "title": "豪华间",
            "subtitle": "更大空间 · 更多一对一照料",
            "blurb": "面积与床具升级，活动区更宽敞，互动时间更充足。适合中大型犬，或需要更多活动空间、不愿合笼的宠物。",
            "price_hint": "约 ¥120–250 / 晚",
            "icon": "bi-house-heart",
        },
        RoomType.SUITE: {
            "title": "套房",
            "subtitle": "实墙独立房 · 安静私密",
            "blurb": "独立房间（非铁丝笼位），常配备窗景、摄像头与恒温新风。适合胆小、老年、易应激，或主人希望实时查看动态的宠物。",
            "price_hint": "约 ¥150–350 / 晚",
            "icon": "bi-door-open",
        },
        RoomType.VIP: {
            "title": "VIP套房",
            "subtitle": "最大面积 · 可含独立小院",
            "blurb": "顶级空间与增值护理（阳光区、独立小院、多宠同住等按房说明）。适合长住、家庭多宠同行，或节假日希望锁定优质房位的主人。",
            "price_hint": "约 ¥300+ / 晚",
            "icon": "bi-stars",
        },
    }

    class PetType(models.TextChoices):
        DOG = "dog", "狗"
        CAT = "cat", "猫"
        ANY = "any", "猫狗皆可"

    class Status(models.TextChoices):
        AVAILABLE = "available", "空闲"
        FULL = "full", "已满"
        CLEANING = "cleaning", "清洁消毒"
        MAINTENANCE = "maintenance", "维护停用"

    # 不可对外预约的状态（看似空房但实际不可用）
    BLOCKED_STATUSES = (Status.CLEANING, Status.MAINTENANCE)

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
        """根据入住中订单数刷新空闲/已满；清洁消毒与维护停用需人工解除。"""
        if self.status in self.BLOCKED_STATUSES:
            return
        new_status = self.Status.FULL if self.current_occupancy() >= self.capacity else self.Status.AVAILABLE
        if new_status != self.status:
            self.status = new_status
            self.save(update_fields=["status"])
