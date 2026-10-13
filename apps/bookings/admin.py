from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.template.response import TemplateResponse
from django.urls import path

from apps.care.models import ServiceRecord
from apps.pets.models import Species

from .models import Order, Payment, find_available_rooms


class ServiceRecordInline(admin.StackedInline):
    model = ServiceRecord
    extra = 0
    verbose_name_plural = "服务进度（喂养与护理记录）"
    fields = (
        "code",
        ("feeding_time", "staff"),
        "care_content",
        ("appetite", "health_status"),
        "health_note",
        "photo",
    )
    readonly_fields = ("code",)


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    fields = ("transaction_no", "kind", "method", "status", "amount", "created_at")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class AvailableRoomForm(forms.Form):
    species = forms.ChoiceField(label="宠物类型", choices=Species.choices)
    check_in = forms.DateField(label="入住时间", widget=forms.DateInput(attrs={"type": "date"}))
    check_out = forms.DateField(label="离店时间", widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        data = super().clean()
        if data.get("check_in") and data.get("check_out") and data["check_out"] <= data["check_in"]:
            raise ValidationError("离店时间必须晚于入住时间")
        return data


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_no",
        "pet",
        "owner_phone",
        "room",
        "check_in",
        "check_out",
        "days",
        "amount",
        "payment_status",
        "status",
        "source",
    )
    list_filter = ("status", "payment_status", "source", "room__room_type", "check_in")
    search_fields = ("order_no", "pet__code", "pet__name", "pet__owner__name", "pet__owner__phone")
    autocomplete_fields = ("pet", "room", "store")
    readonly_fields = (
        "order_no",
        "amount",
        "discount",
        "payment_status",
        "status",
        "source",
        "paid_at",
        "checked_in_at",
        "checked_out_at",
        "cancel_reason",
        "cancel_fee",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        ("预约信息", {"fields": ("order_no", "store", "pet", "room", "check_in", "check_out", "note")}),
        (
            "费用与状态",
            {
                "fields": (
                    ("amount", "discount"),
                    ("payment_status", "status"),
                    "source",
                    ("cancel_reason", "cancel_fee"),
                )
            },
        ),
        ("时间记录", {"fields": ("created_at", "paid_at", "checked_in_at", "checked_out_at", "updated_at")}),
    )
    list_select_related = ("pet__owner", "room", "store")
    date_hierarchy = "check_in"
    inlines = [ServiceRecordInline, PaymentInline]
    actions = ("mark_paid", "start_boarding", "finish_boarding", "cancel_orders")
    change_list_template = "admin/bookings/order/change_list.html"

    @admin.display(description="主人电话")
    def owner_phone(self, obj):
        return obj.pet.owner.phone

    @admin.display(description="天数")
    def days(self, obj):
        return obj.days

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        for key in ("room", "pet", "check_in", "check_out", "store"):
            if request.GET.get(key):
                initial[key] = request.GET[key]
        return initial

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if change and {"room", "check_in", "check_out"} & set(form.changed_data):
            obj._sync_payment_status()
            Order.objects.filter(pk=obj.pk).update(payment_status=obj.payment_status)
            if obj.can_pay:
                self.message_user(request, f"订单已修改，顾客仍需支付 ¥{obj.balance_due}", messages.WARNING)
            else:
                self.message_user(request, "订单房间/日期已更新，金额已重算", messages.SUCCESS)

    def _run_transition(self, request, queryset, method: str, label: str, **kwargs):
        ok, failed = 0, []
        for order in queryset:
            try:
                getattr(order, method)(**kwargs)
                ok += 1
            except ValidationError as exc:
                failed.append(f"{order}: {'；'.join(exc.messages)}")
        if ok:
            self.message_user(request, f"{label}成功 {ok} 单", messages.SUCCESS)
        for msg in failed:
            self.message_user(request, msg, messages.ERROR)

    @admin.action(description="一键收款（标记已付）")
    def mark_paid(self, request, queryset):
        self._run_transition(request, queryset, "mark_paid", "收款")

    @admin.action(description="办理入住")
    def start_boarding(self, request, queryset):
        self._run_transition(request, queryset, "start_boarding", "办理入住")

    @admin.action(description="办理离店（完成寄养）")
    def finish_boarding(self, request, queryset):
        self._run_transition(request, queryset, "finish_boarding", "办理离店")

    @admin.action(description="取消预约")
    def cancel_orders(self, request, queryset):
        self._run_transition(request, queryset, "cancel", "取消预约", reason="门店操作取消")

    def get_urls(self):
        custom = [
            path(
                "available-rooms/",
                self.admin_site.admin_view(self.available_rooms_view),
                name="bookings_order_available_rooms",
            ),
        ]
        return custom + super().get_urls()

    def available_rooms_view(self, request):
        if not request.user.has_perm("bookings.view_order"):
            raise PermissionDenied
        form = AvailableRoomForm(request.GET or None)
        rooms = None
        if form.is_valid():
            d = form.cleaned_data
            rooms = find_available_rooms(d["species"], d["check_in"], d["check_out"])
            days = (d["check_out"] - d["check_in"]).days
            rooms = [(room, room.price * days) for room in rooms]
        context = {
            **self.admin_site.each_context(request),
            "title": "查空房开单",
            "opts": self.model._meta,
            "form": form,
            "rooms": rooms,
        }
        return TemplateResponse(request, "admin/bookings/order/available_rooms.html", context)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("transaction_no", "order", "kind", "method", "status", "amount", "created_at")
    list_filter = ("kind", "method", "status", "created_at")
    search_fields = ("transaction_no", "order__order_no")
    readonly_fields = (
        "transaction_no",
        "provider_trade_no",
        "order",
        "kind",
        "method",
        "status",
        "amount",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
