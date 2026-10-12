from django.contrib import admin

from .models import ApiToken


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "key", "is_active", "last_used_at", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "user__username", "key")
    readonly_fields = ("key", "last_used_at", "created_at")
    autocomplete_fields = ("user",)
