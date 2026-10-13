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
from apps.pets.models import Pet
from apps.rooms.models import Room
from apps.rooms.pricing import quote

from .forms import (
    BookingForm,
    CancelForm,
    LoginForm,
    PetForm,
    ProfileForm,
    RegisterForm,
    ReviewForm,
    SearchForm,
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
    return Room.objects.filter(is_listed=True).exclude(status__in=Room.BLOCKED_STATUSES)


def home(request):
    rating = Review.objects.aggregate(avg=Avg("rating"), total=Count("id"))
    rooms = _listed_rooms()
    context = {
        "rooms": rooms[:6],
        "room_count": rooms.count(),
        "reviews": _public_reviews()[:6],
        "avg_rating": rating["avg"],
        "review_count": rating["total"],
    }
    return render(request, "web/home.html", context)


def room_list(request):
    tomorrow = timezone.localdate() + timedelta(days=1)
    has_dates = bool(request.GET.get("check_in") and request.GET.get("check_out"))
    form = SearchForm(
        request.GET if has_dates else None,
        initial={"check_in": tomorrow, "check_out": tomorrow + timedelta(days=3)},
    )
    rooms = _listed_rooms()
    results, searched = None, False
    if has_dates and form.is_valid():
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
    elif not searched:
        if request.GET.get("species"):
            rooms = rooms.filter(Q(pet_type=request.GET["species"]) | Q(pet_type=Room.PetType.ANY))
        if request.GET.get("room_type"):
            rooms = rooms.filter(room_type=request.GET["room_type"])
    return render(
        request,
        "web/room_list.html",
        {
            "form": form,
            "rooms": rooms,
            "results": results,
            "searched": searched,
            "room_type_guides": [{"key": key, **info} for key, info in Room.ROOM_TYPE_GUIDES.items()],
        },
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
        "faq": "web/pages/faq.html",
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
        if request.user.is_staff and not hasattr(request.user, "owner_profile"):
            return redirect("admin:index")
        return redirect("web:dashboard")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        if form.cleaned_data["role"] == "store":
            messages.success(request, "门店账号已创建，正在进入门店后台。")
            return redirect("admin:index")
        messages.success(request, "注册成功！先为您的毛孩子建立档案吧。")
        return redirect("web:pet_create")
    return render(request, "web/account/register.html", {"form": form})


class LoginView(auth_views.LoginView):
    template_name = "web/account/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def get_success_url(self):
        role = self.request.POST.get("role") or self.request.GET.get("role")
        if self.request.user.is_staff and (
            role == "store" or not hasattr(self.request.user, "owner_profile")
        ):
            return reverse("admin:index")
        return super().get_success_url()

    def get_initial(self):
        initial = super().get_initial()
        role = self.request.GET.get("role")
        if role in ("customer", "store"):
            initial["role"] = role
        return initial


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
    active_orders = orders.filter(status__in=Order.ACTIVE_STATUSES).order_by("check_in")
    context = {
        "active_orders": active_orders,
        "active_count": active_orders.count(),
        "pets": owner.pets.all(),
        "to_review": list(orders.filter(status=Order.Status.COMPLETED, review__isnull=True)[:5]),
        "vaccine_warnings": [p for p in owner.pets.all() if not p.vaccine_valid_through(today + timedelta(days=30))],
    }
    return render(request, "web/dashboard.html", context)


@owner_required
def review_list(request):
    orders = Order.objects.filter(pet__owner=request.owner).select_related("pet", "room")
    pending = orders.filter(status=Order.Status.COMPLETED, review__isnull=True).order_by("-check_out")
    reviews = (
        Review.objects.filter(order__pet__owner=request.owner)
        .select_related("order__pet", "order__room")
        .order_by("-created_at")
    )
    return render(request, "web/reviews/list.html", {"pending": pending, "reviews": reviews})


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
    booking_quote = _parse_quote(form.data if form.is_bound else initial)
    if request.method == "POST":
        with transaction.atomic():
            room_id = form.data.get("room", "")
            if room_id.isdigit():
                list(Room.objects.select_for_update().filter(pk=room_id))
            if form.is_valid():
                order = form.save()
                messages.success(request, f"预约成功，订单号 {order.order_no}，请完成支付以锁定房间")
                return redirect("web:order_pay", order_no=order.order_no)
    return render(request, "web/orders/create.html", {"form": form, "quote": booking_quote})


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
    return render(request, "web/orders/detail.html", context)


@owner_required
def order_pay(request, order_no):
    order = _owner_order(request, order_no)
    if not order.can_pay:
        messages.info(request, "该订单无需支付")
        return redirect(order)
    if request.method == "POST":
        from apps.payments.services import CheckoutError, settle_payment, start_checkout

        try:
            payment, _session = start_checkout(order, request)
            settle_payment(payment, payment.provider_trade_no or f"SBX-{payment.transaction_no}")
        except CheckoutError as exc:
            messages.error(request, str(exc))
            return redirect("web:order_pay", order_no=order.order_no)
        messages.success(request, "支付成功（演示环境，未产生真实扣款）")
        return redirect(order)
    return render(request, "web/orders/pay.html", {"order": order})


@owner_required
@require_POST
def order_cancel(request, order_no):
    order = _owner_order(request, order_no)
    form = CancelForm(request.POST)
    try:
        order.cancel(form.data.get("reason", "")[:200])
        messages.success(request, "预约已取消")
    except ValidationError as exc:
        messages.error(request, "；".join(exc.messages))
    return redirect(order)


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
    """预约页费用明细片段。"""
    booking_quote = _parse_quote(request.GET)
    return render(
        request,
        "web/orders/_quote.html",
        {"quote": booking_quote, "payable": booking_quote.total if booking_quote else None},
    )


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
