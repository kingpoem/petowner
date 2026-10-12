from django.conf import settings
from django.db import models
from django.utils import timezone

from . import totp


class TOTPDevice(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, verbose_name="账号", on_delete=models.CASCADE, related_name="totp_device"
    )
    secret = models.CharField("密钥", max_length=64, default=totp.generate_secret, editable=False)
    confirmed_at = models.DateTimeField("启用时间", null=True, blank=True, editable=False)
    last_step = models.BigIntegerField("最近使用的时间片", default=0, editable=False)
    last_used_at = models.DateTimeField("最近验证时间", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "二次验证设备"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.user} 的身份验证器"

    @property
    def confirmed(self) -> bool:
        return self.confirmed_at is not None

    def verify(self, code: str) -> bool:
        """校验一次性密码；同一时间片的验证码只能使用一次，防止重放。"""
        step = totp.match_step(self.secret, code)
        if step is None or step <= self.last_step:
            return False
        self.last_step = step
        self.last_used_at = timezone.now()
        if not self.confirmed:
            self.confirmed_at = self.last_used_at
        self.save(update_fields=["last_step", "last_used_at", "confirmed_at"])
        return True

    def provisioning_uri(self) -> str:
        return totp.provisioning_uri(self.secret, self.user.get_username(), settings.SITE_NAME)
