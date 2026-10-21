from django.contrib import admin

from .models import Store


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    """单店数据仍供订单/房间自动完成引用，但不在侧栏与首页展示「门店管理」。"""

    list_display = ("name", "code", "phone", "is_active", "is_default", "sort")
    search_fields = ("name", "code", "address")

    def has_module_permission(self, request):
        return False
