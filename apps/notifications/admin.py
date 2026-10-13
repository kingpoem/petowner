from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "level", "is_read", "created_at")
    list_filter = ("level", "is_read")
    search_fields = ("title", "body", "user__username")
    autocomplete_fields = ("user",)

    def has_module_permission(self, request):
        return False
