from urllib.parse import quote

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse

from .models import TOTPDevice
from .views import VERIFIED_SESSION_KEY


class TwoFactorMiddleware:
    """员工访问后台与工作台时，已绑定身份验证器的账号必须先完成动态码验证。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.is_staff and self._protected(request.path):
            if response := self._enforce(request):
                return response
        return self.get_response(request)

    @staticmethod
    def _protected(path: str) -> bool:
        exempt = (reverse("security:2fa_setup"), reverse("admin:logout"), reverse("admin:login"))
        if path.startswith(exempt):
            return False
        return path.startswith((reverse("admin:index"), *settings.STAFF_2FA_PATHS))

    @staticmethod
    def _enforce(request):
        device = TOTPDevice.objects.filter(user=request.user).only("confirmed_at").first()
        if device is not None and device.confirmed:
            if request.session.get(VERIFIED_SESSION_KEY) != request.user.pk:
                return redirect(f"{reverse('security:2fa_verify')}?next={quote(request.get_full_path())}")
        elif settings.ADMIN_REQUIRE_2FA:
            return redirect("security:2fa_setup")
        return None


class PermissionsPolicyMiddleware:
    """限制浏览器能力：仅允许本站调用摄像头（护理师拍照上传），其余敏感能力全部禁用。"""

    POLICY = "camera=(self), microphone=(), geolocation=(), payment=(), usb=()"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Permissions-Policy", self.POLICY)
        return response
