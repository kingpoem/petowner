"""门店此刻的公开看板：只展示宠物和房间，不露出主人电话。"""

from django.db.models import Prefetch
from django.utils import timezone

from apps.bookings.models import Order
from apps.care.models import ServiceRecord
from apps.rooms.models import Room

from .models import StaffMember


def public_note(record: ServiceRecord | None) -> str:
    if record is None:
        return "刚刚安顿好，护理师正在熟悉 TA 的习惯"
    if record.needs_attention:
        return "护理师正在密切观察，主人已经收到通知"
    text = " ".join((record.care_content or "").split())
    return text[:72] or "状态平稳"


def house_board(day=None) -> dict:
    day = day or timezone.localdate()
    staying_qs = (
        Order.objects.filter(status=Order.Status.CHECKED_IN)
        .select_related("pet", "room")
        .prefetch_related(Prefetch("service_records", queryset=ServiceRecord.objects.order_by("-feeding_time")))
        .order_by("room__number", "pk")
    )
    staying = []
    for order in staying_qs:
        latest = next(iter(order.service_records.all()), None)
        staying.append(
            {
                "order": order,
                "note": public_note(latest),
                "when": latest.feeding_time if latest else order.checked_in_at,
                "alert": bool(latest and latest.needs_attention),
            }
        )
    listed = Room.objects.filter(is_listed=True).exclude(status=Room.Status.MAINTENANCE).count()
    occupied = len(staying)
    arrivals = (
        Order.objects.filter(status=Order.Status.PENDING, check_in=day)
        .select_related("pet", "room")
        .order_by("room__number")
    )
    departures = (
        Order.objects.filter(status=Order.Status.CHECKED_IN, check_out=day)
        .select_related("pet", "room")
        .order_by("room__number")
    )
    return {
        "day": day,
        "staying": staying,
        "arrivals": arrivals,
        "departures": departures,
        "occupied": occupied,
        "listed": listed,
        "rate": round(occupied * 100 / listed) if listed else 0,
        "staff": StaffMember.objects.filter(is_active=True),
    }
