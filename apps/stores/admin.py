from django.contrib import admin

from .models import Store


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "phone", "is_active", "is_default", "sort")
    list_filter = ("is_active", "is_default")
    search_fields = ("name", "code", "address")
    prepopulated_fields = {"code": ("name",)}

    def has_module_permission(self, request):
        # 单店课程版：不占门店主入口，房间/订单已关联门店
        return request.user.is_superuser
