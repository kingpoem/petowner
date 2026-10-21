import secrets
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone

from apps.notifications.services import notify_owner
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
    amount = models.DecimalField("订单金额（元）", max_digits=10, decimal_places=2, default=0, editable=False)
    payment_status = models.CharField("支付状态", max_length=20, choices=PaymentStatus, default=PaymentStatus.UNPAID)
    status = models.CharField("订单状态", max_length=20, choices=Status, default=Status.PENDING)
    source = models.CharField("下单渠道", max_length=20, choices=Source, default=Source.FRONT_DESK)
    note = models.CharField("备注", max_length=200, blank=True)
    addon_amount = models.DecimalField("增值服务（元）", max_digits=10, decimal_places=2, default=0)
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
            self.store_id = (
                getattr(self.room, "store_id", None)
                or Room.objects.filter(pk=self.room_id).values_list("store_id", flat=True).first()
            )
        if self.status == self.Status.PENDING and self.payment_status == self.PaymentStatus.UNPAID:
            q = quote(self.room, self.check_in, self.check_out)
            addon = Decimal(self.addon_amount or 0)
            self.amount = max(q.total + addon, Decimal("0.00"))
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
    def can_reschedule(self) -> bool:
        return self.status == self.Status.PENDING and self.check_in > timezone.localdate()

    def cancellation_fee(self) -> Decimal:
        """入住日当天及之后取消，扣除前 LATE_CANCEL_NIGHTS 晚房费（不超过已付金额）。"""
        paid = self.net_paid
        if paid <= 0 or timezone.localdate() < self.check_in or settings.LATE_CANCEL_NIGHTS <= 0:
            return Decimal("0.00")
        nights = quote(self.room, self.check_in, self.check_out).nights[: settings.LATE_CANCEL_NIGHTS]
        return min(sum((n.price for n in nights), Decimal("0.00")), self.amount, paid)

    @property
    def pay_deadline(self):
        """线上未支付订单的支付截止时间；门店录入或已支付订单返回 None。"""
        if self.source != self.Source.ONLINE or self.payment_status != self.PaymentStatus.UNPAID or not self.created_at:
            return None
        return self.created_at + timedelta(minutes=settings.PAYMENT_TIMEOUT_MINUTES)

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
        rescheduling = getattr(self, "_rescheduling", False)
        if not self._state.adding and self.payment_status != self.PaymentStatus.UNPAID and not rescheduling:
            original = Order.objects.get(pk=self.pk)
            if (original.room_id, original.check_in, original.check_out) != (
                self.room_id,
                self.check_in,
                self.check_out,
            ):
                raise ValidationError("已付款订单请通过“改期”功能修改房间或日期，以便自动结算差价")
        if rescheduling and self.check_in < timezone.localdate():
            raise ValidationError({"check_in": "入住时间不能早于今天"})
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

    def _notify(self, title: str, body: str, level: str = "info"):
        notify_owner(self.owner, title, body, self.get_absolute_url(), level)

    def _sync_payment_status(self):
        paid = self.net_paid
        if paid <= 0:
            refunded = self.payments.filter(kind=Payment.Kind.REFUND, status=Payment.Status.SUCCESS).exists()
            self.payment_status = self.PaymentStatus.REFUNDED if refunded else self.PaymentStatus.UNPAID
        elif paid >= self.amount:
            self.payment_status = self.PaymentStatus.PAID
        else:
            self.payment_status = self.PaymentStatus.PARTIAL

    def _refund(self, amount: Decimal) -> "Payment | None":
        from apps.payments.services import gateway_refund

        return gateway_refund(self, amount)

    @transaction.atomic
    def pay(self, method: str) -> "Payment":
        """入账一笔已成功的收款（门店收款、演示数据、或渠道回调确认后）。

        顾客在线支付请走 apps.payments.services.start_checkout，由异步通知调用 settle_payment。
        """
        if not self.can_pay:
            raise ValidationError("该订单当前无需支付")
        due = self.balance_due
        top_up = self.payment_status == self.PaymentStatus.PARTIAL
        payment = Payment.objects.create(
            order=self, method=method, kind=Payment.Kind.PAY, amount=due, status=Payment.Status.SUCCESS
        )
        self._sync_payment_status()
        self.paid_at = timezone.now()
        self.save(update_fields=["payment_status", "paid_at", "updated_at"])
        title = "补款成功" if top_up else "支付成功"
        self._notify(title, f"订单 {self} 已支付 ¥{due}，期待 {self.pet.name} 的到来。", "success")
        return payment

    def mark_paid(self):
        return self.pay(Payment.Method.CASH)

    @transaction.atomic
    def cancel(self, reason: str = "", waive_fee: bool = False):
        self._require_status(self.Status.PENDING, action="取消预约")
        fee = Decimal("0.00") if waive_fee else self.cancellation_fee()
        paid = self.net_paid
        refund = self._refund(paid - fee)
        self.status = self.Status.CANCELLED
        self.cancel_reason = reason
        self.cancel_fee = fee
        if paid > 0:
            # 订单金额改为实际留存的违约金，使“已付 = 应付”，对账与营收统计口径一致
            self.amount = fee
            self._sync_payment_status()
        self.save(update_fields=["status", "cancel_reason", "cancel_fee", "amount", "payment_status", "updated_at"])
        detail = f"，¥{refund.amount} 已原路退回" if refund else ""
        if fee:
            detail += f"（入住当天取消，扣除首晚房费 ¥{fee}）"
        self._notify("预约已取消", f"订单 {self} 已取消{detail}。", "warning")

    @transaction.atomic
    def reschedule(self, room: Room, check_in, check_out) -> Decimal:
        """改期或换房；已付款项多退少补，返回需补付的金额（多退时为 0）。"""
        if not self.can_reschedule:
            raise ValidationError("仅入住日之前的已预约订单可以改期")
        list(Room.objects.select_for_update().filter(pk=room.pk))
        old = (self.room_id, self.check_in, self.check_out)
        self.room, self.check_in, self.check_out = room, check_in, check_out
        if old == (self.room_id, self.check_in, self.check_out):
            raise ValidationError("房间和日期均未变化")
        self._rescheduling = True
        try:
            self.full_clean()
        finally:
            self._rescheduling = False
        from apps.hospitality.services import retarget_addons

        retarget_addons(self)
        new_quote = quote(room, check_in, check_out)
        self.amount = max(new_quote.total + Decimal(self.addon_amount or 0), Decimal("0.00"))
        refund = self._refund(self.net_paid - self.amount)
        self._sync_payment_status()
        self.save()
        due = self.balance_due
        if refund:
            money = f"差价 ¥{refund.amount} 已原路退回"
        elif due and self.payment_status == self.PaymentStatus.PARTIAL:
            money = f"需补差价 ¥{due}"
        else:
            money = f"订单金额 ¥{self.amount}"
        self._notify(
            "预约已改期",
            f"{self.pet.name} 改为 {check_in:%m月%d日} 入住 {room.display_name}，{check_out:%m月%d日} 离店；{money}。",
        )
        return due

    @transaction.atomic
    def start_boarding(self):
        self._require_status(self.Status.PENDING, action="办理入住")
        self.status = self.Status.CHECKED_IN
        self.checked_in_at = timezone.now()
        self.save(update_fields=["status", "checked_in_at", "updated_at"])
        self.room.refresh_status()
        self._notify("已办理入住", f"{self.pet.name} 已入住 {self.room.display_name}，可随时查看护理动态。")

    @transaction.atomic
    def finish_boarding(self):
        self._require_status(self.Status.CHECKED_IN, action="办理离店")
        today = timezone.localdate()
        released_early = today < self.check_out
        self.status = self.Status.COMPLETED
        self.checked_out_at = timezone.now()
        refund = None
        if released_early:
            self.check_out = max(today, self.check_in + timedelta(days=1))
            if settings.EARLY_CHECKOUT_REFUND:
                from apps.hospitality.services import retarget_addons

                retarget_addons(self)
                stayed = quote(self.room, self.check_in, self.check_out)
                target = max(stayed.total + Decimal(self.addon_amount or 0), Decimal("0.00"))
                if target < self.amount:
                    self.amount = target
                    refund = self._refund(self.net_paid - self.amount)
                    self._sync_payment_status()
        self.save(
            update_fields=[
                "status",
                "checked_out_at",
                "check_out",
                "amount",
                "payment_status",
                "updated_at",
            ]
        )
        self.room.refresh_status()
        body = f"{self.pet.name} 已平安离店，欢迎为本次服务评价。"
        if refund:
            body += f"未入住的 {self.check_out:%m月%d日} 起房费 ¥{refund.amount} 已原路退回。"
        self._notify("寄养已完成", body, "success")


class Payment(models.Model):
    class Method(models.TextChoices):
        WECHAT = "wechat", "微信支付"
        ALIPAY = "alipay", "支付宝"
        CASH = "cash", "门店现金"
        CARD = "card", "门店刷卡"

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
        verbose_name = "收退款"
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
    if room.status == Room.Status.MAINTENANCE:
        return "room", "该房间正在维护停用，无法预约"
    if not room.accepts(pet.species):
        return "room", f"该房间不适用于{pet.get_species_display()}"
    if pet.size > room.max_pet_size:
        return "room", f"该房间最大接待{room.get_max_pet_size_display()}宠物，{pet.name}体型超出"
    if pet.temperament == Pet.Temperament.AGGRESSIVE and room.capacity > 1:
        return "room", "有攻击性的宠物只能入住单宠房间"
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
    rooms = Room.objects.exclude(status=Room.Status.MAINTENANCE).filter(
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


def expire_unpaid_orders() -> int:
    """取消超时未支付的线上订单并释放房间；返回取消数量。"""
    cutoff = timezone.now() - timedelta(minutes=settings.PAYMENT_TIMEOUT_MINUTES)
    stale = Order.objects.filter(
        source=Order.Source.ONLINE,
        status=Order.Status.PENDING,
        payment_status=Order.PaymentStatus.UNPAID,
        created_at__lt=cutoff,
    ).select_related("pet__owner", "room")
    count = 0
    for order in stale:
        order.cancel(f"超过 {settings.PAYMENT_TIMEOUT_MINUTES} 分钟未支付，系统自动取消")
        count += 1
    return count
