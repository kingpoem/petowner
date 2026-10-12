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

from apps.bookings.models import Order, Waitlist, find_available_rooms
from apps.care.models import Review
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
    WaitlistForm,
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


def _listed_rooms(request):
    rooms = Room.objects.filter(is_listed=True).exclude(status=Room.Status.MAINTENANCE)
    store = getattr(request, "store", None)
    if store is not None:
        rooms = rooms.filter(Q(store=store) | Q(store__isnull=True))
    return rooms


def home(request):
    rating = Review.objects.aggregate(avg=Avg("rating"), total=Count("id"))
    rooms = _listed_rooms(request)
    tomorrow = timezone.localdate() + timedelta(days=1)
    context = {
        "rooms": rooms[:6],
        "room_count": rooms.count(),
        "reviews": _public_reviews()[:6],
        "avg_rating": rating["avg"],
        "review_count": rating["total"],
        "search_form": SearchForm(initial={"check_in": tomorrow, "check_out": tomorrow + timedelta(days=3)}),
    }
    return render(request, "web/home.html", context)


def room_list(request):
    form = SearchForm(request.GET or None)
    rooms = _listed_rooms(request)
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
            store=getattr(request, "store", None),
        )
        results = [(room, quote(room, d["check_in"], d["check_out"])) for room in available]
    elif request.GET.get("species"):
        rooms = rooms.filter(Q(pet_type=request.GET["species"]) | Q(pet_type=Room.PetType.ANY))
    context = {"form": form, "rooms": rooms, "results": results, "searched": searched}
    if searched and not results and request.user.is_authenticated and hasattr(request.user, "owner_profile"):
        context["waitlist_form"] = WaitlistForm(
            owner=request.user.owner_profile,
            initial={k: form.cleaned_data[k] for k in ("check_in", "check_out", "room_type")},
        )
    return render(request, "web/room_list.html", context)


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
        "waitlist": Waitlist.objects.filter(
            pet__owner=owner, status__in=[Waitlist.Status.WAITING, Waitlist.Status.NOTIFIED], check_in__gte=today
        ).select_related("pet"),
        "to_review": orders.filter(status=Order.Status.COMPLETED, review__isnull=True)[:3],
        "notifications": request.user.notifications.filter(is_read=False)[:5],
        "vaccine_warnings": [p for p in owner.pets.all() if not p.vaccine_valid_through(today + timedelta(days=30))],
    }
    return render(request, "web/dashboard.html", context)


@owner_required
def loyalty_center(request):
    from apps.loyalty.models import PointLedger
    from apps.loyalty.services import available_coupons, membership_tier

    owner = request.owner
    ledger = PointLedger.objects.filter(owner=owner).select_related("order")[:40]
    coupons = available_coupons(owner, store=getattr(request, "store", None))
    tier = membership_tier(owner)
    return render(
        request,
        "web/loyalty.html",
        {"ledger": ledger, "coupons": coupons, "tier": tier, "redeem_rate": settings.LOYALTY_POINTS_PER_YUAN_REDEEM},
    )


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
    form = BookingForm(
        request.POST or None, owner=request.owner, store=getattr(request, "store", None), initial=initial
    )
    booking_quote = _parse_quote(form.data if form.is_bound else initial)
    if request.method == "POST":
        with transaction.atomic():
            # 锁住房间行，使同一房间的并发预约串行校验，避免超订
            room_id = form.data.get("room", "")
            if room_id.isdigit():
                list(Room.objects.select_for_update().filter(pk=room_id))
            if form.is_valid():
                from apps.loyalty.services import apply_coupon, redeem_points

                order = form.save(commit=False)
                form.apply_loyalty(order)
                order.save()
                if order.points_redeemed:
                    redeem_points(request.owner, order.points_redeemed, order=order)
                if form.coupon and form.coupon_discount:
                    apply_coupon(form.coupon, request.owner, order, form.coupon_discount)
                Waitlist.objects.filter(
                    pet=order.pet, status=Waitlist.Status.NOTIFIED, check_in=order.check_in, check_out=order.check_out
                ).update(status=Waitlist.Status.BOOKED)
                messages.success(request, f"预约成功，订单号 {order.order_no}，请完成支付以锁定房间")
                return redirect("web:order_pay", order_no=order.order_no)
    return render(
        request,
        "web/orders/create.html",
        {"form": form, "quote": booking_quote, "owner_points": request.owner.points},
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
    from apps.billing.models import Invoice

    invoice = Invoice.objects.filter(order=order).first()
    context = {
        "order": order,
        "records": records,
        "steps": steps,
        "payments": order.payments.order_by("created_at", "pk"),
        "paid": paid,
        "balance_due": order.balance_due,
        "cancel_form": CancelForm(),
        "invoice": invoice,
        "can_invoice": paid > 0 and invoice is None,
    }
    if order.can_cancel:
        fee = order.cancellation_fee()
        context.update(cancel_fee=fee, cancel_refund=paid - fee)
    return render(request, "web/orders/detail.html", context)


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
    context = {"order": order, "form": form, **_quote_context(quote(*target), order)}
    return render(request, "web/orders/reschedule.html", context)


def _quote_context(booking_quote, order=None, loyalty=None) -> dict:
    """费用明细片段的上下文；传入订单时附带与已付金额的差额（改期场景）。"""
    context = {"quote": booking_quote, "order": order, "loyalty": loyalty}
    if booking_quote is not None and loyalty:
        context["payable"] = loyalty["payable"]
    elif booking_quote is not None:
        context["payable"] = booking_quote.total
    if order is not None and booking_quote is not None:
        base = loyalty["payable"] if loyalty else booking_quote.total
        diff = base - order.net_paid
        context.update(paid=order.net_paid, top_up=max(diff, 0), refund=max(-diff, 0))
    return context


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
    booking_quote = _parse_quote(request.GET)
    loyalty = None
    if booking_quote is not None and not order:
        from apps.loyalty.services import preview_loyalty_discount

        try:
            points = int(request.GET.get("redeem_points") or 0)
        except (TypeError, ValueError):
            points = 0
        loyalty = preview_loyalty_discount(
            request.owner,
            booking_quote.total,
            coupon_code=request.GET.get("coupon_code", ""),
            redeem_points=points,
            store=getattr(request, "store", None),
        )
    return render(request, "web/orders/_quote.html", _quote_context(booking_quote, order, loyalty))


@owner_required
def order_review(request, order_no):
    order = _owner_order(request, order_no)
    if not order.can_review:
        messages.info(request, "该订单暂不能评价")
        return redirect(order)
    form = ReviewForm(request.POST or None, instance=Review(order=order))
    if request.method == "POST" and form.is_valid():
        form.save()
        from apps.loyalty.services import issue_review_coupon

        coupon = issue_review_coupon(request.owner, order)
        if coupon:
            messages.success(request, f"感谢您的评价！已赠送优惠码 {coupon.code}")
        else:
            messages.success(request, "感谢您的评价！")
        return redirect(order)
    return render(request, "web/orders/review.html", {"order": order, "form": form})


@owner_required
def order_invoice(request, order_no):
    from apps.billing.models import Invoice
    from apps.billing.services import create_invoice_request, ensure_invoice_pdf

    order = _owner_order(request, order_no)
    existing = Invoice.objects.filter(order=order).first()
    if existing:
        ensure_invoice_pdf(existing)
        return redirect(existing.pdf.url)
    if order.net_paid <= 0:
        messages.info(request, "订单尚未支付，无法开具收据")
        return redirect(order)
    if request.method == "POST":
        try:
            inv = create_invoice_request(
                order,
                title=request.POST.get("title") or request.owner.name,
                tax_no=request.POST.get("tax_no") or "",
                email=request.POST.get("email") or request.owner.email,
                kind=request.POST.get("kind") or Invoice.Kind.PERSONAL,
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
            return redirect(order)
        messages.success(request, f"电子收据 {inv.receipt_no} 已生成")
        return redirect(inv.pdf.url)
    return render(request, "web/orders/invoice.html", {"order": order})


# ---------- 候补 ----------


@owner_required
@require_POST
def waitlist_create(request):
    form = WaitlistForm(request.POST, owner=request.owner)
    if form.is_valid():
        entry = form.save()
        if entry.available_rooms():
            entry.delete()
            messages.info(request, "该时段已有空房，直接预约即可")
            return redirect(
                f"{reverse('web:booking_create')}?pet={entry.pet_id}&check_in={entry.check_in}&check_out={entry.check_out}"
            )
        messages.success(request, "已加入候补，一旦有房会第一时间通知您")
        return redirect("web:dashboard")
    messages.error(request, "候补登记失败：" + "；".join(e for errs in form.errors.values() for e in errs))
    return redirect("web:room_list")


@owner_required
@require_POST
def waitlist_cancel(request, pk):
    entry = get_object_or_404(Waitlist, pk=pk, pet__owner=request.owner)
    entry.status = Waitlist.Status.CANCELLED
    entry.save(update_fields=["status"])
    messages.success(request, "已取消候补")
    return redirect("web:dashboard")


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
