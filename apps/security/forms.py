from django import forms
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError

from . import captcha, sms


def client_ip(request) -> str:
    if settings.TRUST_X_REAL_IP and request.META.get("HTTP_X_REAL_IP"):
        return request.META["HTTP_X_REAL_IP"]
    return request.META.get("REMOTE_ADDR", "")


class CaptchaField(forms.CharField):
    def __init__(self, **kwargs):
        kwargs.setdefault("label", "图形验证码")
        kwargs.setdefault("max_length", captcha.LENGTH)
        kwargs.setdefault(
            "widget",
            forms.TextInput(attrs={"autocomplete": "off", "placeholder": "右侧字符", "data-captcha-input": ""}),
        )
        super().__init__(**kwargs)


class SmsCodeField(forms.CharField):
    def __init__(self, **kwargs):
        kwargs.setdefault("label", "短信验证码")
        kwargs.setdefault("max_length", 6)
        kwargs.setdefault(
            "widget",
            forms.TextInput(attrs={"autocomplete": "one-time-code", "inputmode": "numeric", "placeholder": "6 位数字"}),
        )
        super().__init__(**kwargs)


class SmsVerifyMixin:
    """表单需包含 phone 与 sms_code 字段，并声明 sms_purpose。

    其余字段全部通过后才核验验证码（核验成功即作废），避免用户因密码不合规等问题白白浪费一条短信。
    """

    sms_purpose = ""

    def clean(self):
        data = super().clean()
        phone, code = data.get("phone"), data.get("sms_code")
        if phone and code and not self.errors and not sms.verify_code(phone, self.sms_purpose, code):
            self.add_error("sms_code", "短信验证码错误或已过期")
        return data


class SendSmsForm(forms.Form):
    phone = forms.RegexField(regex=r"^1\d{10}$", error_messages={"invalid": "请输入 11 位手机号"})
    purpose = forms.ChoiceField(choices=list(sms.PURPOSES.items()))
    captcha = forms.CharField(max_length=captcha.LENGTH)

    def __init__(self, *args, request, **kwargs):
        self.request = request
        super().__init__(*args, **kwargs)

    def clean_captcha(self):
        if not captcha.verify(self.request, self.cleaned_data["captcha"]):
            raise ValidationError("图形验证码错误或已过期，请刷新后重试")
        return self.cleaned_data["captcha"]


class LoginGuardMixin:
    """登录防爆破：同一账号连续失败 5 次锁定 15 分钟；同一 IP 失败 3 次后需输入图形验证码。"""

    MAX_FAILURES = 5
    LOCK_SECONDS = 15 * 60
    CAPTCHA_AFTER = 3

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.captcha_required = False
        if self.request is not None and (cache.get(self._ip_key) or 0) >= self.CAPTCHA_AFTER:
            self._require_captcha()

    @property
    def _ip_key(self) -> str:
        return f"login-failures-ip:{client_ip(self.request)}" if self.request is not None else ""

    def _require_captcha(self):
        self.captcha_required = True
        field = CaptchaField()
        field.widget.attrs["class"] = "form-control"
        self.fields["captcha"] = field

    def clean(self):
        user_key = f"login-failures:{self.data.get('username', '').strip()}"
        if (cache.get(user_key) or 0) >= self.MAX_FAILURES:
            raise ValidationError(f"登录失败次数过多，请 {self.LOCK_SECONDS // 60} 分钟后再试", code="throttled")
        if self.captcha_required and not captcha.verify(self.request, self.data.get("captcha", "")):
            raise ValidationError("图形验证码错误或已过期，请刷新后重试", code="captcha")
        try:
            data = super().clean()
        except ValidationError:
            for key in filter(None, (user_key, self._ip_key)):
                cache.add(key, 0, self.LOCK_SECONDS)
                cache.incr(key)
            if not self.captcha_required and self._ip_key and cache.get(self._ip_key) >= self.CAPTCHA_AFTER:
                self._require_captcha()
            raise
        cache.delete(user_key)
        return data
