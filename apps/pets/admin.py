from django.contrib import admin
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
    fields = ("code", "name", "species", "breed", "age", "weight", "deworm_expiry")
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
    list_display = ("name", "phone", "pet_count")
    search_fields = ("name", "phone")
    readonly_fields = ("created_at",)
    fields = ("name", "phone", "email", "address", "emergency_contact", "emergency_phone", "created_at")
    inlines = [PetInline]

    @admin.display(description="宠物数量")
    def pet_count(self, obj):
        return obj.pets.count()


@admin.register(Pet)
class PetAdmin(admin.ModelAdmin):
    list_display = (
        "photo_thumb",
        "code",
        "name",
        "species",
        "breed",
        "temperament",
        "owner_name",
        "owner_phone",
    )
    list_display_links = ("photo_thumb", "code", "name")
    list_filter = ("species", "temperament")
    # 供订单等页的 autocomplete 使用；列表页搜索框已在全局 change_list 中隐藏
    search_fields = ("code", "name", "breed", "owner__name", "owner__phone")
    show_facets = admin.ShowFacets.NEVER
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
        ("健康", {"fields": ("health_status", "deworm_expiry", "diet_notes")}),
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
