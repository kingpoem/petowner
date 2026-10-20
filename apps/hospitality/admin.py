from django.contrib import admin

from .models import (
    AddonService,
    CareTask,
    Coupon,
    HolidayRate,
    Medication,
    MemberAccount,
    OrderAddon,
    PointLedger,
    StaffMember,
    StoreNotice,
    Supply,
    SupplyMovement,
    VaccineRecord,
    WaitlistEntry,
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


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "kind", "value", "min_spend", "used_count", "usage_limit", "is_active")
    list_filter = ("kind", "is_active")
    search_fields = ("code", "name")


class PointLedgerInline(admin.TabularInline):
    model = PointLedger
    extra = 0
    readonly_fields = ("order", "delta", "reason", "created_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(MemberAccount)
class MemberAccountAdmin(admin.ModelAdmin):
    list_display = ("owner", "tier_name", "points", "lifetime_points", "created_at")
    search_fields = ("owner__name", "owner__phone")
    readonly_fields = ("tier_name",)
    inlines = [PointLedgerInline]


@admin.register(VaccineRecord)
class VaccineRecordAdmin(admin.ModelAdmin):
    list_display = ("pet", "name", "injected_on", "expires_on", "clinic")
    search_fields = ("pet__name", "pet__code", "name")
    autocomplete_fields = ("pet",)


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


@admin.register(WaitlistEntry)
class WaitlistEntryAdmin(admin.ModelAdmin):
    list_display = ("pet", "owner", "check_in", "check_out", "room_type", "status", "created_at")
    list_filter = ("status", "room_type")
    search_fields = ("pet__name", "owner__name", "owner__phone")


@admin.register(HolidayRate)
class HolidayRateAdmin(admin.ModelAdmin):
    list_display = ("day", "label", "multiplier", "is_active")
    list_filter = ("is_active",)


@admin.register(StoreNotice)
class StoreNoticeAdmin(admin.ModelAdmin):
    list_display = ("title", "pinned", "is_published", "created_at")
    list_filter = ("pinned", "is_published")
