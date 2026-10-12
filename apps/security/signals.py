from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .views import VERIFIED_SESSION_KEY


@receiver(user_logged_in)
def reset_two_factor_state(sender, request, user, **kwargs):
    """每次密码登录都要重新完成二次验证（同一账号重新登录时 session 数据会被保留）。"""
    if request is not None and hasattr(request, "session"):
        request.session.pop(VERIFIED_SESSION_KEY, None)
