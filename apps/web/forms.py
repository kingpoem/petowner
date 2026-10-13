import re

from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.bookings.models import Order
from apps.care.models import Review
from apps.pets.models import Owner, Pet, Species
from apps.rooms.models import Room
from apps.stores.staff import create_store_user, ensure_store_groups

PHONE_RE = re.compile(r"^1\d{10}$")
DATE_INPUT = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")

ROLE_CUSTOMER = "customer"
ROLE_STORE = "store"
ROLE_CHOICES = (
    (ROLE_CUSTOMER, "顾客"),
    (ROLE_STORE, "门店"),
)


class BootstrapMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                css = "form-check-input"
            elif isinstance(widget, forms.RadioSelect):
                continue
            elif isinstance(widget, forms.Select):
                css = "form-select"
            else:
                css = "form-control"
            widget.attrs["class"] = f"{widget.attrs.get('class', '')} {css}".strip()


def pet_label(pet: Pet) -> str:
    return f"{pet.name}（{pet.breed or pet.get_species_display()}）"


def clean_phone(value: str) -> str:
    value = value.strip()
    if not PHONE_RE.match(value):
        raise ValidationError("请输入 11 位手机号")
    return value


def validate_new_password(form, first: str, second: str, user=None) -> str:
    p1, p2 = form.cleaned_data.get(first), form.cleaned_data.get(second)
    if p1 and p2 and p1 != p2:
        raise ValidationError("两次输入的密码不一致")
    if p1:
        try:
            password_validation.validate_password(p1, user)
        except ValidationError as exc:
            form.add_error(first, exc)
    return p2


class RegisterForm(BootstrapMixin, forms.Form):
    role = forms.ChoiceField(
        label="账号类型",
        choices=ROLE_CHOICES,
        initial=ROLE_CUSTOMER,
        widget=forms.RadioSelect,
    )
    name = forms.CharField(label="您的称呼", max_length=50)
    phone = forms.CharField(label="手机号", max_length=11, widget=forms.TextInput(attrs={"inputmode": "tel"}))
    email = forms.EmailField(label="邮箱（选填）", required=False)
    password1 = forms.CharField(label="设置密码", widget=forms.PasswordInput, strip=False)
    password2 = forms.CharField(label="确认密码", widget=forms.PasswordInput, strip=False)
    agree = forms.BooleanField(label="我已阅读并同意《服务协议》和《隐私政策》")

    def clean_phone(self):
        phone = clean_phone(self.cleaned_data["phone"])
        if get_user_model().objects.filter(username=phone).exists():
            raise ValidationError("该手机号已注册，请直接登录")
        role = self.data.get("role", ROLE_CUSTOMER)
        if role == ROLE_CUSTOMER and Owner.objects.filter(phone=phone).exists():
            raise ValidationError("该手机号已在门店登记，请联系门店为您开通线上账号")
        return phone

    def clean_password2(self):
        return validate_new_password(self, "password1", "password2")

    def save(self):
        data = self.cleaned_data
        User = get_user_model()
        if data["role"] == ROLE_STORE:
            ensure_store_groups()
            return create_store_user(
                data["phone"],
                data["password1"],
                name=data["name"],
                email=data["email"],
                role="front",
            )
        user = User.objects.create_user(
            username=data["phone"], password=data["password1"], email=data["email"], first_name=data["name"]
        )
        Owner.objects.create(user=user, name=data["name"], phone=data["phone"], email=data["email"])
        return user


class LoginForm(BootstrapMixin, AuthenticationForm):
    role = forms.ChoiceField(
        label="登录身份",
        choices=ROLE_CHOICES,
        initial=ROLE_CUSTOMER,
        widget=forms.RadioSelect,
    )
    error_messages = {
        "invalid_login": "账号或密码不正确",
        "inactive": "该账号已停用，请联系门店",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "账号"
        self.fields["username"].widget.attrs.update(placeholder="手机号或门店账号", inputmode="tel")
        # 把角色选项排到最前
        self.order_fields(["role", "username", "password"])

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        role = self.cleaned_data.get("role", ROLE_CUSTOMER)
        has_owner = hasattr(user, "owner_profile")
        if role == ROLE_STORE:
            if not user.is_staff:
                raise ValidationError("该账号不是门店账号，请改选「顾客」登录", code="invalid_login")
        elif not has_owner:
            if user.is_staff:
                raise ValidationError("该账号是门店账号，请改选「门店」登录", code="invalid_login")
            raise ValidationError("该账号未开通顾客档案，请重新注册", code="invalid_login")


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
            "allergies",
            "vaccine_expiry",
            "deworm_expiry",
        ]
        widgets = {
            "vaccine_expiry": DATE_INPUT,
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
    species = forms.ChoiceField(
        label="宠物类型",
        choices=[("", "请选择宠物类型"), *Species.choices],
    )
    check_in = forms.DateField(label="入住日期", widget=DATE_INPUT)
    check_out = forms.DateField(label="离店日期", widget=DATE_INPUT)
    room_type = forms.ChoiceField(label="房型", choices=[("", "不限房型"), *Room.RoomType.choices], required=False)


class BookingForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Order
        fields = ["pet", "room", "check_in", "check_out", "note"]
        widgets = {"check_in": DATE_INPUT, "check_out": DATE_INPUT, "note": forms.TextInput}
        labels = {"note": "给护理师的留言（选填）"}

    def __init__(self, *args, owner: Owner, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner
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


def bookable_rooms():
    return Room.objects.filter(is_listed=True).exclude(status__in=Room.BLOCKED_STATUSES)


def room_label(room: Room) -> str:
    return f"{room.display_name} · {room.get_pet_type_display()} · ¥{room.price.normalize():f}/晚"


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
        fields = ["rating", "content", "feedback", "is_public"]
        widgets = {"content": forms.Textarea(attrs={"rows": 4}), "feedback": forms.Textarea(attrs={"rows": 3})}
        labels = {
            "content": "说说这次寄养体验",
            "feedback": "给我们的建议（仅门店可见）",
            "is_public": "允许在官网展示我的评价",
        }
