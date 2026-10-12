import secrets

from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.utils.html import format_html

from apps.bookings.models import Order
from apps.images import thumbnail_url

from .models import Owner, Pet


def thumbnail(file, size=48):
    if not file:
        return "—"
    return format_html(
        '<a href="{}" target="_blank" rel="noopener">'
        '<img src="{}" alt="" class="admin-thumb" width="{}" height="{}"></a>',
        file.url,
        thumbnail_url(file, 160 if size <= 80 else 480),
        size,
        size,
    )


class PetInline(admin.TabularInline):
    model = Pet
    extra = 0
    fields = ("code", "name", "species", "breed", "age", "weight", "vaccine_expiry")
    readonly_fields = ("code",)
    show_change_link = True


class OrderHistoryInline(admin.TabularInline):
    model = Order
    extra = 0
    verbose_name_plural = "历史寄养记录"
    fields = ("order_no", "room", "check_in", "check_out", "amount", "payment_status", "status")
    readonly_fields = fields
    show_change_link = True
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Owner)
class OwnerAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "email", "points", "home_store", "pet_count", "has_account", "created_at")
    search_fields = ("name", "phone")
    list_filter = ("home_store",)
    autocomplete_fields = ("home_store",)
    readonly_fields = ("user", "points", "created_at")
    inlines = [PetInline]
    actions = ("create_account",)

    @admin.display(description="宠物数量")
    def pet_count(self, obj):
        return obj.pets.count()

    @admin.display(description="线上账号", boolean=True)
    def has_account(self, obj):
        return obj.user_id is not None

    @admin.action(description="开通线上账号（生成初始密码）")
    def create_account(self, request, queryset):
        User = get_user_model()
        for owner in queryset.filter(user__isnull=True):
            if User.objects.filter(username=owner.phone).exists():
                self.message_user(request, f"{owner.name}：手机号已被其他账号占用", messages.ERROR)
                continue
            password = secrets.token_urlsafe(6)
            owner.user = User.objects.create_user(
                username=owner.phone, password=password, email=owner.email, first_name=owner.name
            )
            owner.save(update_fields=["user"])
            self.message_user(
                request,
                f"{owner.name}：账号 {owner.phone}，初始密码 {password}（请告知顾客登录后修改）",
                messages.SUCCESS,
            )


@admin.register(Pet)
class PetAdmin(admin.ModelAdmin):
    list_display = (
        "photo_thumb",
        "code",
        "name",
        "species",
        "breed",
        "age",
        "weight",
        "temperament",
        "vaccine_expiry",
        "owner_name",
        "owner_phone",
    )
    list_display_links = ("photo_thumb", "code", "name")
    list_filter = ("species", "gender", "temperament", "sterilized")
    search_fields = ("code", "name", "breed", "owner__name", "owner__phone")
    autocomplete_fields = ("owner",)
    readonly_fields = ("code", "created_at", "photo_preview")
    list_select_related = ("owner",)
    inlines = [OrderHistoryInline]
    fieldsets = (
        (
            "基本信息",
            {"fields": ("code", "owner", "name", "photo", "photo_preview", "species", "breed", "gender", "age")},
        ),
        ("体型与性格", {"fields": ("weight", "sterilized", "temperament")}),
        ("健康", {"fields": ("health_status", "vaccine_expiry", "deworm_expiry", "diet_notes", "allergies")}),
        (None, {"fields": ("created_at",)}),
    )

    @admin.display(description="照片")
    def photo_thumb(self, obj):
        return thumbnail(obj.photo)

    @admin.display(description="预览")
    def photo_preview(self, obj):
        return thumbnail(obj.photo, 160)

    @admin.display(description="主人姓名", ordering="owner__name")
    def owner_name(self, obj):
        return obj.owner.name

    @admin.display(description="联系方式")
    def owner_phone(self, obj):
        return obj.owner.phone
