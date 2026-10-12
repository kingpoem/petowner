"""开放 REST JSON API（/api/v1/），供小程序 / 渠道对接。"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.bookings.calendar import build_calendar
from apps.bookings.models import Order, Payment, Waitlist, find_available_rooms
from apps.care.models import Review, ServiceRecord
from apps.loyalty.services import apply_coupon, preview_loyalty_discount, redeem_points
from apps.pets.models import Pet
from apps.rooms.models import Room
from apps.rooms.pricing import quote
from apps.stores.models import Store
from apps.web.forms import BookingForm

from .auth import api_json, api_owner_required, api_staff_required, parse_json
from .serializers import calendar_json, care_json, order_json, quote_json, room_json


def _parse_date(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 日期格式无效，请用 YYYY-MM-DD") from exc


def _store(request, code: str | None = None):
    code = code or request.GET.get("store") or getattr(getattr(request, "store", None), "code", None)
    if code:
        return Store.objects.filter(code=code, is_active=True).first()
    return getattr(request, "store", None)


@require_GET
def health(request):
    return api_json({"service": "pawstay-api", "version": "v1", "time": timezone.now().isoformat()})


@require_GET
def rooms_availability(request):
    try:
        check_in = _parse_date(request.GET.get("check_in"), "check_in")
        check_out = _parse_date(request.GET.get("check_out"), "check_out")
    except ValueError as exc:
        return api_json(error=str(exc), code="bad_request", status=400)
    if check_out <= check_in:
        return api_json(error="离店须晚于入住", code="bad_request", status=400)
    species = request.GET.get("species") or "dog"
    room_type = request.GET.get("room_type") or ""
    store = _store(request)
    rooms = find_available_rooms(
        species, check_in, check_out, room_type=room_type, listed_only=True, store=store
    )
    results = []
    for room in rooms:
        q = quote(room, check_in, check_out)
        results.append({**room_json(room), "quote": quote_json(q)})
    return api_json({"check_in": check_in.isoformat(), "check_out": check_out.isoformat(), "rooms": results})


@require_GET
def rooms_calendar(request):
    today = timezone.localdate()
    try:
        start = _parse_date(request.GET.get("start") or today.isoformat(), "start")
        nights = int(request.GET.get("nights") or 14)
    except (ValueError, TypeError) as exc:
        return api_json(error=str(exc) if isinstance(exc, ValueError) else "参数无效", code="bad_request", status=400)
    store = _store(request)
    cal = build_calendar(start, nights, store=store)
    return api_json(calendar_json(cal))


@require_GET
def quotes(request):
    try:
        room = Room.objects.get(pk=request.GET.get("room"))
        check_in = _parse_date(request.GET.get("check_in"), "check_in")
        check_out = _parse_date(request.GET.get("check_out"), "check_out")
    except (Room.DoesNotExist, ValueError) as exc:
        return api_json(error=str(exc) if isinstance(exc, ValueError) else "房间不存在", code="bad_request", status=400)
    if not (0 < (check_out - check_in).days <= settings.MAX_BOARDING_DAYS):
        return api_json(error="寄养天数无效", code="bad_request", status=400)
    q = quote(room, check_in, check_out)
    loyalty = None
    owner = getattr(getattr(request, "user", None), "owner_profile", None)
    if owner is None:
        from .auth import authenticate_request

        user = authenticate_request(request)
        owner = getattr(user, "owner_profile", None) if user else None
    if owner is not None:
        try:
            points = int(request.GET.get("redeem_points") or 0)
        except (TypeError, ValueError):
            points = 0
        loyalty = preview_loyalty_discount(
            owner,
            q.total,
            coupon_code=request.GET.get("coupon_code", ""),
            redeem_points=points,
            store=room.store or _store(request),
        )
    return api_json({"room": room_json(room), "quote": quote_json(q, loyalty)})


@csrf_exempt
@require_POST
@api_owner_required
def bookings_create(request):
    try:
        payload = parse_json(request)
    except ValueError as exc:
        return api_json(error=str(exc), code="bad_request", status=400)
    form = BookingForm(payload, owner=request.api_owner, store=_store(request, payload.get("store")))
    if not form.is_valid():
        return api_json({"errors": form.errors.get_json_data()}, error="校验失败", code="validation", status=400)
    with transaction.atomic():
        room_id = form.cleaned_data["room"].pk
        list(Room.objects.select_for_update().filter(pk=room_id))
        order = form.save(commit=False)
        form.apply_loyalty(order)
        order.save()
        if order.points_redeemed:
            redeem_points(request.api_owner, order.points_redeemed, order=order)
        if form.coupon and form.coupon_discount:
            apply_coupon(form.coupon, request.api_owner, order, form.coupon_discount)
    return api_json(order_json(order), status=201)


@require_GET
@api_owner_required
def orders_list(request):
    qs = Order.objects.filter(pet__owner=request.api_owner).select_related("pet", "room").order_by("-created_at")
    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status)
    return api_json({"orders": [order_json(o) for o in qs[:50]]})


@require_GET
@api_owner_required
def orders_detail(request, order_no):
    order = get_object_or_404(
        Order.objects.select_related("pet", "room").prefetch_related("service_records"),
        order_no=order_no,
        pet__owner=request.api_owner,
    )
    return api_json(order_json(order, include_care=True))


@csrf_exempt
@require_POST
@api_owner_required
def orders_cancel(request, order_no):
    order = get_object_or_404(Order, order_no=order_no, pet__owner=request.api_owner)
    try:
        payload = parse_json(request)
    except ValueError as exc:
        return api_json(error=str(exc), code="bad_request", status=400)
    try:
        order.cancel(reason=payload.get("reason", "API 取消"))
    except Exception as exc:  # ValidationError etc.
        return api_json(error=str(exc), code="conflict", status=409)
    return api_json(order_json(order))


@require_GET
@api_owner_required
def orders_care(request, order_no):
    order = get_object_or_404(Order, order_no=order_no, pet__owner=request.api_owner)
    records = order.service_records.all()[:100]
    return api_json({"order_no": order.order_no, "records": [care_json(r) for r in records]})


@require_GET
@api_owner_required
def orders_care_digest(request, order_no):
    from apps.care.digest import build_care_digest

    order = get_object_or_404(Order, order_no=order_no, pet__owner=request.api_owner)
    day = request.GET.get("date")
    try:
        when = _parse_date(day, "date") if day else timezone.localdate()
    except ValueError as exc:
        return api_json(error=str(exc), code="bad_request", status=400)
    return api_json(build_care_digest(order, when))


@csrf_exempt
@require_POST
@api_owner_required
def orders_review(request, order_no):
    from apps.loyalty.services import issue_review_coupon

    order = get_object_or_404(Order, order_no=order_no, pet__owner=request.api_owner)
    if not order.can_review:
        return api_json(error="该订单暂不能评价", code="conflict", status=409)
    try:
        payload = parse_json(request)
        rating = int(payload.get("rating") or 0)
    except (ValueError, TypeError) as exc:
        return api_json(error=str(exc), code="bad_request", status=400)
    if rating < 1 or rating > 5:
        return api_json(error="评分须为 1-5", code="bad_request", status=400)
    review = Review.objects.create(
        order=order,
        rating=rating,
        content=payload.get("content", "")[:2000],
        feedback=payload.get("feedback", "")[:2000],
        is_public=bool(payload.get("is_public", True)),
    )
    coupon = issue_review_coupon(order.owner, order)
    data = {"rating": review.rating, "coupon_code": coupon.code if coupon else ""}
    return api_json(data, status=201)


@csrf_exempt
@require_http_methods(["POST"])
@api_owner_required
def waitlist_create(request):
    try:
        payload = parse_json(request)
        pet = Pet.objects.get(pk=payload.get("pet"), owner=request.api_owner)
        check_in = _parse_date(payload.get("check_in"), "check_in")
        check_out = _parse_date(payload.get("check_out"), "check_out")
    except (Pet.DoesNotExist, ValueError, TypeError) as exc:
        return api_json(error=str(exc), code="bad_request", status=400)
    entry = Waitlist.objects.create(
        pet=pet,
        room_type=payload.get("room_type") or "",
        check_in=check_in,
        check_out=check_out,
    )
    return api_json({"id": entry.pk, "status": entry.status}, status=201)


@csrf_exempt
@require_http_methods(["DELETE", "POST"])
@api_owner_required
def waitlist_cancel(request, pk):
    entry = get_object_or_404(Waitlist, pk=pk, pet__owner=request.api_owner)
    entry.status = Waitlist.Status.CANCELLED
    entry.save(update_fields=["status"])
    return api_json({"id": entry.pk, "status": entry.status})


@csrf_exempt
@require_POST
@api_staff_required
def staff_check_in(request, order_no):
    order = get_object_or_404(Order, order_no=order_no)
    try:
        order.start_boarding()
    except Exception as exc:
        return api_json(error=str(exc), code="conflict", status=409)
    return api_json(order_json(order))


@csrf_exempt
@require_POST
@api_staff_required
def staff_check_out(request, order_no):
    order = get_object_or_404(Order, order_no=order_no)
    try:
        order.finish_boarding()
    except Exception as exc:
        return api_json(error=str(exc), code="conflict", status=409)
    return api_json(order_json(order))


@csrf_exempt
@require_POST
@api_staff_required
def staff_care(request, order_no):
    order = get_object_or_404(Order, order_no=order_no)
    try:
        payload = parse_json(request)
    except ValueError as exc:
        return api_json(error=str(exc), code="bad_request", status=400)
    record = ServiceRecord.objects.create(
        order=order,
        staff=payload.get("staff") or request.api_user.get_username(),
        care_content=payload.get("care_content") or payload.get("content") or "",
        appetite=payload.get("appetite") or ServiceRecord.Appetite.NA,
        health_status=payload.get("health_status") or ServiceRecord.Health.GOOD,
        health_note=payload.get("health_note") or "",
    )
    return api_json(care_json(record), status=201)


@csrf_exempt
@require_POST
@api_staff_required
def staff_collect(request, order_no):
    order = get_object_or_404(Order, order_no=order_no)
    try:
        payload = parse_json(request)
        method = payload.get("method") or Payment.Method.CASH
    except ValueError as exc:
        return api_json(error=str(exc), code="bad_request", status=400)
    try:
        order.pay(method)
    except Exception as exc:
        return api_json(error=str(exc), code="conflict", status=409)
    return api_json(order_json(order))


@csrf_exempt
@require_POST
@api_owner_required
def invoices_create(request):
    from apps.billing.models import Invoice
    from apps.billing.services import create_invoice_request

    try:
        payload = parse_json(request)
        order = Order.objects.get(order_no=payload.get("order_no"), pet__owner=request.api_owner)
    except (Order.DoesNotExist, ValueError, TypeError) as exc:
        return api_json(error=str(exc) if isinstance(exc, ValueError) else "订单不存在", code="bad_request", status=400)
    try:
        inv = create_invoice_request(
            order,
            title=payload.get("title") or request.api_owner.name,
            tax_no=payload.get("tax_no") or "",
            email=payload.get("email") or request.api_owner.email,
            kind=payload.get("kind") or Invoice.Kind.PERSONAL,
        )
    except Exception as exc:
        return api_json(error=str(exc), code="conflict", status=409)
    return api_json({"id": inv.pk, "status": inv.status, "receipt_no": inv.receipt_no}, status=201)


@require_GET
@api_owner_required
def invoices_pdf(request, pk):
    from django.http import FileResponse

    from apps.billing.models import Invoice
    from apps.billing.services import ensure_invoice_pdf

    inv = get_object_or_404(Invoice, pk=pk, owner=request.api_owner)
    ensure_invoice_pdf(inv)
    return FileResponse(inv.pdf.open("rb"), as_attachment=True, filename=f"{inv.receipt_no}.pdf")
