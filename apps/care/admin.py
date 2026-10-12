from django.contrib import admin

from apps.pets.admin import thumbnail

from .models import Review, ServiceRecord


@admin.register(ServiceRecord)
class ServiceRecordAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "photo_thumb",
        "order",
        "pet_code",
        "pet_name",
        "staff",
        "feeding_time",
        "appetite",
        "health_status",
    )
    list_filter = ("health_status", "appetite", "feeding_time")
    search_fields = ("order__order_no", "order__pet__code", "order__pet__name", "staff")
    autocomplete_fields = ("order",)
    list_select_related = ("order__pet",)

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
    list_display = ("order", "rating", "content", "feedback", "has_reply", "is_public", "created_at")
    list_filter = ("rating", "is_public")
    list_editable = ("is_public",)
    search_fields = ("order__order_no", "content", "feedback")
    autocomplete_fields = ("order",)

    @admin.display(description="已回复", boolean=True)
    def has_reply(self, obj):
        return bool(obj.reply)
