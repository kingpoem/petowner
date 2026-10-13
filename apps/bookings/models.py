import secrets
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone

from apps.pets.models import Owner, Pet
from apps.rooms.models import Room
from apps.rooms.pricing import quote


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "已预约"
        CHECKED_IN = "checked_in", "寄养中"
        COMPLETED = "completed", "已完成"
        CANCELLED = "cancelled", "已取消"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "未支付"
        PARTIAL = "partial", "待补差价"
        PAID = "paid", "已支付"
        REFUNDED = "refunded", "已退款"

    class Source(models.TextChoices):
        ONLINE = "online", "线上预约"
        FRONT_DESK = "front_desk", "门店录入"

    ACTIVE_STATUSES = (Status.PENDING, Status.CHECKED_IN)

    order_no = models.CharField("订单编号", max_length=30, unique=True, blank=True, editable=False)
    store = models.ForeignKey(
        "stores.Store",
        verbose_name="门店",
        on_delete=models.PROTECT,
        related_name="orders",
        null=True,
        blank=True,
    )
    pet = models.ForeignKey(Pet, verbose_name="宠物", on_delete=models.PROTECT, related_name="orders")
    room = models.ForeignKey(Room, verbose_name="寄养房间", on_delete=models.PROTECT, related_name="orders")
    check_in = models.DateField("入住时间")
    check_out = models.DateField("离店时间")
    discount = models.DecimalField("优惠金额（元）", max_digits=10, decimal_places=2, default=0, editable=False)
    amount = models.DecimalField("订单金额（元）", max_digits=10, decimal_places=2, default=0, editable=False)
    payment_status = models.CharField("支付状态", max_length=20, choices=PaymentStatus, default=PaymentStatus.UNPAID)
    status = models.CharField("订单状态", max_length=20, choices=Status, default=Status.PENDING)
    source = models.CharField("下单渠道", max_length=20, choices=Source, default=Source.FRONT_DESK)
    note = models.CharField("备注", max_length=200, blank=True)
    cancel_reason = models.CharField("取消原因", max_length=200, blank=True)
    cancel_fee = models.DecimalField("取消违约金（元）", max_digits=10, decimal_places=2, default=0, editable=False)
    paid_at = models.DateTimeField("支付时间", null=True, blank=True)
    checked_in_at = models.DateTimeField("实际入住时间", null=True, blank=True)
    checked_out_at = models.DateTimeField("实际离店时间", null=True, blank=True)
    created_at = models.DateTimeField("下单时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "寄养订单"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["room", "status", "check_in", "check_out"])]

    def __str__(self):
        return self.order_no or f"订单#{self.pk}"

    def save(self, *args, **kwargs):
        if self.room_id and not self.store_id:
            self.store_id = getattr(self.room, "store_id", None) or Room.objects.filter(pk=self.room_id).values_list(
                "store_id", flat=True
            ).first()
        if self.status == self.Status.PENDING and self.room_id and self.check_in and self.check_out:
            q = quote(self.room, self.check_in, self.check_out)
            self.amount = q.total
            self.discount = q.discount
        super().save(*args, **kwargs)
        if not self.order_no:
            self.order_no = f"O{timezone.localdate():%Y%m%d}{self.pk:05d}"
            Order.objects.filter(pk=self.pk).update(order_no=self.order_no)

    def get_absolute_url(self):
        return reverse("web:order_detail", args=[self.order_no])

    @property
    def days(self) -> int:
        return (self.check_out - self.check_in).days

    @property
    def is_active(self) -> bool:
        return self.status in self.ACTIVE_STATUSES

    @property
    def owner(self) -> Owner:
        return self.pet.owner

    @property
    def net_paid(self) -> Decimal:
        if not self.pk:
            return Decimal("0.00")
        return sum(
            (p.signed_amount for p in self.payments.all() if p.status == Payment.Status.SUCCESS),
            Decimal("0.00"),
        )

    @property
    def balance_due(self) -> Decimal:
        return max(self.amount - self.net_paid, Decimal("0.00"))

    @property
    def can_pay(self) -> bool:
        return self.status != self.Status.CANCELLED and self.balance_due > 0

    @property
    def can_cancel(self) -> bool:
        return self.status == self.Status.PENDING

    @property
    def can_review(self) -> bool:
        return self.status == self.Status.COMPLETED and not hasattr(self, "review")

    def clean(self):
        if not (self.check_in and self.check_out and self.room_id and self.pet_id):
            return
        if self.check_out <= self.check_in:
            raise ValidationError({"check_out": "离店时间必须晚于入住时间"})
        if self._state.adding and self.check_in < timezone.localdate():
            raise ValidationError({"check_in": "入住时间不能早于今天"})
        if self.days > settings.MAX_BOARDING_DAYS:
            raise ValidationError({"check_out": f"单次寄养最长 {settings.MAX_BOARDING_DAYS} 天"})
        if not self.is_active:
            return
        problem = room_problem_for_pet(self.room, self.pet, self.check_out)
        if problem:
            raise ValidationError({problem[0]: problem[1]})
        if not is_room_available(self.room, self.check_in, self.check_out, exclude_order=self):
            raise ValidationError({"room": "该房间在所选时间段已满"})
        if pet_has_conflict(self.pet, self.check_in, self.check_out, exclude_order=self):
            raise ValidationError({"pet": "该宠物在所选时间段已有其他寄养订单"})

    def _require_status(self, *allowed, action: str):
        if self.status not in allowed:
            raise ValidationError(f"订单当前状态为「{self.get_status_display()}」，不能{action}")

    def _sync_payment_status(self):
        paid = self.net_paid
        if paid <= 0:
            refunded = self.payments.filter(kind=Payment.Kind.REFUND, status=Payment.Status.SUCCESS).exists()
            self.payment_status = self.PaymentStatus.REFUNDED if refunded else self.PaymentStatus.UNPAID
        elif paid >= self.amount:
            self.payment_status = self.PaymentStatus.PAID
        else:
            self.payment_status = self.PaymentStatus.PARTIAL

    @transaction.atomic
    def pay(self, method: str) -> "Payment":
        """入账一笔已成功的收款（门店收款或演示一键支付）。"""
        if not self.can_pay:
            raise ValidationError("该订单当前无需支付")
        due = self.balance_due
        payment = Payment.objects.create(
            order=self, method=method, kind=Payment.Kind.PAY, amount=due, status=Payment.Status.SUCCESS
        )
        self._sync_payment_status()
        self.paid_at = timezone.now()
        self.save(update_fields=["payment_status", "paid_at", "updated_at"])
        return payment

    def mark_paid(self):
        return self.pay(Payment.Method.CASH)

    @transaction.atomic
    def cancel(self, reason: str = "", waive_fee: bool = False):
        """取消预约并释放房间；已付款记一笔退款流水（无真实渠道）。"""
        self._require_status(self.Status.PENDING, action="取消预约")
        from apps.payments.services import record_refund

        paid = self.net_paid
        if paid > 0:
            record_refund(self, paid)
        self.status = self.Status.CANCELLED
        self.cancel_reason = reason
        self.cancel_fee = Decimal("0.00")
        self._sync_payment_status()
        self.save(update_fields=["status", "cancel_reason", "cancel_fee", "payment_status", "updated_at"])

    @transaction.atomic
    def start_boarding(self):
        self._require_status(self.Status.PENDING, action="办理入住")
        self.status = self.Status.CHECKED_IN
        self.checked_in_at = timezone.now()
        self.save(update_fields=["status", "checked_in_at", "updated_at"])
        self.room.refresh_status()

    @transaction.atomic
    def finish_boarding(self):
        self._require_status(self.Status.CHECKED_IN, action="办理离店")
        self.status = self.Status.COMPLETED
        self.checked_out_at = timezone.now()
        self.save(update_fields=["status", "checked_out_at", "updated_at"])
        self.room.refresh_status()


class Payment(models.Model):
    class Method(models.TextChoices):
        ONLINE = "online", "在线支付"
        CASH = "cash", "门店现金"
        CARD = "card", "门店刷卡"
        # 兼容历史流水
        WECHAT = "wechat", "微信支付"
        ALIPAY = "alipay", "支付宝"

    class Kind(models.TextChoices):
        PAY = "pay", "收款"
        REFUND = "refund", "退款"

    class Status(models.TextChoices):
        PENDING = "pending", "待确认"
        SUCCESS = "success", "已成功"
        FAILED = "failed", "已关闭"

    order = models.ForeignKey(Order, verbose_name="订单", on_delete=models.PROTECT, related_name="payments")
    kind = models.CharField("类型", max_length=10, choices=Kind, default=Kind.PAY)
    method = models.CharField("支付方式", max_length=10, choices=Method)
    amount = models.DecimalField("金额（元）", max_digits=10, decimal_places=2)
    status = models.CharField("状态", max_length=10, choices=Status, default=Status.SUCCESS)
    transaction_no = models.CharField("商户流水号", max_length=40, unique=True, editable=False)
    provider_trade_no = models.CharField("渠道交易号", max_length=64, blank=True)
    last_error = models.CharField("渠道错误", max_length=200, blank=True)
    retry_count = models.PositiveSmallIntegerField("重试次数", default=0)
    created_at = models.DateTimeField("时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    RETRY_PREFIX = "RETRY-"

    class Meta:
        verbose_name = "收退款流水"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return self.transaction_no

    def save(self, *args, **kwargs):
        if not self.transaction_no:
            prefix = "R" if self.kind == self.Kind.REFUND else "T"
            self.transaction_no = f"{prefix}{timezone.now():%Y%m%d%H%M%S}{secrets.token_hex(4).upper()}"
        super().save(*args, **kwargs)

    @property
    def signed_amount(self) -> Decimal:
        if self.status != self.Status.SUCCESS:
            return Decimal("0.00")
        return -self.amount if self.kind == self.Kind.REFUND else self.amount


def room_problem_for_pet(room: Room, pet: Pet, check_out) -> tuple[str, str] | None:
    """返回 (字段, 原因)；房间可接待该宠物时返回 None。"""
    if room.status in Room.BLOCKED_STATUSES:
        label = room.get_status_display()
        return "room", f"该房间当前为「{label}」状态，无法预约"
    if not room.accepts(pet.species):
        return "room", f"该房间不适用于{pet.get_species_display()}"
    if pet.size > room.max_pet_size:
        return "room", f"该房间最大接待{room.get_max_pet_size_display()}宠物，{pet.name}体型超出"
    if pet.temperament == Pet.Temperament.AGGRESSIVE and room.capacity > 1:
        return "room", "有攻击性的宠物只能入住单宠房间"
    if settings.REQUIRE_VACCINE and not pet.vaccine_valid_through(check_out):
        return "pet", f"{pet.name}的疫苗未登记或将在离店前过期，请先更新疫苗记录"
    return None


def _overlapping_orders(queryset, check_in, check_out, exclude_order=None):
    qs = queryset.filter(status__in=Order.ACTIVE_STATUSES, check_in__lt=check_out, check_out__gt=check_in)
    if exclude_order is not None and exclude_order.pk:
        qs = qs.exclude(pk=exclude_order.pk)
    return qs


def _has_capacity(stays, capacity: int, check_in, check_out) -> bool:
    """stays 为 (入住, 离店) 列表；逐日统计占用数，任意一天达到容量即视为不可用。"""
    if len(stays) < capacity:
        return True
    day = check_in
    while day < check_out:
        if sum(1 for start, end in stays if start <= day < end) >= capacity:
            return False
        day += timedelta(days=1)
    return True


def is_room_available(room: Room, check_in, check_out, exclude_order=None) -> bool:
    stays = _overlapping_orders(room.orders.all(), check_in, check_out, exclude_order).values_list(
        "check_in", "check_out"
    )
    return _has_capacity(list(stays), room.capacity, check_in, check_out)


def pet_has_conflict(pet: Pet, check_in, check_out, exclude_order=None) -> bool:
    return _overlapping_orders(pet.orders.all(), check_in, check_out, exclude_order).exists()


def find_available_rooms(
    species: str,
    check_in,
    check_out,
    pet: Pet | None = None,
    room_type: str = "",
    listed_only=False,
    store=None,
):
    """返回时间段内可预约的房间；传入 pet 时同时校验体型、性格等接待条件。"""
    rooms = Room.objects.exclude(status__in=Room.BLOCKED_STATUSES).filter(
        models.Q(pet_type=Room.PetType.ANY) | models.Q(pet_type=species)
    )
    if store is not None:
        rooms = rooms.filter(models.Q(store=store) | models.Q(store__isnull=True))
    if room_type:
        rooms = rooms.filter(room_type=room_type)
    if listed_only:
        rooms = rooms.filter(is_listed=True)
    rooms = list(rooms)
    stays: dict[int, list] = {room.pk: [] for room in rooms}
    overlapping = _overlapping_orders(Order.objects.filter(room__in=rooms), check_in, check_out)
    for room_id, start, end in overlapping.values_list("room_id", "check_in", "check_out"):
        stays[room_id].append((start, end))
    result = []
    for room in rooms:
        if pet is not None:
            problem = room_problem_for_pet(room, pet, check_out)
            if problem and problem[0] == "room":
                continue
        if _has_capacity(stays[room.pk], room.capacity, check_in, check_out):
            result.append(room)
    return result

