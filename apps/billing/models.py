from django.db import models
from django.utils import timezone

from apps.bookings.models import Order
from apps.pets.models import Owner


class Invoice(models.Model):
    class Kind(models.TextChoices):
        PERSONAL = "personal", "个人收据"
        COMPANY = "company", "企业抬头"

    class Status(models.TextChoices):
        PENDING = "pending", "待开具"
        ISSUED = "issued", "已开具"
        REJECTED = "rejected", "已驳回"

    order = models.OneToOneField(Order, verbose_name="订单", on_delete=models.PROTECT, related_name="invoice")
    owner = models.ForeignKey(Owner, verbose_name="申请人", on_delete=models.CASCADE, related_name="invoices")
    kind = models.CharField("类型", max_length=20, choices=Kind, default=Kind.PERSONAL)
    title = models.CharField("抬头", max_length=120)
    tax_no = models.CharField("税号", max_length=40, blank=True)
    email = models.EmailField("接收邮箱", blank=True)
    amount = models.DecimalField("金额", max_digits=10, decimal_places=2)
    receipt_no = models.CharField("收据号", max_length=40, unique=True, blank=True, editable=False)
    status = models.CharField("状态", max_length=20, choices=Status, default=Status.PENDING)
    pdf = models.FileField("PDF 文件", upload_to="invoices/%Y/%m/", blank=True)
    note = models.CharField("备注", max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    issued_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "发票/收据申请"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return self.receipt_no or f"发票#{self.pk}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.receipt_no:
            self.receipt_no = f"INV{timezone.localdate():%Y%m%d}{self.pk:05d}"
            type(self).objects.filter(pk=self.pk).update(receipt_no=self.receipt_no)
