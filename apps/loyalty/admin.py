from django.contrib import admin

from .models import Coupon, CouponRedemption, PointLedger


@admin.register(PointLedger)
class PointLedgerAdmin(admin.ModelAdmin):
    list_display = ("owner", "kind", "points", "balance", "note", "created_at")
    list_filter = ("kind",)
    search_fields = ("owner__name", "owner__phone", "note")
    autocomplete_fields = ("owner", "order")
    readonly_fields = ("owner", "kind", "points", "balance", "note", "order", "created_at")

    def has_add_permission(self, request):
        return False


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "kind",
        "value",
        "min_amount",
        "store",
        "valid_from",
        "valid_until",
        "used_count",
        "is_active",
    )
    list_filter = ("kind", "is_active", "store")
    search_fields = ("code", "name")
    autocomplete_fields = ("store",)


@admin.register(CouponRedemption)
class CouponRedemptionAdmin(admin.ModelAdmin):
    list_display = ("coupon", "owner", "order", "discount", "created_at")
    search_fields = ("coupon__code", "owner__phone", "order__order_no")
    readonly_fields = ("coupon", "owner", "order", "discount", "created_at")

    def has_add_permission(self, request):
        return False
