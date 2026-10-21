from datetime import date, timedelta

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Case, IntegerField, Value, When
from django.template.response import TemplateResponse
from django.urls import path
from django.utils import timezone

from apps.care.models import ServiceRecord
from apps.hospitality.admin import OrderAddonInline

from .calendar import build_calendar
from .models import Order, Payment


class StayWindowFilter(admin.SimpleListFilter):
    """前台常用入住窗口，避免与顶部月份导航重复。"""

    title = "入住窗口"
    parameter_name = "stay"

    def lookups(self, request, model_admin):
        return (
            ("in_house", "当前在住"),
            ("today_in", "今日入住"),
            ("today_out", "今日离店"),
            ("upcoming", "未来预约"),
            ("active", "进行中（预约+在住）"),
        )

    def queryset(self, request, queryset):
        today = timezone.localdate()
        match self.value():
            case "in_house":
                return queryset.filter(status=Order.Status.CHECKED_IN)
            case "today_in":
                return queryset.filter(check_in=today).exclude(status=Order.Status.CANCELLED)
            case "today_out":
                return queryset.filter(check_out=today).exclude(status=Order.Status.CANCELLED)
            case "upcoming":
                return queryset.filter(status=Order.Status.PENDING, check_in__gte=today)
            case "active":
                return queryset.filter(status__in=Order.ACTIVE_STATUSES)
            case _:
                return queryset


class OrderAdminForm(forms.ModelForm):
    """入住/离店用日历选择，不用可手填的文本日期框。"""

    class Meta:
        model = Order
        fields = "__all__"
        widgets = {
            "check_in": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "check_out": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("check_in", "check_out"):
            field = self.fields.get(name)
            if field is not None:
                field.input_formats = ["%Y-%m-%d"]


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
    classes = ("collapse",)
    verbose_name_plural = "收退款流水（点击展开）"
    fields = ("transaction_no", "provider_trade_no", "kind", "method", "status", "amount", "created_at")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    form = OrderAdminForm
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
    )
    # 去掉 check_in 侧栏筛选，避免与顶部「按入住月份」重复；改用入住窗口
    list_filter = (StayWindowFilter, "status", "payment_status", "room__room_type")
    show_facets = admin.ShowFacets.NEVER
    search_fields = ("order_no", "pet__code", "pet__name", "pet__owner__name", "pet__owner__phone")
    autocomplete_fields = ("pet", "room")
    # 列头排序回退；默认运营序在 get_ordering 里加「在住优先」
    ordering = ("check_in", "-created_at")
    readonly_fields = (
        "order_no",
        "amount",
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
        ("预约信息", {"fields": ("order_no", "pet", "room", ("check_in", "check_out"), "note")}),
        (
            "费用与状态",
            {
                "fields": (
                    "amount",
                    ("payment_status", "status"),
                    "source",
                    ("cancel_reason", "cancel_fee"),
                )
            },
        ),
        ("时间记录", {"fields": ("created_at", "paid_at", "checked_in_at", "checked_out_at", "updated_at"), "classes": ("collapse",)}),
    )
    list_select_related = ("pet__owner", "room", "store")
    date_hierarchy = "check_in"
    inlines = [ServiceRecordInline, OrderAddonInline, PaymentInline]
    # 顺序即前台流程：收款 → 入住 → 离店 → 取消
    actions = ("mark_paid", "start_boarding", "finish_boarding", "cancel_orders", "cancel_orders_full_refund")
    actions_on_top = True
    actions_on_bottom = True
    change_list_template = "admin/bookings/order/change_list.html"
    exclude = ("store",)

    def get_queryset(self, request):
        # 须先注解再 order_by：父类 get_queryset 会立刻按 get_ordering 排序
        qs = self.model._default_manager.get_queryset().annotate(
            _ops_rank=Case(
                When(status=Order.Status.CHECKED_IN, then=Value(0)),
                When(status=Order.Status.PENDING, then=Value(1)),
                When(status=Order.Status.COMPLETED, then=Value(2)),
                default=Value(3),
                output_field=IntegerField(),
            )
        )
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs

    def get_ordering(self, request):
        # 未点列头时：寄养中 → 已预约 → 其他，同组内按入住日升序
        # 仅在本列表页使用 _ops_rank，避免其它页 FK 下拉按该注解字段排序报错
        if "o" in request.GET:
            return super().get_ordering(request)
        match = getattr(request, "resolver_match", None)
        on_changelist = bool(
            match and match.url_name == f"{self.opts.app_label}_{self.opts.model_name}_changelist"
        )
        if on_changelist:
            return ("_ops_rank", "check_in", "-created_at")
        return super().get_ordering(request)

    @admin.display(description="主人电话", ordering="pet__owner__phone")
    def owner_phone(self, obj):
        return obj.pet.owner.phone

    @admin.display(description="天数", ordering="check_in")
    def days(self, obj):
        return obj.days

    def has_delete_permission(self, request, obj=None):
        # 列表页禁止批量删除；详情仅允许删除「未支付且已取消」的脏数据
        if obj is None:
            return False
        return obj.status == Order.Status.CANCELLED and obj.payment_status == Order.PaymentStatus.UNPAID

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            # 新建页只保留可填项，去掉金额/状态等噪音
            return (("预约信息", {"fields": ("pet", "room", ("check_in", "check_out"), "note")}),)
        return self.fieldsets

    def get_inline_instances(self, request, obj=None):
        if obj is None:
            return [OrderAddonInline(self.model, self.admin_site)]
        return super().get_inline_instances(request, obj)

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        for key in ("room", "pet", "check_in", "check_out"):
            if request.GET.get(key):
                initial[key] = request.GET[key]
        return initial

    def get_object(self, request, object_id, from_field=None):
        obj = super().get_object(request, object_id, from_field)
        if obj is not None:
            obj._rescheduling = obj.can_reschedule
        return obj

    def save_model(self, request, obj, form, change):
        if not obj.store_id:
            from apps.stores.models import Store

            obj.store = Store.default()
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
            path("calendar/", self.admin_site.admin_view(self.calendar_view), name="bookings_order_calendar"),
        ]
        return custom + super().get_urls()

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
        cal = build_calendar(start, nights)
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


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """对账用：不进日常导航，在订单详情折叠区查看。"""

    list_display = ("transaction_no", "order", "kind", "method", "status", "amount", "provider_trade_no", "created_at")
    list_filter = ("kind", "method", "status", "created_at")
    show_facets = admin.ShowFacets.NEVER
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

    def has_module_permission(self, request):
        return False

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
