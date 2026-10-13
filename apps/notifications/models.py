from django.conf import settings
from django.db import models


class Notification(models.Model):
    class Level(models.TextChoices):
        INFO = "info", "通知"
        SUCCESS = "success", "成功"
        WARNING = "warning", "提醒"
        DANGER = "danger", "警告"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="接收人", on_delete=models.CASCADE, related_name="notifications"
    )
    title = models.CharField("标题", max_length=100)
    body = models.TextField("内容", blank=True)
    link = models.CharField("跳转链接", max_length=200, blank=True)
    level = models.CharField("级别", max_length=10, choices=Level, default=Level.INFO)
    is_read = models.BooleanField("已读", default=False)
    created_at = models.DateTimeField("时间", auto_now_add=True)

    class Meta:
        verbose_name = "站内通知"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "is_read"])]

    def __str__(self):
        return self.title
