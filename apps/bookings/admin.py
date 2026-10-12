from datetime import date, timedelta

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models
from django.template.response import TemplateResponse
from django.urls import path
from django.utils import timezone

from apps.care.models import ServiceRecord
from apps.pets.models import Species

from .calendar import build_calendar
from .models import Order, Payment, Waitlist, find_available_rooms, process_waitlist
from .reports import build_report, chart, export_daily, export_orders, export_xlsx


class ServiceRecordInline(admin.StackedInline):
    model = ServiceRecord
    extra = 0
    verbose_name_plural = "服务进度（喂养与护理记录）"
    fields = (("feeding_time", "staff"), "care_content", ("appetite", "health_status"), "health_note", "photo")


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    fields = ("transaction_no", "provider_trade_no", "kind", "method", "status", "amount", "created_at")
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


class ReportPeriodForm(forms.Form):
    PRESETS = {
        "7": "近 7 天",
        "30": "近 30 天",
        "90": "近 90 天",
        "365": "近 12 个月",
        "month": "本月",
        "custom": "自定义",
    }
    MAX_DAYS = 731

    preset = forms.ChoiceField(label="统计周期", choices=PRESETS.items(), required=False, initial="30")
    start = forms.DateField(label="开始日期", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(label="结束日期", required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def period(self):
        today = timezone.localdate()
        data = self.cleaned_data if self.is_bound and self.is_valid() else {}
        preset = data.get("preset") or "30"
        if preset == "custom" and data.get("start") and data.get("end"):
            start, end = sorted((data["start"], data["end"]))
            return max(start, end - timedelta(days=self.MAX_DAYS - 1)), end
        if preset == "month":
            return today.replace(day=1), today
        days = int(preset) if preset.isdigit() else 30
        return today - timedelta(days=days - 1), today


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_no",
        "store",
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
    list_filter = ("store", "status", "payment_status", "source", "room__room_type", "check_in")
    search_fields = ("order_no", "pet__code", "pet__name", "pet__owner__name", "pet__owner__phone")
    autocomplete_fields = ("pet", "room", "store")
    readonly_fields = (
        "order_no",
        "amount",
        "discount",
        "points_redeemed",
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
                    ("amount", "discount", "points_redeemed"),
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
    actions = ("mark_paid", "start_boarding", "finish_boarding", "cancel_orders", "cancel_orders_full_refund")
    change_list_template = "admin/bookings/order/change_list.html"

    @admin.display(description="主人电话")
    def owner_phone(self, obj):
        return obj.pet.owner.phone

    @admin.display(description="天数")
    def days(self, obj):
        return obj.days

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        store = getattr(request, "store", None)
        if store is not None:
            qs = qs.filter(models.Q(store=store) | models.Q(room__store=store))
        return qs

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        for key in ("room", "pet", "check_in", "check_out", "store"):
            if request.GET.get(key):
                initial[key] = request.GET[key]
        store = getattr(request, "store", None)
        if store and "store" not in initial:
            initial["store"] = store.pk
        return initial

    def get_object(self, request, object_id, from_field=None):
        obj = super().get_object(request, object_id, from_field)
        if obj is not None:
            obj._rescheduling = obj.can_reschedule
        return obj

    def save_model(self, request, obj, form, change):
        moved = change and {"room", "check_in", "check_out"} & set(form.changed_data)
        if not (moved and obj.payment_status != Order.PaymentStatus.UNPAID):
            return super().save_model(request, obj, form, change)
        target = (obj.room, obj.check_in, obj.check_out)
        obj.refresh_from_db(fields=["room", "check_in", "check_out"])
        due = obj.reschedule(*target)
        if due:
            self.message_user(request, f"改期后需向顾客补收差价 ¥{due}", messages.WARNING)

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

    @admin.action(description="前台收款（现金，含补差价）")
    def mark_paid(self, request, queryset):
        self._run_transition(request, queryset, "mark_paid", "收款")

    @admin.action(description="办理入住")
    def start_boarding(self, request, queryset):
        self._run_transition(request, queryset, "start_boarding", "办理入住")

    @admin.action(description="办理离店（完成寄养）")
    def finish_boarding(self, request, queryset):
        self._run_transition(request, queryset, "finish_boarding", "办理离店")

    @admin.action(description="取消预约（按取消政策退款）")
    def cancel_orders(self, request, queryset):
        self._run_transition(request, queryset, "cancel", "取消预约", reason="门店操作取消")

    @admin.action(description="取消预约并全额退款（门店原因）")
    def cancel_orders_full_refund(self, request, queryset):
        self._run_transition(
            request, queryset, "cancel", "取消并全额退款", reason="门店原因取消，全额退款", waive_fee=True
        )

    def get_urls(self):
        custom = [
            path(
                "available-rooms/",
                self.admin_site.admin_view(self.available_rooms_view),
                name="bookings_order_available_rooms",
            ),
            path("reports/", self.admin_site.admin_view(self.reports_view), name="bookings_order_reports"),
            path("calendar/", self.admin_site.admin_view(self.calendar_view), name="bookings_order_calendar"),
        ]
        return custom + super().get_urls()

    def reports_view(self, request):
        if not (request.user.has_perm("bookings.view_order") and request.user.has_perm("bookings.view_payment")):
            raise PermissionDenied
        form = ReportPeriodForm(request.GET or None)
        start, end = form.period()
        store = getattr(request, "store", None)
        report = build_report(start, end, store=store)
        export = request.GET.get("export")
        if export == "daily":
            return export_daily(report)
        if export == "orders":
            return export_orders(report)
        if export == "xlsx":
            return export_xlsx(report)
        context = {
            **self.admin_site.each_context(request),
            "title": "经营报表" + (f" · {store.name}" if store else ""),
            "opts": self.model._meta,
            "form": ReportPeriodForm(
                {"preset": form.data.get("preset") or "30", "start": start.isoformat(), "end": end.isoformat()}
            ),
            "report": report,
            "chart": chart(report),
            "query": request.GET.urlencode(),
            "report_store": store,
        }
        return TemplateResponse(request, "admin/bookings/order/reports.html", context)

    def calendar_view(self, request):
        if not request.user.has_perm("bookings.view_order"):
            raise PermissionDenied
        today = timezone.localdate()
        try:
            start = date.fromisoformat(request.GET.get("start") or today.isoformat())
        except ValueError:
            start = today
        try:
            nights = int(request.GET.get("nights") or 14)
        except ValueError:
            nights = 14
        store = getattr(request, "store", None)
        cal = build_calendar(start, nights, store=store)
        context = {
            **self.admin_site.each_context(request),
            "title": "房态日历",
            "opts": self.model._meta,
            "cal": cal,
            "prev": start - timedelta(days=7),
            "next": start + timedelta(days=7),
            "nights": max(7, min(nights, 31)),
            "can_add": request.user.has_perm("bookings.add_order"),
        }
        return TemplateResponse(request, "admin/bookings/order/calendar.html", context)

    def available_rooms_view(self, request):
        form = AvailableRoomForm(request.GET or None)
        rooms = None
        if form.is_valid():
            d = form.cleaned_data
            rooms = find_available_rooms(d["species"], d["check_in"], d["check_out"])
            days = (d["check_out"] - d["check_in"]).days
            rooms = [(room, room.price * days) for room in rooms]
        context = {
            **self.admin_site.each_context(request),
            "title": "可用房间查询",
            "opts": self.model._meta,
            "form": form,
            "rooms": rooms,
        }
        return TemplateResponse(request, "admin/bookings/order/available_rooms.html", context)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("transaction_no", "order", "kind", "method", "status", "amount", "provider_trade_no", "created_at")
    list_filter = ("kind", "method", "status", "created_at")
    search_fields = ("transaction_no", "provider_trade_no", "order__order_no")
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


@admin.register(Waitlist)
class WaitlistAdmin(admin.ModelAdmin):
    list_display = ("pet", "owner_phone", "room_type", "check_in", "check_out", "status", "created_at", "notified_at")
    list_filter = ("status", "room_type")
    search_fields = ("pet__name", "pet__owner__phone")
    autocomplete_fields = ("pet",)
    actions = ("run_matching",)

    @admin.display(description="主人电话")
    def owner_phone(self, obj):
        return obj.pet.owner.phone

    @admin.action(description="立即匹配空房并通知")
    def run_matching(self, request, queryset):
        count = process_waitlist()
        self.message_user(request, f"已通知 {count} 位候补顾客", messages.SUCCESS)
