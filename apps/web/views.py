import json
from datetime import date, timedelta
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views.decorators.http import require_POST

from apps.bookings.models import Order, find_available_rooms
from apps.care.models import Review
from apps.hospitality.house import house_board
from apps.hospitality.models import StoreNotice
from apps.hospitality.pulse import weave
from apps.hospitality.services import ensure_member, preview_reschedule, price_booking
from apps.notifications.models import Notification
from apps.pets.models import Pet
from apps.rooms.models import Room
from apps.rooms.pricing import quote

from .forms import (
    BookingForm,
    CancelForm,
    LoginForm,
    PayForm,
    PetForm,
    ProfileForm,
    RegisterForm,
    RescheduleForm,
    ReviewForm,
    SearchForm,
    SmsPasswordResetForm,
)


def owner_required(view):
    """要求登录且已关联宠物主人档案；员工账号引导至管理后台。"""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        owner = getattr(request.user, "owner_profile", None)
        if owner is None:
            if request.user.is_staff:
                return redirect("admin:index")
            raise Http404
        request.owner = owner
        return view(request, *args, **kwargs)

    return wrapper


def _safe_next(request, default: str) -> str:
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return target
    return reverse(default)


def _public_reviews():
    return Review.objects.filter(is_public=True).exclude(content="").select_related("order__pet", "order__room")


# ---------- 公开页面 ----------


def _listed_rooms():
    return Room.objects.filter(is_listed=True).exclude(status=Room.Status.MAINTENANCE)


def home(request):
    rating = Review.objects.aggregate(avg=Avg("rating"), total=Count("id"))
    rooms = _listed_rooms()
    tomorrow = timezone.localdate() + timedelta(days=1)
    context = {
        "rooms": rooms[:6],
        "room_count": rooms.count(),
        "reviews": _public_reviews()[:6],
        "avg_rating": rating["avg"],
        "review_count": rating["total"],
        "search_form": SearchForm(initial={"check_in": tomorrow, "check_out": tomorrow + timedelta(days=3)}),
        "notices": StoreNotice.published()[:3],
        "board": house_board(),
    }
    return render(request, "web/home.html", context)


def room_list(request):
    form = SearchForm(request.GET or None)
    rooms = _listed_rooms()
    results, searched = None, False
    if request.GET and form.is_valid():
        searched = True
        d = form.cleaned_data
        available = find_available_rooms(
            d["species"],
            d["check_in"],
            d["check_out"],
            room_type=d["room_type"],
            listed_only=True,
        )
        results = [(room, quote(room, d["check_in"], d["check_out"])) for room in available]
    elif request.GET.get("species"):
        rooms = rooms.filter(Q(pet_type=request.GET["species"]) | Q(pet_type=Room.PetType.ANY))
    return render(
        request,
        "web/room_list.html",
        {"form": form, "rooms": rooms, "results": results, "searched": searched},
    )


def room_detail(request, pk):
    room = get_object_or_404(Room, pk=pk, is_listed=True)
    form = SearchForm(request.GET or None, initial={"species": room.pet_type if room.pet_type != "any" else "dog"})
    room_quote = available = None
    if request.GET and form.is_valid():
        d = form.cleaned_data
        room_quote = quote(room, d["check_in"], d["check_out"])
        available = room in find_available_rooms(d["species"], d["check_in"], d["check_out"], listed_only=True)
    reviews = _public_reviews().filter(order__room=room)[:4]
    return render(
        request,
        "web/room_detail.html",
        {"room": room, "form": form, "quote": room_quote, "available": available, "reviews": reviews},
    )


def page(request, name):
    templates = {
        "terms": "web/pages/terms.html",
        "privacy": "web/pages/privacy.html",
        "credits": "web/pages/credits.html",
    }
    if name not in templates:
        raise Http404
    context = {}
    if name == "credits":
        credits_file = settings.BASE_DIR / "static" / "img" / "stock" / "credits.json"
        context["credits"] = json.loads(credits_file.read_text(encoding="utf-8")) if credits_file.exists() else {}
    return render(request, templates[name], context)


# ---------- 账号 ----------


def register(request):
    if request.user.is_authenticated:
        return redirect("web:dashboard")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, "注册成功！先为您的毛孩子建立档案吧。")
        return redirect("web:pet_create")
    return render(request, "web/account/register.html", {"form": form})


class LoginView(auth_views.LoginView):
    template_name = "web/account/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def get_success_url(self):
        if self.request.user.is_staff and not hasattr(self.request.user, "owner_profile"):
            return reverse("admin:index")
        return super().get_success_url()


class BootstrapFormMixin:
    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        for field in form.fields.values():
            field.widget.attrs["class"] = "form-control"
        return form


class PasswordChangeView(BootstrapFormMixin, auth_views.PasswordChangeView):
    template_name = "web/account/password_change.html"
    success_url = reverse_lazy("web:profile")

    def dispatch(self, request, *args, **kwargs):
        request.owner = getattr(request.user, "owner_profile", None)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        messages.success(self.request, "密码已修改")
        return super().form_valid(form)


class PasswordResetView(BootstrapFormMixin, auth_views.PasswordResetView):
    template_name = "web/account/password_reset.html"
    email_template_name = "web/account/password_reset_email.txt"
    subject_template_name = "web/account/password_reset_subject.txt"
    success_url = reverse_lazy("web:password_reset_done")
    extra_email_context = {"brand": settings.SITE_NAME}


class PasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = "web/account/password_reset_status.html"
    extra_context = {
        "icon": "envelope-check",
        "heading": "请查收邮件",
        "body": "如果该邮箱已绑定账号，我们已发送重置链接，请在 3 天内完成设置。"
        "没收到？请检查垃圾邮件，或致电门店协助。",
    }


class PasswordResetConfirmView(BootstrapFormMixin, auth_views.PasswordResetConfirmView):
    template_name = "web/account/password_reset_confirm.html"
    success_url = reverse_lazy("web:password_reset_complete")


def password_reset_sms(request):
    form = SmsPasswordResetForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "密码已重置，请使用新密码登录")
        return redirect("web:login")
    return render(request, "web/account/password_reset_sms.html", {"form": form})


class PasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = "web/account/password_reset_status.html"
    extra_context = {"icon": "shield-check", "heading": "密码已重置", "body": "请使用新密码登录。", "show_login": True}


@owner_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.owner)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "个人资料已更新")
        return redirect("web:profile")
    return render(request, "web/account/profile.html", {"form": form})


# ---------- 个人中心 ----------


@owner_required
def dashboard(request):
    owner = request.owner
    orders = Order.objects.filter(pet__owner=owner).select_related("pet", "room")
    today = timezone.localdate()
    context = {
        "active_orders": orders.filter(status__in=Order.ACTIVE_STATUSES).order_by("check_in"),
        "pets": owner.pets.all(),
        "to_review": orders.filter(status=Order.Status.COMPLETED, review__isnull=True)[:3],
        "notifications": request.user.notifications.filter(is_read=False)[:5],
        "vaccine_warnings": [p for p in owner.pets.all() if not p.vaccine_valid_through(today + timedelta(days=30))],
        "membership": ensure_member(owner),
    }
    return render(request, "web/dashboard.html", context)


@owner_required
def pet_list(request):
    return render(request, "web/pets/list.html", {"pets": request.owner.pets.annotate(order_count=Count("orders"))})


@owner_required
def pet_form(request, pk=None):
    pet = get_object_or_404(Pet, pk=pk, owner=request.owner) if pk else Pet(owner=request.owner)
    form = PetForm(request.POST or None, request.FILES or None, instance=pet)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"{pet.name} 的档案已保存")
        return redirect(_safe_next(request, "web:pet_list"))
    return render(request, "web/pets/form.html", {"form": form, "pet": pet})


@owner_required
@require_POST
def pet_delete(request, pk):
    pet = get_object_or_404(Pet, pk=pk, owner=request.owner)
    if pet.orders.exists():
        messages.error(request, "该宠物已有寄养记录，不能删除")
    else:
        pet.delete()
        messages.success(request, "档案已删除")
    return redirect("web:pet_list")


# ---------- 预约与订单 ----------


@owner_required
def booking_create(request):
    if not request.owner.pets.exists():
        messages.info(request, "预约前请先添加宠物档案")
        return redirect(f"{reverse('web:pet_create')}?{urlencode({'next': request.get_full_path()})}")
    initial = {k: request.GET.get(k) for k in ("pet", "room", "check_in", "check_out") if request.GET.get(k)}
    form = BookingForm(request.POST or None, owner=request.owner, initial=initial)
    params = form.data if form.is_bound else initial
    booking_quote, stay = _stay_for(params, request.owner)
    if request.method == "POST":
        with transaction.atomic():
            room_id = form.data.get("room", "")
            if room_id.isdigit():
                list(Room.objects.select_for_update().filter(pk=room_id))
            if form.is_valid():
                try:
                    order = form.save()
                except ValidationError as exc:
                    transaction.set_rollback(True)
                    form.add_error(None, exc)
                else:
                    messages.success(request, f"预约成功，订单号 {order.order_no}，请完成支付以锁定房间")
                    return redirect("web:order_pay", order_no=order.order_no)
        if form.stay is not None:
            stay = form.stay
            booking_quote = stay.room_quote
    return render(
        request,
        "web/orders/create.html",
        {"form": form, "quote": booking_quote, "stay": stay, "weave": _company_weave(params, request.owner)},
    )


def _owner_order(request, order_no):
    return get_object_or_404(Order.objects.select_related("pet", "room"), order_no=order_no, pet__owner=request.owner)


@owner_required
def order_list(request):
    orders = Order.objects.filter(pet__owner=request.owner).select_related("pet", "room")
    status = request.GET.get("status", "")
    if status in Order.Status.values:
        orders = orders.filter(status=status)
    page_obj = Paginator(orders, 10).get_page(request.GET.get("page"))
    return render(
        request, "web/orders/list.html", {"page_obj": page_obj, "status": status, "statuses": Order.Status.choices}
    )


@owner_required
def order_detail(request, order_no):
    order = _owner_order(request, order_no)
    records = order.service_records.all()
    steps = [
        ("预约成功", order.created_at, True),
        ("完成支付", order.paid_at, order.payment_status != Order.PaymentStatus.UNPAID),
        ("办理入住", order.checked_in_at, order.checked_in_at is not None),
        ("平安离店", order.checked_out_at, order.status == Order.Status.COMPLETED),
    ]
    if order.status == Order.Status.CANCELLED:
        steps = [steps[0], ("预约已取消", order.updated_at, True)]
    paid = order.net_paid
    context = {
        "order": order,
        "records": records,
        "steps": steps,
        "payments": order.payments.order_by("created_at", "pk"),
        "paid": paid,
        "balance_due": order.balance_due,
        "cancel_form": CancelForm(),
    }
    if order.can_cancel:
        fee = order.cancellation_fee()
        context.update(cancel_fee=fee, cancel_refund=paid - fee)
    return render(request, "web/orders/detail.html", context)


@owner_required
def order_receipt(request, order_no):
    order = _owner_order(request, order_no)
    return render(
        request,
        "web/orders/receipt.html",
        {
            "order": order,
            "stay_quote": quote(order.room, order.check_in, order.check_out),
            "addons": order.addons.select_related("service"),
            "paid": order.net_paid,
        },
    )


@owner_required
def order_pay(request, order_no):
    order = _owner_order(request, order_no)
    if order.can_pay and order.pay_deadline and timezone.now() > order.pay_deadline:
        order.cancel(f"超过 {settings.PAYMENT_TIMEOUT_MINUTES} 分钟未支付，系统自动取消")
        messages.warning(request, "订单已超过支付时限并自动取消，请重新预约")
        return redirect(order)
    if not order.can_pay:
        messages.info(request, "该订单无需支付")
        return redirect(order)
    form = PayForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        from apps.payments.gateways import PaymentGatewayError
        from apps.payments.services import CheckoutError, start_checkout

        try:
            payment, session = start_checkout(order, form.cleaned_data["method"], request)
        except (CheckoutError, PaymentGatewayError) as exc:
            messages.error(request, str(exc))
            return redirect("web:order_pay", order_no=order.order_no)
        if session.mode == "form" and session.form_html:
            return HttpResponse(session.form_html)
        return redirect(session.url or reverse("payments:checkout", args=[payment.pk]))
    return render(request, "web/orders/pay.html", {"order": order, "form": form})


@owner_required
@require_POST
def order_cancel(request, order_no):
    order = _owner_order(request, order_no)
    form = CancelForm(request.POST)
    paid = order.net_paid
    try:
        order.cancel(form.data.get("reason", "")[:200])
        refund = paid - order.cancel_fee
        msg = "预约已取消" + (f"，¥{refund} 将原路退回" if refund > 0 else "")
        messages.success(request, msg + (f"，扣除违约金 ¥{order.cancel_fee}" if order.cancel_fee else ""))
    except ValidationError as exc:
        messages.error(request, "；".join(exc.messages))
    return redirect(order)


@owner_required
def order_reschedule(request, order_no):
    order = _owner_order(request, order_no)
    if not order.can_reschedule:
        messages.info(request, "该订单已不能改期，如需调整请联系门店")
        return redirect(order)
    form = RescheduleForm(request.POST or None, order=order)
    paid = order.net_paid
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            with transaction.atomic():
                due = order.reschedule(data["room"], data["check_in"], data["check_out"])
        except ValidationError as exc:
            order.refresh_from_db()
            form.apply_model_errors(exc)
        else:
            if due:
                messages.warning(request, f"改期成功，请补付差价 ¥{due}")
                return redirect("web:order_pay", order_no=order.order_no)
            refund = paid - order.net_paid
            messages.success(request, "改期成功" + (f"，差价 ¥{refund} 将原路退回" if refund > 0 else ""))
            return redirect(order)
    target = (order.room, order.check_in, order.check_out)
    if form.is_bound and form.is_valid():
        target = (form.cleaned_data["room"], form.cleaned_data["check_in"], form.cleaned_data["check_out"])
    room_quote = quote(*target)
    context = {
        "order": order,
        "form": form,
        **_quote_context(room_quote, order, preview_reschedule(order, room_quote)),
    }
    return render(request, "web/orders/reschedule.html", context)


def _quote_context(booking_quote, order=None, stay=None) -> dict:
    """费用明细片段的上下文；传入订单时附带与已付金额的差额（改期场景）。"""
    context = {"quote": booking_quote, "order": order, "stay": stay}
    payable = None
    if stay is not None:
        payable = stay.payable
    elif booking_quote is not None:
        payable = booking_quote.total
    if payable is not None:
        context["payable"] = payable
    if order is not None and payable is not None:
        diff = payable - order.net_paid
        context.update(paid=order.net_paid, top_up=max(diff, 0), refund=max(-diff, 0))
    return context


def _param_list(params, name):
    if hasattr(params, "getlist"):
        return params.getlist(name)
    value = params.get(name) if hasattr(params, "get") else None
    if not value:
        return []
    return value if isinstance(value, list) else [value]


def _stay_for(params, owner, order=None):
    booking_quote = _parse_quote(params)
    if booking_quote is None:
        return None, None
    if order is not None:
        return booking_quote, preview_reschedule(order, booking_quote)
    try:
        room = Room.objects.get(pk=params.get("room"))
        check_in = date.fromisoformat(str(params.get("check_in")))
        check_out = date.fromisoformat(str(params.get("check_out")))
        points = int(params.get("redeem_points") or 0)
    except (Room.DoesNotExist, ValueError, TypeError):
        return booking_quote, None
    pet = None
    pet_id = params.get("pet")
    if pet_id and str(pet_id).isdigit() and owner is not None:
        pet = owner.pets.filter(pk=pet_id).first()
    stay = price_booking(
        room=room,
        check_in=check_in,
        check_out=check_out,
        addon_ids=_param_list(params, "addons"),
        coupon_code=params.get("coupon_code") or "",
        redeem_points=points,
        use_member=str(params.get("use_member") or "") in {"1", "on", "true", "True"},
        owner=owner,
        pet=pet,
    )
    return booking_quote, stay


def _parse_quote(params):
    try:
        room = Room.objects.get(pk=params.get("room"))
        check_in = date.fromisoformat(params.get("check_in", ""))
        check_out = date.fromisoformat(params.get("check_out", ""))
    except (Room.DoesNotExist, ValueError, TypeError):
        return None
    if 0 < (check_out - check_in).days <= settings.MAX_BOARDING_DAYS:
        return quote(room, check_in, check_out)
    return None


@owner_required
def quote_preview(request):
    """预约/改期页面的费用明细片段，供前端在房间或日期变化时局部刷新。"""
    order = _owner_order(request, request.GET["order"]) if request.GET.get("order") else None
    booking_quote, stay = _stay_for(request.GET, request.owner, order)
    context = _quote_context(booking_quote, order, stay)
    context["weave"] = _company_weave(request.GET, request.owner)
    return render(request, "web/orders/_quote.html", context)


def _company_weave(params, owner):
    if owner is None or not hasattr(params, "get"):
        return None
    try:
        check_in = date.fromisoformat(str(params.get("check_in") or ""))
        check_out = date.fromisoformat(str(params.get("check_out") or ""))
    except ValueError:
        return None
    if not (0 < (check_out - check_in).days <= settings.MAX_BOARDING_DAYS):
        return None
    pet_id = params.get("pet")
    if not pet_id or not str(pet_id).isdigit():
        return None
    pet = owner.pets.filter(pk=int(pet_id)).first()
    if pet is None:
        return None
    company = (
        Order.objects.filter(
            status__in=Order.ACTIVE_STATUSES,
            check_in__lt=check_out,
            check_out__gt=check_in,
        )
        .exclude(pet_id=pet.pk)
        .select_related("pet")
    )
    return weave(pet.species, pet.temperament, [(row.pet.species, row.pet.temperament) for row in company])


@owner_required
def order_review(request, order_no):
    order = _owner_order(request, order_no)
    if not order.can_review:
        messages.info(request, "该订单暂不能评价")
        return redirect(order)
    form = ReviewForm(request.POST or None, instance=Review(order=order))
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "感谢您的评价！")
        return redirect(order)
    return render(request, "web/orders/review.html", {"order": order, "form": form})


# ---------- 通知 ----------


@owner_required
def notification_list(request):
    page_obj = Paginator(request.user.notifications.all(), 15).get_page(request.GET.get("page"))
    return render(request, "web/notifications.html", {"page_obj": page_obj})


@owner_required
def notification_open(request, pk):
    note = get_object_or_404(Notification, pk=pk, user=request.user)
    if not note.is_read:
        note.is_read = True
        note.save(update_fields=["is_read"])
    if note.link and url_has_allowed_host_and_scheme(note.link, allowed_hosts={request.get_host()}):
        return redirect(note.link)
    return redirect("web:notifications")


@owner_required
@require_POST
def notification_read_all(request):
    request.user.notifications.filter(is_read=False).update(is_read=True)
    return redirect("web:notifications")
