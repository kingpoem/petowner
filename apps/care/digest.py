"""在住护理日报摘要。"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from django.utils import timezone

from apps.bookings.models import Order
from apps.notifications.services import notify_owner


def build_care_digest(order: Order, day: date) -> dict:
    tz = timezone.get_current_timezone()
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    records = list(
        order.service_records.filter(feeding_time__gte=start, feeding_time__lt=end).order_by("feeding_time")
    )
    abnormal = [r for r in records if r.needs_attention]
    lines = []
    for r in records:
        stamp = timezone.localtime(r.feeding_time).strftime("%H:%M")
        lines.append(f"{stamp} {r.staff}：{r.care_content}")
    summary = "；".join(lines) if lines else "本日暂无护理记录"
    return {
        "order_no": order.order_no,
        "pet": order.pet.name,
        "date": day.isoformat(),
        "count": len(records),
        "abnormal_count": len(abnormal),
        "summary": summary[:500],
        "records": [
            {
                "time": timezone.localtime(r.feeding_time).strftime("%H:%M"),
                "staff": r.staff,
                "content": r.care_content,
                "health_status": r.health_status,
            }
            for r in records
        ],
    }


def send_care_digests(day: date | None = None) -> int:
    """向所有在住订单主人推送当日护理摘要，返回推送人数。"""
    day = day or timezone.localdate()
    orders = Order.objects.filter(status=Order.Status.CHECKED_IN).select_related("pet__owner")
    sent = 0
    for order in orders:
        digest = build_care_digest(order, day)
        if digest["count"] == 0:
            continue
        title = f"{order.pet.name} {day:%m月%d日}护理日报"
        body = digest["summary"]
        if digest["abnormal_count"]:
            body = f"【含 {digest['abnormal_count']} 条需关注】" + body
        notify_owner(
            order.owner,
            title,
            body[:200],
            order.get_absolute_url(),
            sms_event="care",
        )
        sent += 1
    return sent
