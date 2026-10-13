from django.contrib import admin
from django.db.models import Q

from apps.pets.admin import thumbnail

from .models import Review, ServiceRecord


class UnrepliedFilter(admin.SimpleListFilter):
    title = "回复状态"
    parameter_name = "replied"

    def lookups(self, request, model_admin):
        return (("no", "待回复"), ("yes", "已回复"))

    def queryset(self, request, queryset):
        if self.value() == "no":
            return queryset.filter(Q(reply="") | Q(reply__isnull=True))
        if self.value() == "yes":
            return queryset.exclude(Q(reply="") | Q(reply__isnull=True))
        return queryset


@admin.register(ServiceRecord)
class ServiceRecordAdmin(admin.ModelAdmin):
    """日常服务反馈：喂养、护理与健康观察更新。"""

    list_display = (
        "code",
        "photo_thumb",
        "order",
        "pet_code",
        "pet_name",
        "staff",
        "feeding_time",
        "appetite",
        "health_status",
    )
    list_filter = ("feeding_time", "health_status")
    search_fields = (
        "code",
        "order__order_no",
        "order__pet__code",
        "order__pet__name",
        "order__pet__owner__name",
        "order__pet__owner__phone",
        "staff",
        "health_status",
        "appetite",
        "care_content",
    )
    autocomplete_fields = ("order",)
    list_select_related = ("order__pet", "order__pet__owner")
    readonly_fields = ("code",)
    date_hierarchy = "feeding_time"
    ordering = ("-feeding_time",)
    change_list_template = "admin/care/servicerecord/change_list.html"
    fieldsets = (
        ("关联订单", {"fields": ("order", "code")}),
        (
            "日常服务反馈",
            {
                "fields": (
                    ("feeding_time", "staff"),
                    "care_content",
                    ("appetite", "health_status"),
                    "health_note",
                    "photo",
                )
            },
        ),
    )

    @admin.display(description="照片")
    def photo_thumb(self, obj):
        return thumbnail(obj.photo)

    @admin.display(description="宠物编号")
    def pet_code(self, obj):
        return obj.pet.code

    @admin.display(description="宠物名称")
    def pet_name(self, obj):
        return obj.pet.name


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    """顾客评价回复操作。"""

    list_display = ("order", "rating", "content_short", "feedback_short", "has_reply", "is_public", "created_at")
    list_filter = (UnrepliedFilter, "rating", "is_public")
    list_editable = ("is_public",)
    search_fields = ("order__order_no", "order__pet__name", "order__pet__owner__name", "content", "feedback", "reply")
    autocomplete_fields = ("order",)
    readonly_fields = ("order", "rating", "content", "feedback", "created_at")
    ordering = ("-created_at",)
    change_list_template = "admin/care/review/change_list.html"
    fieldsets = (
        ("顾客评价（只读）", {"fields": ("order", "rating", "content", "feedback", "created_at", "is_public")}),
        ("门店回复", {"fields": ("reply",), "description": "填写机构回复后保存，顾客可在官网评价板块看到。"}),
    )

    @admin.display(description="评价内容")
    def content_short(self, obj):
        return (obj.content or "—")[:36]

    @admin.display(description="意见反馈")
    def feedback_short(self, obj):
        return (obj.feedback or "—")[:24]

    @admin.display(description="已回复", boolean=True)
    def has_reply(self, obj):
        return bool(obj.reply)

    def has_add_permission(self, request):
        return False
