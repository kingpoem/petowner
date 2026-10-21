import re

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, SetPasswordForm
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.bookings.models import Order, Payment
from apps.care.models import Review
from apps.hospitality.models import AddonService
from apps.hospitality.services import apply_stay, price_booking
from apps.pets.models import Owner, Pet, Species
from apps.rooms.models import Room
from apps.security.forms import LoginGuardMixin, SmsCodeField, SmsVerifyMixin

PHONE_RE = re.compile(r"^1\d{10}$")
DATE_INPUT = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class BootstrapMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxSelectMultiple, forms.RadioSelect)):
                continue
            if isinstance(widget, forms.CheckboxInput):
                css = "form-check-input"
            elif isinstance(widget, forms.Select):
                css = "form-select"
            else:
                css = "form-control"
            widget.attrs["class"] = f"{widget.attrs.get('class', '')} {css}".strip()


class AddonCheckboxSelect(forms.CheckboxSelectMultiple):
    """增值服务：卡片式多选，名称 + 单价。"""

    template_name = "web/widgets/addon_select.html"
    option_template_name = "web/widgets/addon_option.html"

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        option["service"] = getattr(value, "instance", None)
        return option


class PetSelect(forms.Select):
    """宠物下拉：选项带物种，便于前端过滤不适用的增值服务。"""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        pet = getattr(value, "instance", None)
        if pet is not None:
            option["attrs"]["data-species"] = pet.species
        return option


def pet_label(pet: Pet) -> str:
    return f"{pet.name}（{pet.breed or pet.get_species_display()}）"


def clean_phone(value: str) -> str:
    value = value.strip()
    if not PHONE_RE.match(value):
        raise ValidationError("请输入 11 位手机号")
    return value


def validate_new_password(form, first: str, second: str, user=None) -> str:
    """顾客端只校验两次输入一致，不限制密码强度与格式。"""
    p1, p2 = form.cleaned_data.get(first), form.cleaned_data.get(second)
    if p1 and p2 and p1 != p2:
        raise ValidationError("两次输入的密码不一致")
    return p2


class OwnerSetPasswordForm(BootstrapMixin, SetPasswordForm):
    """邮件重置密码：不限制密码形式。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].help_text = ""

    def clean_new_password2(self):
        password1 = self.cleaned_data.get("new_password1")
        password2 = self.cleaned_data.get("new_password2")
        if password1 and password2 and password1 != password2:
            raise ValidationError("两次输入的密码不一致", code="password_mismatch")
        return password2


class OwnerPasswordChangeForm(BootstrapMixin, PasswordChangeForm):
    """登录后修改密码：不限制密码形式。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].help_text = ""

    def clean_new_password2(self):
        password1 = self.cleaned_data.get("new_password1")
        password2 = self.cleaned_data.get("new_password2")
        if password1 and password2 and password1 != password2:
            raise ValidationError("两次输入的密码不一致", code="password_mismatch")
        return password2


class RegisterForm(SmsVerifyMixin, BootstrapMixin, forms.Form):
    sms_purpose = "register"

    name = forms.CharField(label="您的称呼", max_length=50)
    phone = forms.CharField(label="手机号", max_length=11, widget=forms.TextInput(attrs={"inputmode": "tel"}))
    sms_code = SmsCodeField()
    email = forms.EmailField(label="邮箱（选填）", required=False)
    password1 = forms.CharField(label="设置密码", widget=forms.PasswordInput, strip=False)
    password2 = forms.CharField(label="确认密码", widget=forms.PasswordInput, strip=False)
    agree = forms.BooleanField(label="我已阅读并同意《服务协议》和《隐私政策》")

    def clean_phone(self):
        phone = clean_phone(self.cleaned_data["phone"])
        if get_user_model().objects.filter(username=phone).exists():
            raise ValidationError("该手机号已注册，请直接登录")
        if Owner.objects.filter(phone=phone).exists():
            raise ValidationError("该手机号已在门店登记，请联系门店为您开通线上账号")
        return phone

    def clean_password2(self):
        return validate_new_password(self, "password1", "password2")

    def save(self):
        data = self.cleaned_data
        user = get_user_model().objects.create_user(
            username=data["phone"], password=data["password1"], email=data["email"], first_name=data["name"]
        )
        Owner.objects.create(user=user, name=data["name"], phone=data["phone"], email=data["email"])
        return user


class LoginForm(LoginGuardMixin, BootstrapMixin, AuthenticationForm):
    error_messages = {
        "invalid_login": "手机号或密码不正确",
        "inactive": "该账号已停用，请联系门店",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "手机号"
        self.fields["username"].widget.attrs.update(placeholder="请输入注册手机号", inputmode="tel")


class SmsPasswordResetForm(SmsVerifyMixin, BootstrapMixin, forms.Form):
    sms_purpose = "reset"

    phone = forms.CharField(label="注册手机号", max_length=11, widget=forms.TextInput(attrs={"inputmode": "tel"}))
    sms_code = SmsCodeField()
    new_password1 = forms.CharField(label="新密码", widget=forms.PasswordInput, strip=False)
    new_password2 = forms.CharField(label="确认新密码", widget=forms.PasswordInput, strip=False)

    def clean_phone(self):
        return clean_phone(self.cleaned_data["phone"])

    def clean_new_password2(self):
        user = get_user_model().objects.filter(username=self.cleaned_data.get("phone")).first()
        return validate_new_password(self, "new_password1", "new_password2", user)

    def clean(self):
        data = super().clean()
        if not self.errors:
            self.user = get_user_model().objects.filter(username=data["phone"], is_active=True).first()
            if self.user is None:
                self.add_error("sms_code", "短信验证码错误或已过期")
        return data

    def save(self):
        self.user.set_password(self.cleaned_data["new_password1"])
        self.user.save(update_fields=["password"])
        cache.delete(f"login-failures:{self.user.username}")
        return self.user


class ProfileForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Owner
        fields = ["name", "email", "address", "emergency_contact", "emergency_phone"]


class PetForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Pet
        fields = [
            "name",
            "photo",
            "species",
            "breed",
            "gender",
            "age",
            "weight",
            "sterilized",
            "temperament",
            "health_status",
            "diet_notes",
            "deworm_expiry",
        ]
        widgets = {
            "deworm_expiry": DATE_INPUT,
            "photo": forms.FileInput(attrs={"accept": "image/*", "data-preview": "#photoPreview"}),
        }


class DateRangeMixin:
    def clean(self):
        data = super().clean()
        check_in, check_out = data.get("check_in"), data.get("check_out")
        if check_in and check_in < timezone.localdate():
            self.add_error("check_in", "入住日期不能早于今天")
        if check_in and check_out and check_out <= check_in:
            self.add_error("check_out", "离店日期必须晚于入住日期")
        return data


class SearchForm(BootstrapMixin, DateRangeMixin, forms.Form):
    species = forms.ChoiceField(label="宠物类型", choices=Species.choices)
    check_in = forms.DateField(label="入住日期", widget=DATE_INPUT)
    check_out = forms.DateField(label="离店日期", widget=DATE_INPUT)
    room_type = forms.ChoiceField(label="房型", choices=[("", "不限房型"), *Room.RoomType.choices], required=False)


class BookingForm(BootstrapMixin, forms.ModelForm):
    addons = forms.ModelMultipleChoiceField(
        label="增值服务（选填）",
        queryset=AddonService.objects.none(),
        required=False,
        widget=AddonCheckboxSelect,
    )

    class Meta:
        model = Order
        fields = ["pet", "room", "check_in", "check_out", "note"]
        widgets = {
            "pet": PetSelect,
            "check_in": DATE_INPUT,
            "check_out": DATE_INPUT,
            "note": forms.TextInput,
        }
        labels = {"note": "给护理师的留言（选填）"}

    def __init__(self, *args, owner: Owner, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner
        self.stay = None
        self.instance.source = Order.Source.ONLINE
        pets = owner.pets.all()
        self.fields["pet"].queryset = pets
        self.fields["pet"].label_from_instance = pet_label
        self.fields["pet"].empty_label = "请选择宠物"
        if not self.is_bound and "pet" not in self.initial and len(pets) == 1:
            self.initial["pet"] = pets[0].pk
        self.fields["room"].queryset = bookable_rooms()
        self.fields["room"].label_from_instance = room_label
        self.fields["room"].empty_label = "请选择房间"
        # 全部在售项都渲染；前端按宠物种隐藏不适用项，避免切宠物后选项丢失
        self.fields["addons"].queryset = AddonService.objects.filter(is_active=True)
        self.fields["addons"].label_from_instance = addon_label

    def clean(self):
        cleaned = super().clean()
        if self.errors or not cleaned.get("room"):
            return cleaned
        self.stay = price_booking(
            room=cleaned["room"],
            check_in=cleaned["check_in"],
            check_out=cleaned["check_out"],
            addon_ids=[item.pk for item in cleaned.get("addons") or []],
            owner=self.owner,
            pet=cleaned.get("pet"),
        )
        for error in self.stay.errors:
            self.add_error(None, error)
        return cleaned

    def save(self, commit=True):
        order = super().save(commit=False)
        if commit:
            apply_stay(order, self.stay)
        return order


def bookable_rooms():
    return Room.objects.filter(is_listed=True).exclude(status=Room.Status.MAINTENANCE)


def room_label(room: Room) -> str:
    return f"{room.display_name} · {room.get_pet_type_display()} · ¥{room.price.normalize():f}/晚"


def addon_label(service) -> str:
    unit = "晚" if service.billing == "night" else "次"
    return f"{service.name} · ¥{service.price}/{unit} · {service.summary}"


class RescheduleForm(BootstrapMixin, DateRangeMixin, forms.Form):
    room = forms.ModelChoiceField(label="寄养房间", queryset=Room.objects.none(), empty_label=None)
    check_in = forms.DateField(label="入住日期", widget=DATE_INPUT)
    check_out = forms.DateField(label="离店日期", widget=DATE_INPUT)

    def __init__(self, *args, order: Order, **kwargs):
        kwargs.setdefault("initial", {"room": order.room_id, "check_in": order.check_in, "check_out": order.check_out})
        super().__init__(*args, **kwargs)
        species = order.pet.species
        rooms = bookable_rooms().filter(models.Q(pet_type=Room.PetType.ANY) | models.Q(pet_type=species))
        self.fields["room"].queryset = rooms | Room.objects.filter(pk=order.room_id)
        self.fields["room"].label_from_instance = room_label

    def apply_model_errors(self, exc: ValidationError):
        if not hasattr(exc, "error_dict"):
            self.add_error(None, exc)
            return
        for field, errors in exc.message_dict.items():
            self.add_error(field if field in self.fields else None, errors)


class PayForm(forms.Form):
    method = forms.ChoiceField(
        label="支付方式",
        choices=[(Payment.Method.WECHAT, "微信支付"), (Payment.Method.ALIPAY, "支付宝")],
        initial=Payment.Method.WECHAT,
        widget=forms.RadioSelect,
    )


class CancelForm(BootstrapMixin, forms.Form):
    reason = forms.CharField(label="取消原因（选填）", max_length=200, required=False)


class ReviewForm(BootstrapMixin, forms.ModelForm):
    rating = forms.TypedChoiceField(
        label="服务评分",
        coerce=int,
        choices=[(i, f"{i} 星") for i in range(5, 0, -1)],
        widget=forms.RadioSelect,
        initial=5,
    )

    class Meta:
        model = Review
        fields = ["rating", "content", "is_public"]
        widgets = {"content": forms.Textarea(attrs={"rows": 4})}
        labels = {
            "content": "评价与建议",
            "is_public": "允许在官网展示我的评价",
        }
