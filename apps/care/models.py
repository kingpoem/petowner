from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

from apps.bookings.models import Order
from apps.images import OptimizedImageField
from apps.notifications.services import notify_owner


class ServiceRecord(models.Model):
    """寄养服务记录：关键业务字段由人工如实填写，不做枚举选择题。"""

    ALERT_KEYWORDS = ("异常", "腹泻", "呕吐", "发烧", "发热", "受伤", "拒食", "未进食", "吃得很少", "精神不振")

    code = models.CharField("记录编号", max_length=20, unique=True, blank=True, editable=False)
    order = models.ForeignKey(Order, verbose_name="寄养订单", on_delete=models.CASCADE, related_name="service_records")
    staff = models.CharField("服务人员", max_length=50)
    feeding_time = models.DateTimeField("喂养时间", default=timezone.now)
    care_content = models.TextField("护理内容")
    appetite = models.CharField(
        "进食情况",
        max_length=100,
        blank=True,
        help_text="如实填写，如：全部吃完 / 只吃一半 / 未进食 / 非喂食记录",
    )
    health_status = models.CharField(
        "健康状态",
        max_length=200,
        default="良好",
        help_text="如实填写当前状态，如：良好、精神尚可、轻微掉毛、异常：轻微腹泻",
    )
    health_note = models.CharField("健康情况说明", max_length=200, blank=True)
    photo = OptimizedImageField("现场照片", upload_to="care/%Y/%m/", blank=True)
    created_at = models.DateTimeField("记录时间", auto_now_add=True)

    class Meta:
        verbose_name = "服务记录"
        verbose_name_plural = verbose_name
        ordering = ["-feeding_time"]

    def __str__(self):
        return self.code or (f"S{self.pk:05d}" if self.pk else "新服务记录")

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.code:
                self.code = f"S{self.pk:05d}"
                type(self).objects.filter(pk=self.pk).update(code=self.code)
            if is_new:
                self._after_create()

    @property
    def pet(self):
        return self.order.pet

    @property
    def needs_attention(self) -> bool:
        blob = f"{self.health_status} {self.health_note} {self.appetite} {self.care_content}"
        return any(keyword in blob for keyword in self.ALERT_KEYWORDS)

    @classmethod
    def attention_q(cls) -> Q:
        q = Q()
        for keyword in cls.ALERT_KEYWORDS:
            q |= (
                Q(health_status__icontains=keyword)
                | Q(health_note__icontains=keyword)
                | Q(appetite__icontains=keyword)
                | Q(care_content__icontains=keyword)
            )
        return q

    def clean(self):
        if self.order_id and self.order.status not in (Order.Status.CHECKED_IN, Order.Status.COMPLETED):
            raise ValidationError({"order": "只能为寄养中或已完成的订单登记服务记录"})

    def _after_create(self):
        pet = self.order.pet
        if self.needs_attention:
            detail = self.health_note or self.health_status or self.care_content
            pet.health_status = f"寄养中异常：{detail}"[:200]
            pet.save(update_fields=["health_status"])
            notify_owner(
                pet.owner,
                f"{pet.name} 健康状况提醒",
                f"护理人员 {self.staff} 记录到异常：{detail}。我们会持续观察并与您联系。",
                self.order.get_absolute_url(),
                "danger",
                sms_event="health",
            )
        else:
            notify_owner(
                pet.owner,
                f"{pet.name} 有新的护理动态",
                self.care_content[:80],
                self.order.get_absolute_url(),
                sms_event="care",
            )


class Review(models.Model):
    order = models.OneToOneField(Order, verbose_name="寄养订单", on_delete=models.CASCADE, related_name="review")
    rating = models.PositiveSmallIntegerField(
        "服务评分", validators=[MinValueValidator(1), MaxValueValidator(5)], help_text="1-5 分"
    )
    content = models.TextField("评价内容", blank=True)
    feedback = models.TextField("意见反馈", blank=True)
    reply = models.TextField("机构回复", blank=True)
    is_public = models.BooleanField("官网展示", default=True)
    created_at = models.DateTimeField("评价时间", auto_now_add=True)

    class Meta:
        verbose_name = "服务评价"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.order} - {self.rating}分"

    def clean(self):
        if self.order_id and self.order.status != Order.Status.COMPLETED:
            raise ValidationError({"order": "寄养结束（订单已完成）后才能评价"})
