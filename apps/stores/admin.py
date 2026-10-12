from django.contrib import admin, messages
from django.shortcuts import redirect

from .models import StaffStore, Store


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "phone", "is_active", "is_default", "sort")
    list_filter = ("is_active", "is_default")
    search_fields = ("name", "code", "address")
    prepopulated_fields = {"code": ("name",)}
    actions = ("switch_to_store",)

    @admin.action(description="切换后台操作到所选门店（仅选一家）")
    def switch_to_store(self, request, queryset):
        from .access import allowed_stores_for

        if queryset.count() != 1:
            self.message_user(request, "请只选择一家门店进行切换", messages.WARNING)
            return
        store = queryset.get()
        if not allowed_stores_for(request.user).filter(pk=store.pk).exists():
            self.message_user(request, "您没有该门店的操作权限", messages.ERROR)
            return
        request.session["current_store"] = store.code
        self.message_user(request, f"已切换到门店：{store.name}", messages.SUCCESS)
        return redirect("admin:index")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        from .access import allowed_stores_for

        if request.user.is_superuser:
            return qs
        return qs.filter(pk__in=allowed_stores_for(request.user))


@admin.register(StaffStore)
class StaffStoreAdmin(admin.ModelAdmin):
    list_display = ("user", "store")
    list_filter = ("store",)
    autocomplete_fields = ("user", "store")
