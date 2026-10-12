from django.contrib import admin

from .models import Invoice


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("receipt_no", "order", "owner", "title", "amount", "status", "created_at")
    list_filter = ("status", "kind")
    search_fields = ("receipt_no", "order__order_no", "title", "owner__phone")
    readonly_fields = ("receipt_no", "amount", "pdf", "created_at", "issued_at")
    autocomplete_fields = ("order", "owner")
