import segno
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model, logout
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from apps.pets.models import Owner

from . import captcha, sms
from .forms import SendSmsForm, client_ip
from .models import TOTPDevice

VERIFIED_SESSION_KEY = "2fa_verified_user"
OTP_MAX_FAILURES = 5
OTP_LOCK_SECONDS = 15 * 60


@never_cache
def captcha_image(request):
    return HttpResponse(captcha.render_png(captcha.issue(request)), content_type="image/png")


@require_POST
def send_sms_code(request):
    form = SendSmsForm(request.POST, request=request)
    if not form.is_valid():
        field, errors = next(iter(form.errors.items()))
        return JsonResponse({"ok": False, "field": field, "message": errors[0]}, status=400)
    phone, purpose = form.cleaned_data["phone"], form.cleaned_data["purpose"]
    registered = get_user_model().objects.filter(username=phone).exists()
    if purpose == "register" and (registered or Owner.objects.filter(phone=phone).exists()):
        return JsonResponse({"ok": False, "field": "phone", "message": "该手机号已注册或已在门店登记"}, status=400)
    masked = f"{phone[:3]}****{phone[-4:]}"
    payload = {"ok": True, "message": f"验证码已发送至 {masked}，5 分钟内有效", "cooldown": sms.RESEND_SECONDS}
    if purpose == "reset" and not registered:
        # 找回密码不暴露手机号是否注册，响应与成功发送一致
        return JsonResponse(payload)
    try:
        code = sms.issue_code(phone, purpose, client_ip(request))
    except sms.SmsError as exc:
        return JsonResponse({"ok": False, "message": str(exc)}, status=429)
    if settings.DEBUG and settings.SMS_BACKEND == "console":
        payload["debug_code"] = code
    return JsonResponse(payload)


# ---------- 后台二次验证 ----------


def _safe_next(request) -> str:
    target = request.POST.get("next") or request.GET.get("next") or ""
    if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return target
    return reverse("admin:index")


def _verify_otp(request, device: TOTPDevice) -> bool:
    """校验验证码并统计失败次数；超限时返回 False 且由调用方处理。"""
    key = f"otp-failures:{request.user.pk}"
    if (cache.get(key) or 0) >= OTP_MAX_FAILURES:
        return False
    if device.verify(request.POST.get("code", "")):
        cache.delete(key)
        request.session[VERIFIED_SESSION_KEY] = request.user.pk
        return True
    cache.add(key, 0, OTP_LOCK_SECONDS)
    cache.incr(key)
    return False


def _otp_locked(request) -> bool:
    return (cache.get(f"otp-failures:{request.user.pk}") or 0) >= OTP_MAX_FAILURES


@never_cache
@staff_member_required
def two_factor_setup(request):
    device, _ = TOTPDevice.objects.get_or_create(user=request.user)
    if device.confirmed and request.session.get(VERIFIED_SESSION_KEY) != request.user.pk:
        return redirect(f"{reverse('security:2fa_verify')}?next={request.path}")
    error = ""
    if request.method == "POST" and not device.confirmed:
        if _verify_otp(request, device):
            messages.success(request, "二次验证已启用，今后登录后台需输入身份验证器中的 6 位动态码")
            return redirect("admin:index")
        error = "操作过于频繁，请稍后再试" if _otp_locked(request) else "动态码不正确，请确认手机时间准确后重试"
    context = {
        **admin.site.each_context(request),
        "title": "二次验证（身份验证器）",
        "device": device,
        "error": error,
        "required": settings.ADMIN_REQUIRE_2FA,
        "secret_groups": [device.secret[i : i + 4] for i in range(0, len(device.secret), 4)],
        "qr_svg": None if device.confirmed else segno.make(device.provisioning_uri(), error="m").svg_inline(scale=4),
    }
    return render(request, "security/two_factor_setup.html", context)


@never_cache
@staff_member_required
@require_POST
def two_factor_disable(request):
    device = TOTPDevice.objects.filter(user=request.user, confirmed_at__isnull=False).first()
    if device is None:
        return redirect("security:2fa_setup")
    if not _verify_otp(request, device):
        messages.error(request, "动态码不正确，二次验证未关闭")
        return redirect("security:2fa_setup")
    device.delete()
    request.session.pop(VERIFIED_SESSION_KEY, None)
    messages.warning(request, "已关闭二次验证")
    return redirect("security:2fa_setup" if settings.ADMIN_REQUIRE_2FA else "admin:index")


@never_cache
def two_factor_verify(request):
    if not (request.user.is_authenticated and request.user.is_staff):
        return redirect("admin:login")
    device = TOTPDevice.objects.filter(user=request.user, confirmed_at__isnull=False).first()
    if device is None or request.session.get(VERIFIED_SESSION_KEY) == request.user.pk:
        return redirect(_safe_next(request))
    error = ""
    if request.method == "POST":
        if _verify_otp(request, device):
            return redirect(_safe_next(request))
        if _otp_locked(request):
            logout(request)
            messages.error(request, "动态码错误次数过多，请 15 分钟后重新登录")
            return redirect("admin:login")
        error = "动态码不正确，请重试"
    context = {**admin.site.each_context(request), "title": "登录验证", "error": error, "next": _safe_next(request)}
    return render(request, "security/two_factor_verify.html", context)
