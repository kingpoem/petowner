from django.contrib import admin

from .models import (
    AddonService,
    CareTask,
    HolidayRate,
    Medication,
    OrderAddon,
    StaffMember,
    StoreNotice,
    Supply,
    SupplyMovement,
)


class OrderAddonInline(admin.TabularInline):
    model = OrderAddon
    extra = 0
    autocomplete_fields = ("service",)


@admin.register(AddonService)
class AddonServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "price", "billing", "species", "is_active", "sort")
    list_filter = ("billing", "species", "is_active")
    search_fields = ("name", "code")


@admin.register(Medication)
class MedicationAdmin(admin.ModelAdmin):
    list_display = ("pet", "drug", "dosage", "frequency", "is_active")
    list_filter = ("is_active",)
    autocomplete_fields = ("pet",)


@admin.register(StaffMember)
class StaffMemberAdmin(admin.ModelAdmin):
    list_display = ("name", "role", "phone", "skills", "is_active")
    list_filter = ("role", "is_active")
    search_fields = ("name", "phone")


@admin.register(CareTask)
class CareTaskAdmin(admin.ModelAdmin):
    list_display = ("title", "order", "staff", "due_date", "status")
    list_filter = ("status", "due_date")
    search_fields = ("title", "order__order_no", "order__pet__name")
    autocomplete_fields = ("order", "staff")


class SupplyMovementInline(admin.TabularInline):
    model = SupplyMovement
    extra = 0
    readonly_fields = ("created_at",)


@admin.register(Supply)
class SupplyAdmin(admin.ModelAdmin):
    list_display = ("name", "stock", "unit", "reorder_level", "low")
    search_fields = ("name",)
    inlines = [SupplyMovementInline]

    @admin.display(boolean=True, description="需补货")
    def low(self, obj: Supply):
        return obj.low


@admin.register(HolidayRate)
class HolidayRateAdmin(admin.ModelAdmin):
    list_display = ("day", "label", "multiplier", "is_active")
    list_filter = ("is_active",)


@admin.register(StoreNotice)
class StoreNoticeAdmin(admin.ModelAdmin):
    list_display = ("title", "pinned", "is_published", "created_at")
    list_filter = ("pinned", "is_published")
