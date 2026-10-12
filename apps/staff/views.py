from datetime import datetime, time
from functools import wraps
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Max, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from apps.bookings.models import Order, Payment

from .forms import QUICK_PHRASES, CareRecordForm

TABS = (
    ("arrivals", "待入住", "bi-box-arrow-in-right"),
    ("boarding", "在住", "bi-house-heart"),
    ("departures", "今日离店", "bi-box-arrow-right"),
)


@require_GET
def service_worker(request):
    """从 /staff/sw.js 提供 Service Worker，scope 才能覆盖工作台路径。"""
    path = Path(settings.BASE_DIR) / "static" / "js" / "staff-sw.js"
    response = HttpResponse(path.read_text(encoding="utf-8"), content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/staff/"
    response["Cache-Control"] = "no-cache"
    return response


def staff_required(perm: str | None = None):
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path(), reverse("admin:login"))
            if not request.user.is_staff or (perm and not request.user.has_perm(perm)):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


def _back(request) -> str:
    target = request.POST.get("next") or ""
    if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return target
    return reverse("staff:board")


def _staff_name(user) -> str:
    return user.get_full_name() or user.first_name or user.get_username()


def _queues(today):
    day_start = timezone.make_aware(datetime.combine(today, time.min))
    base = (
        Order.objects.select_related("pet__owner", "room")
        .prefetch_related("payments")
        .annotate(
            last_care=Max("service_records__feeding_time"),
            care_today=Count("service_records", filter=Q(service_records__feeding_time__gte=day_start)),
        )
    )
    boarding = base.filter(status=Order.Status.CHECKED_IN)
    return {
        "arrivals": base.filter(status=Order.Status.PENDING, check_in__lte=today).order_by("check_in", "room__number"),
        "boarding": boarding.order_by("room__number"),
        "departures": boarding.filter(check_out__lte=today).order_by("room__number"),
    }


@staff_required()
def board(request):
    today = timezone.localdate()
    queues = _queues(today)
    tab = request.GET.get("tab") if request.GET.get("tab") in queues else "boarding"
    query = request.GET.get("q", "").strip()
    orders = queues[tab]
    if query:
        orders = orders.filter(
            Q(pet__name__icontains=query)
            | Q(pet__owner__name__icontains=query)
            | Q(pet__owner__phone__contains=query)
            | Q(order_no__icontains=query)
            | Q(room__number__icontains=query)
        )
    context = {
        "tabs": [(key, label, icon, queues[key].count()) for key, label, icon in TABS],
        "tab": tab,
        "query": query,
        "orders": orders,
        "today": today,
    }
    return render(request, "staff/board.html", context)


def _transition(request, pk, action: str, success: str):
    order = get_object_or_404(Order, pk=pk)
    try:
        getattr(order, action)()
    except ValidationError as exc:
        messages.error(request, "；".join(exc.messages))
    else:
        messages.success(request, success.format(pet=order.pet.name, room=order.room.display_name))
    return redirect(_back(request))


@staff_required("bookings.change_order")
@require_POST
def check_in(request, pk):
    return _transition(request, pk, "start_boarding", "{pet} 已入住 {room}")


@staff_required("bookings.change_order")
@require_POST
def check_out(request, pk):
    return _transition(request, pk, "finish_boarding", "{pet} 已办理离店")


@staff_required("bookings.change_order")
@require_POST
def collect(request, pk):
    order = get_object_or_404(Order, pk=pk)
    method = request.POST.get("method")
    if method not in (Payment.Method.CASH, Payment.Method.CARD):
        messages.error(request, "请选择收款方式")
        return redirect(_back(request))
    try:
        payment = order.pay(method)
    except ValidationError as exc:
        messages.error(request, "；".join(exc.messages))
    else:
        messages.success(request, f"已收款 ¥{payment.amount}（{payment.get_method_display()}）")
    return redirect(_back(request))


@staff_required("care.add_servicerecord")
def care_record(request, pk):
    order = get_object_or_404(Order.objects.select_related("pet__owner", "room"), pk=pk)
    if order.status != Order.Status.CHECKED_IN:
        messages.info(request, "仅寄养中的订单可以记录护理")
        return redirect("staff:board")
    form = CareRecordForm(
        request.POST or None, request.FILES or None, order=order, staff_name=_staff_name(request.user)
    )
    if request.method == "POST" and form.is_valid():
        record = form.save()
        messages.success(request, f"已记录并通知主人：{record.care_content[:20]}")
        return redirect(f"{reverse('staff:board')}?tab=boarding")
    context = {
        "order": order,
        "form": form,
        "phrases": QUICK_PHRASES,
        "recent": order.service_records.all()[:5],
    }
    return render(request, "staff/care_form.html", context)
