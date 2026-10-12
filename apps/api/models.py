import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


class ApiToken(models.Model):
    """渠道 / 小程序调用开放 API 的访问令牌。"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="绑定用户", on_delete=models.CASCADE, related_name="api_tokens"
    )
    name = models.CharField("用途说明", max_length=80)
    key = models.CharField("令牌", max_length=64, unique=True, editable=False)
    is_active = models.BooleanField("启用", default=True)
    last_used_at = models.DateTimeField("最近使用", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "API 令牌"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name}（{self.user}）"

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    def touch(self):
        ApiToken.objects.filter(pk=self.pk).update(last_used_at=timezone.now())
