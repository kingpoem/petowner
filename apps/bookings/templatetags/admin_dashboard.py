from datetime import datetime, time, timedelta
from decimal import Decimal

from django import template
from django.db.models import Avg, Sum
from django.utils import timezone

from apps.bookings.models import Order, Payment
from apps.care.models import Review, ServiceRecord
from apps.rooms.models import Room

register = template.Library()


@register.simple_tag(takes_context=True)
def dashboard_stats(context):
    today = timezone.localdate()
    month_start = today.replace(day=1)
    rooms = Room.objects.exclude(status=Room.Status.MAINTENANCE)
    orders = Order.objects.all()
    payments = Payment.objects.filter(created_at__gte=timezone.make_aware(datetime.combine(month_start, time.min)))
    capacity = rooms.aggregate(total=Sum("capacity"))["total"] or 0
    boarding = orders.filter(status=Order.Status.CHECKED_IN).count()
    income = payments.filter(kind=Payment.Kind.PAY, status=Payment.Status.SUCCESS).aggregate(s=Sum("amount"))[
        "s"
    ] or Decimal("0")
    refund = payments.filter(kind=Payment.Kind.REFUND, status=Payment.Status.SUCCESS).aggregate(s=Sum("amount"))[
        "s"
    ] or Decimal("0")
    alert_since = timezone.now() - timedelta(days=3)
    alerts = (
        ServiceRecord.objects.filter(created_at__gte=alert_since)
        .filter(ServiceRecord.attention_q())
        .select_related("order__pet")
    )
    return {
        "today": today,
        # 待入住：今日应入住；待离店：今日应离 + 已逾期未离
        "arrivals": orders.filter(status=Order.Status.PENDING, check_in=today).select_related("pet", "room"),
        "departures": orders.filter(status=Order.Status.CHECKED_IN, check_out__lte=today)
        .select_related("pet", "room")
        .order_by("check_out"),
        "boarding": boarding,
        "capacity": capacity,
        "occupancy": round(boarding * 100 / capacity) if capacity else 0,
        "month_revenue": income - refund,
        "unpaid": orders.filter(
            payment_status__in=(Order.PaymentStatus.UNPAID, Order.PaymentStatus.PARTIAL),
            status__in=Order.ACTIVE_STATUSES,
        ).count(),
        "alerts": alerts[:5],
        "avg_rating": Review.objects.aggregate(avg=Avg("rating"))["avg"],
        "pending_reviews": Review.objects.filter(reply="").count(),
    }
