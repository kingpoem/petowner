from django.contrib import admin

from .models import AddonService, OrderAddon


class OrderAddonInline(admin.TabularInline):
    model = OrderAddon
    extra = 0
    autocomplete_fields = ("service",)


@admin.register(AddonService)
class AddonServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "price", "billing", "species", "is_active", "sort")
    list_filter = ("billing", "species", "is_active")
    show_facets = admin.ShowFacets.NEVER
    list_editable = ("is_active", "sort")
    search_fields = ("name", "code")
