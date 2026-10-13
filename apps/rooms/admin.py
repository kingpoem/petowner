from django.contrib import admin, messages

from apps.pets.admin import thumbnail

from .models import Room


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = (
        "photo_thumb",
        "store",
        "number",
        "name",
        "room_type",
        "pet_type",
        "max_pet_size",
        "price",
        "capacity",
        "occupancy",
        "status",
        "is_listed",
    )
    list_display_links = ("photo_thumb", "number")
    list_editable = ("price", "is_listed")
    list_filter = ("store", "room_type", "pet_type", "status", "is_listed")
    search_fields = ("number", "name", "description")
    autocomplete_fields = ("store",)
    readonly_fields = ("photo_preview",)
    actions = ("set_cleaning", "set_maintenance", "restore_available")
    change_list_template = "admin/rooms/room/change_list.html"
    fieldsets = (
        (
            "基本信息",
            {"fields": ("store", "number", "name", "room_type", "pet_type", "max_pet_size", "capacity", "area")},
        ),
        ("价格与状态", {"fields": ("price", "status", "is_listed")}),
        ("官网展示", {"fields": ("photo", "photo_preview", "amenities", "description")}),
    )

    @admin.display(description="照片")
    def photo_thumb(self, obj):
        return thumbnail(obj.photo)

    @admin.display(description="预览")
    def photo_preview(self, obj):
        return thumbnail(obj.photo, 200)

    @admin.display(description="当前入住")
    def occupancy(self, obj):
        return f"{obj.current_occupancy()} / {obj.capacity}"

    @admin.action(description="设为清洁消毒")
    def set_cleaning(self, request, queryset):
        updated = queryset.update(status=Room.Status.CLEANING)
        self.message_user(request, f"已将 {updated} 个房间设为清洁消毒", messages.SUCCESS)

    @admin.action(description="设为维护停用")
    def set_maintenance(self, request, queryset):
        updated = queryset.update(status=Room.Status.MAINTENANCE)
        self.message_user(request, f"已将 {updated} 个房间设为维护停用", messages.SUCCESS)

    @admin.action(description="解除停用/清洁（按入住情况恢复空闲/已满）")
    def restore_available(self, request, queryset):
        for room in queryset.filter(status__in=Room.BLOCKED_STATUSES):
            room.status = Room.Status.AVAILABLE
            room.save(update_fields=["status"])
            room.refresh_status()
        self.message_user(request, "已恢复可售状态", messages.SUCCESS)
