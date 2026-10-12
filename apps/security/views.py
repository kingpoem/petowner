from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from apps.pets.models import Owner

from . import captcha, sms
from .forms import SendSmsForm, client_ip


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
