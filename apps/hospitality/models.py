from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.bookings.models import Order
from apps.pets.models import Owner, Pet, Species


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


class Coupon(models.Model):
    class Kind(models.TextChoices):
        PERCENT = "percent", "折扣（%）"
        AMOUNT = "amount", "立减（元）"

    code = models.CharField("优惠码", max_length=32, unique=True)
    name = models.CharField("名称", max_length=40)
    kind = models.CharField("类型", max_length=10, choices=Kind, default=Kind.AMOUNT)
    value = models.DecimalField("力度", max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    min_spend = models.DecimalField("最低消费（元）", max_digits=10, decimal_places=2, default=0)
    starts_on = models.DateField("开始日期", null=True, blank=True)
    ends_on = models.DateField("结束日期", null=True, blank=True)
    usage_limit = models.PositiveIntegerField("发放上限", default=0, help_text="0 表示不限次数")
    used_count = models.PositiveIntegerField("已使用", default=0)
    is_active = models.BooleanField("启用", default=True)

    class Meta:
        verbose_name = "优惠券"
        verbose_name_plural = verbose_name
        ordering = ["-is_active", "code"]

    def __str__(self):
        return f"{self.code} {self.name}"

    def usable_on(self, day, spend: Decimal) -> str:
        """返回不可用原因；可用时返回空字符串。"""
        if not self.is_active:
            return "优惠码已停用"
        if self.starts_on and day < self.starts_on:
            return "优惠码尚未生效"
        if self.ends_on and day > self.ends_on:
            return "优惠码已过期"
        if self.usage_limit and self.used_count >= self.usage_limit:
            return "优惠码已领完"
        if spend < self.min_spend:
            return f"满 ¥{self.min_spend} 可用"
        return ""

    def discount_for(self, spend: Decimal) -> Decimal:
        if self.kind == self.Kind.PERCENT:
            rate = min(self.value, Decimal("100")) / Decimal("100")
            return (spend * rate).quantize(Decimal("0.01"))
        return min(self.value, spend)


class MemberAccount(models.Model):
    TIERS = (
        (8000, "黑金", Decimal("0.92")),
        (2000, "金卡", Decimal("0.95")),
        (500, "银卡", Decimal("0.98")),
        (0, "萌新", Decimal("1")),
    )

    owner = models.OneToOneField(Owner, verbose_name="主人", on_delete=models.CASCADE, related_name="membership")
    points = models.PositiveIntegerField("可用积分", default=0)
    lifetime_points = models.PositiveIntegerField("累计积分", default=0)
    created_at = models.DateTimeField("入会时间", auto_now_add=True)

    class Meta:
        verbose_name = "会员账户"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.owner.name} · {self.tier_name} · {self.points} 积分"

    @property
    def tier_name(self) -> str:
        for threshold, name, _rate in self.TIERS:
            if self.lifetime_points >= threshold:
                return name
        return "萌新"

    @property
    def rate(self) -> Decimal:
        for threshold, _name, rate in self.TIERS:
            if self.lifetime_points >= threshold:
                return rate
        return Decimal("1")

    @property
    def next_tier(self) -> tuple[str, int] | None:
        higher = [item for item in self.TIERS if item[0] > self.lifetime_points]
        if not higher:
            return None
        threshold, name, _rate = higher[-1]
        return name, threshold

    @property
    def progress_percent(self) -> int:
        nxt = self.next_tier
        if nxt is None:
            return 100
        return min(100, int(self.lifetime_points * 100 / nxt[1])) if nxt[1] else 100

    @property
    def points_to_next(self) -> int:
        nxt = self.next_tier
        if nxt is None:
            return 0
        return max(nxt[1] - self.lifetime_points, 0)

    @property
    def discount_label(self) -> str:
        if self.rate >= 1:
            return "无折扣"
        text = format(self.rate * 10, "f").rstrip("0").rstrip(".")
        return f"{text} 折"


class PointLedger(models.Model):
    account = models.ForeignKey(MemberAccount, verbose_name="会员", on_delete=models.CASCADE, related_name="entries")
    order = models.ForeignKey(
        Order, verbose_name="订单", on_delete=models.SET_NULL, null=True, blank=True, related_name="point_entries"
    )
    delta = models.IntegerField("变动")
    reason = models.CharField("原因", max_length=20)
    created_at = models.DateTimeField("时间", auto_now_add=True)

    class Meta:
        verbose_name = "积分流水"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["account", "order", "reason"],
                name="uniq_point_entry_per_order_reason",
            )
        ]

    def __str__(self):
        sign = "+" if self.delta > 0 else ""
        return f"{sign}{self.delta} {self.reason}"


class VaccineRecord(models.Model):
    pet = models.ForeignKey(Pet, verbose_name="宠物", on_delete=models.CASCADE, related_name="vaccines")
    name = models.CharField("疫苗名称", max_length=40)
    batch = models.CharField("批号", max_length=40, blank=True)
    clinic = models.CharField("接种机构", max_length=80, blank=True)
    injected_on = models.DateField("接种日期")
    expires_on = models.DateField("有效期至")
    note = models.CharField("备注", max_length=120, blank=True)

    class Meta:
        verbose_name = "疫苗记录"
        verbose_name_plural = verbose_name
        ordering = ["-expires_on"]

    def __str__(self):
        return f"{self.pet.name} {self.name}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        latest = self.pet.vaccines.order_by("-expires_on").values_list("expires_on", flat=True).first()
        if latest and self.pet.vaccine_expiry != latest:
            self.pet.vaccine_expiry = latest
            self.pet.save(update_fields=["vaccine_expiry"])


class Medication(models.Model):
    pet = models.ForeignKey(Pet, verbose_name="宠物", on_delete=models.CASCADE, related_name="medications")
    drug = models.CharField("药品", max_length=40)
    dosage = models.CharField("剂量", max_length=40)
    frequency = models.CharField("频次", max_length=40, help_text="如：每日两次，随早餐")
    note = models.CharField("注意事项", max_length=120, blank=True)
    is_active = models.BooleanField("寄养期间执行", default=True)

    class Meta:
        verbose_name = "用药计划"
        verbose_name_plural = verbose_name
        ordering = ["-is_active", "drug"]

    def __str__(self):
        return f"{self.pet.name} · {self.drug}"


class StaffMember(models.Model):
    class Role(models.TextChoices):
        FRONT = "front", "前台"
        CARER = "carer", "护理师"
        MANAGER = "manager", "店长"

    name = models.CharField("姓名", max_length=30)
    phone = models.CharField("电话", max_length=20, blank=True)
    role = models.CharField("岗位", max_length=10, choices=Role, default=Role.CARER)
    skills = models.CharField("擅长", max_length=120, blank=True)
    bio = models.CharField("简介", max_length=200, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="后台账号",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff_profiles",
    )
    is_active = models.BooleanField("在职", default=True)

    class Meta:
        verbose_name = "员工"
        verbose_name_plural = verbose_name
        ordering = ["role", "name"]

    def __str__(self):
        return f"{self.name}（{self.get_role_display()}）"


class CareTask(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "待办"
        DONE = "done", "已完成"
        SKIPPED = "skipped", "已跳过"

    order = models.ForeignKey(Order, verbose_name="订单", on_delete=models.CASCADE, related_name="tasks")
    staff = models.ForeignKey(
        StaffMember, verbose_name="负责人", on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks"
    )
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


class WaitlistEntry(models.Model):
    class Status(models.TextChoices):
        WAITING = "waiting", "排队中"
        OFFERED = "offered", "已通知"
        BOOKED = "booked", "已转预约"
        CANCELLED = "cancelled", "已取消"

    owner = models.ForeignKey(Owner, verbose_name="主人", on_delete=models.CASCADE, related_name="waitlist")
    pet = models.ForeignKey(Pet, verbose_name="宠物", on_delete=models.CASCADE, related_name="waitlist")
    room_type = models.CharField(
        "期望房型",
        max_length=20,
        blank=True,
        choices=[("", "不限房型"), ("standard", "标准间"), ("deluxe", "豪华间"), ("suite", "套间")],
    )
    check_in = models.DateField("期望入住")
    check_out = models.DateField("期望离店")
    note = models.CharField("备注", max_length=200, blank=True)
    status = models.CharField("状态", max_length=12, choices=Status, default=Status.WAITING)
    created_at = models.DateTimeField("提交时间", auto_now_add=True)

    class Meta:
        verbose_name = "满房候补"
        verbose_name_plural = verbose_name
        ordering = ["check_in", "created_at"]

    def __str__(self):
        return f"{self.pet.name} {self.check_in} 候补"


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


class StoreNotice(models.Model):
    title = models.CharField("标题", max_length=60)
    body = models.TextField("正文")
    is_published = models.BooleanField("发布", default=True)
    pinned = models.BooleanField("置顶", default=False)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "门店公告"
        verbose_name_plural = verbose_name
        ordering = ["-pinned", "-created_at"]

    def __str__(self):
        return self.title

    @classmethod
    def published(cls):
        return cls.objects.filter(is_published=True)


def ensure_member(owner: Owner) -> MemberAccount:
    account, _created = MemberAccount.objects.get_or_create(owner=owner)
    return account


def local_today():
    return timezone.localdate()
