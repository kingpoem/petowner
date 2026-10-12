"""经营报表：按日统计收款、间夜与入住率，并按房型、渠道、支付方式拆分。

收入按收款流水（收付实现制）统计；入住率 = 已售间夜 / 可售间夜，未取消的预约均计入（含未来已预订）。
"""

import csv
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.http import HttpResponse
from django.utils import timezone

from apps.rooms.models import Room

from .models import Order, Payment

ZERO = Decimal("0.00")


@dataclass
class Bucket:
    label: str
    start: date
    income: Decimal = ZERO
    refund: Decimal = ZERO
    nights: int = 0
    capacity: int = 0
    new_orders: int = 0

    @property
    def net(self) -> Decimal:
        return self.income - self.refund

    @property
    def occupancy(self) -> float:
        return self.nights * 100 / self.capacity if self.capacity else 0.0


@dataclass
class Slice:
    label: str
    orders: int = 0
    nights: int = 0
    revenue: Decimal = ZERO
    capacity: int = 0
    share: float = 0.0

    @property
    def occupancy(self) -> float:
        return self.nights * 100 / self.capacity if self.capacity else 0.0


@dataclass
class Report:
    start: date
    end: date
    days: list[Bucket] = field(default_factory=list)
    room_types: list[Slice] = field(default_factory=list)
    channels: list[Slice] = field(default_factory=list)
    methods: list[Slice] = field(default_factory=list)
    kpis: dict = field(default_factory=dict)

    @property
    def monthly(self) -> bool:
        return len(self.days) > 62

    def buckets(self) -> list[Bucket]:
        """图表用的分组：超过两个月按月汇总，否则按日。"""
        if not self.monthly:
            return self.days
        months: dict[tuple[int, int], Bucket] = {}
        for day in self.days:
            key = (day.start.year, day.start.month)
            bucket = months.setdefault(key, Bucket(label=f"{key[0]}-{key[1]:02d}", start=day.start.replace(day=1)))
            bucket.income += day.income
            bucket.refund += day.refund
            bucket.nights += day.nights
            bucket.capacity += day.capacity
            bucket.new_orders += day.new_orders
        return list(months.values())


def _bounds(start: date, end: date):
    tz = timezone.get_current_timezone()
    return (
        datetime.combine(start, time.min, tzinfo=tz),
        datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz),
    )


def _with_share(slices: dict[str, Slice], total: Decimal) -> list[Slice]:
    for item in slices.values():
        item.share = float(item.revenue * 100 / total) if total > 0 else 0.0
    return sorted(slices.values(), key=lambda s: s.revenue, reverse=True)


def build_report(start: date, end: date, store=None) -> Report:
    report = Report(start=start, end=end)
    lo, hi = _bounds(start, end)
    span = (end - start).days + 1
    by_day = {
        start + timedelta(days=i): Bucket(label=f"{start + timedelta(days=i):%m-%d}", start=start + timedelta(days=i))
        for i in range(span)
    }

    rooms = Room.objects.exclude(status=Room.Status.MAINTENANCE)
    orders_qs = Order.objects.all()
    payments_qs = Payment.objects.filter(status=Payment.Status.SUCCESS, created_at__gte=lo, created_at__lt=hi)
    if store is not None:
        rooms = rooms.filter(store=store)
        orders_qs = orders_qs.filter(store=store)
        payments_qs = payments_qs.filter(order__store=store)
    room_types = {key: Slice(label=label) for key, label in Room.RoomType.choices}
    for row in rooms.values("room_type").annotate(cap=Sum("capacity")):
        room_types[row["room_type"]].capacity = row["cap"] * span
    daily_capacity = sum(rooms.values_list("capacity", flat=True))
    for bucket in by_day.values():
        bucket.capacity = daily_capacity

    channels = {key: Slice(label=label) for key, label in Order.Source.choices}
    methods = {key: Slice(label=label) for key, label in Payment.Method.choices}
    payments = payments_qs.values_list(
        "created_at", "kind", "amount", "method", "order__source", "order__room__room_type"
    )
    for created_at, kind, amount, method, source, room_type in payments:
        signed = -amount if kind == Payment.Kind.REFUND else amount
        bucket = by_day[timezone.localtime(created_at).date()]
        if kind == Payment.Kind.REFUND:
            bucket.refund += amount
        else:
            bucket.income += amount
        channels[source].revenue += signed
        methods[method].revenue += signed
        room_types[room_type].revenue += signed

    created = orders_qs.filter(created_at__gte=lo, created_at__lt=hi)
    for created_at, source in created.values_list("created_at", "source"):
        by_day[timezone.localtime(created_at).date()].new_orders += 1
        channels[source].orders += 1
    for row in created.values("room__room_type").annotate(n=Count("id")):
        room_types[row["room__room_type"]].orders = row["n"]

    stays = (
        orders_qs.exclude(status=Order.Status.CANCELLED)
        .filter(check_in__lte=end, check_out__gt=start)
        .values_list("check_in", "check_out", "room__room_type", "source")
    )
    for check_in, check_out, room_type, source in stays:
        first, last = max(check_in, start), min(check_out - timedelta(days=1), end)
        nights = (last - first).days + 1
        room_types[room_type].nights += nights
        channels[source].nights += nights
        day = first
        while day <= last:
            by_day[day].nights += 1
            day += timedelta(days=1)

    report.days = list(by_day.values())
    income = sum((d.income for d in report.days), ZERO)
    refund = sum((d.refund for d in report.days), ZERO)
    net = income - refund
    nights = sum(d.nights for d in report.days)
    capacity = daily_capacity * span
    order_count = created.count()
    cancelled = created.filter(status=Order.Status.CANCELLED).count()
    kept = created.exclude(status=Order.Status.CANCELLED)
    stay_lengths = [(o - i).days for i, o in kept.values_list("check_in", "check_out")]
    owners = kept.values_list("pet__owner", flat=True).distinct()
    repeat = (
        orders_qs.exclude(status=Order.Status.CANCELLED)
        .filter(pet__owner__in=owners)
        .values("pet__owner")
        .annotate(n=Count("id"))
        .filter(n__gte=2)
        .count()
    )
    report.kpis = {
        "income": income,
        "refund": refund,
        "net": net,
        "nights": nights,
        "occupancy": nights * 100 / capacity if capacity else 0.0,
        "adr": (net / nights).quantize(Decimal("0.01")) if nights else ZERO,
        "orders": order_count,
        "cancel_rate": cancelled * 100 / order_count if order_count else 0.0,
        "avg_stay": sum(stay_lengths) / len(stay_lengths) if stay_lengths else 0.0,
        "repeat_rate": repeat * 100 / len(owners) if owners else 0.0,
        "store": getattr(store, "name", "") or "全部门店",
    }
    report.room_types = [s for s in _with_share(room_types, net) if s.capacity or s.orders or s.revenue]
    report.channels = _with_share(channels, net)
    report.methods = [s for s in _with_share(methods, net) if s.revenue]
    return report


# ---------- 图表（服务端生成 SVG 坐标，无需前端图表库） ----------

CHART_W, CHART_H = 760, 260
PAD_L, PAD_R, PAD_T, PAD_B = 56, 44, 16, 30


def _nice_ceiling(value: float) -> float:
    if value <= 0:
        return 100.0
    magnitude = 10 ** (len(str(int(value))) - 1)
    for step in (1, 2, 2.5, 5, 10):
        if value <= step * magnitude:
            return step * magnitude
    return 10 * magnitude


def chart(report: Report) -> dict:
    buckets = report.buckets()
    plot_w, plot_h = CHART_W - PAD_L - PAD_R, CHART_H - PAD_T - PAD_B
    top = _nice_ceiling(float(max((b.net for b in buckets), default=0)))
    slot = plot_w / max(len(buckets), 1)
    bar_w = max(min(slot * 0.62, 36), 2)
    every = max(1, round(len(buckets) / 10))
    bars, points = [], []
    for i, b in enumerate(buckets):
        cx = PAD_L + slot * (i + 0.5)
        h = max(float(b.net), 0) / top * plot_h
        bars.append(
            {
                "x": round(cx - bar_w / 2, 1),
                "y": round(PAD_T + plot_h - h, 1),
                "w": round(bar_w, 1),
                "h": round(h, 1),
                "label": b.label,
                "net": b.net,
                "occupancy": round(b.occupancy),
                "show_label": i % every == 0,
                "cx": round(cx, 1),
            }
        )
        points.append(f"{cx:.1f},{PAD_T + plot_h - min(b.occupancy, 100) / 100 * plot_h:.1f}")
    ticks = [
        {"y": round(PAD_T + plot_h - plot_h * k / 4, 1), "money": f"{top * k / 4:,.0f}", "pct": f"{25 * k}%"}
        for k in range(5)
    ]
    return {
        "width": CHART_W,
        "height": CHART_H,
        "bars": bars,
        "line": " ".join(points),
        "ticks": ticks,
        "left": PAD_L,
        "right": CHART_W - PAD_R,
        "baseline": PAD_T + plot_h,
        "label_y": CHART_H - 8,
    }


# ---------- 导出（CSV 带 BOM；xlsx 用 openpyxl） ----------

ORDER_HEADERS = [
    "订单号",
    "下单时间",
    "渠道",
    "宠物",
    "主人",
    "手机号",
    "房间",
    "入住",
    "离店",
    "晚数",
    "订单金额",
    "已付净额",
    "支付状态",
    "订单状态",
]
DAILY_HEADERS = ["日期", "收款（元）", "退款（元）", "净收入（元）", "已售间夜", "可售间夜", "入住率", "新增订单"]


def _csv_response(filename: str) -> tuple[HttpResponse, csv.writer]:
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")
    return response, csv.writer(response)


def _xlsx_response(filename: str, sheets: dict[str, list[list]]):
    from io import BytesIO

    from openpyxl import Workbook

    book = Workbook()
    first = True
    for title, rows in sheets.items():
        sheet = book.active if first else book.create_sheet(title)
        if first:
            sheet.title = title
            first = False
        for row in rows:
            sheet.append(row)
    buf = BytesIO()
    book.save(buf)
    response = HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _order_rows(report: Report) -> list[list]:
    lo, hi = _bounds(report.start, report.end)
    orders = (
        Order.objects.filter(created_at__gte=lo, created_at__lt=hi)
        .select_related("pet__owner", "room")
        .prefetch_related("payments")
        .order_by("created_at")
    )
    rows = [ORDER_HEADERS]
    for o in orders:
        rows.append(
            [
                o.order_no,
                f"{timezone.localtime(o.created_at):%Y-%m-%d %H:%M}",
                o.get_source_display(),
                o.pet.name,
                o.pet.owner.name,
                o.pet.owner.phone,
                o.room.display_name,
                o.check_in.isoformat(),
                o.check_out.isoformat(),
                o.days,
                float(o.amount),
                float(o.net_paid),
                o.get_payment_status_display(),
                o.get_status_display(),
            ]
        )
    return rows


def _daily_rows(report: Report) -> list[list]:
    rows = [DAILY_HEADERS]
    for d in report.days:
        rows.append(
            [
                d.start.isoformat(),
                float(d.income),
                float(d.refund),
                float(d.net),
                d.nights,
                d.capacity,
                round(d.occupancy, 1),
                d.new_orders,
            ]
        )
    k = report.kpis
    rows.append(
        [
            "合计",
            float(k["income"]),
            float(k["refund"]),
            float(k["net"]),
            k["nights"],
            "",
            round(k["occupancy"], 1),
            k["orders"],
        ]
    )
    return rows


def export_daily(report: Report) -> HttpResponse:
    response, writer = _csv_response(f"pawstay-daily-{report.start:%Y%m%d}-{report.end:%Y%m%d}.csv")
    for row in _daily_rows(report):
        writer.writerow([f"{c:.2f}" if isinstance(c, float) and i in (1, 2, 3) else c for i, c in enumerate(row)])
    return response


def export_orders(report: Report) -> HttpResponse:
    response, writer = _csv_response(f"pawstay-orders-{report.start:%Y%m%d}-{report.end:%Y%m%d}.csv")
    for row in _order_rows(report):
        writer.writerow(row)
    return response


def export_xlsx(report: Report) -> HttpResponse:
    k = report.kpis
    summary = [
        ["指标", "数值"],
        ["统计区间", f"{report.start} ~ {report.end}"],
        ["净收入（元）", float(k["net"])],
        ["收款（元）", float(k["income"])],
        ["退款（元）", float(k["refund"])],
        ["入住率", f"{k['occupancy']:.1f}%"],
        ["平均每间夜收入", float(k["adr"])],
        ["订单数", k["orders"]],
        ["取消率", f"{k['cancel_rate']:.1f}%"],
        ["平均寄养时长（晚）", round(k["avg_stay"], 2)],
        ["复购顾客占比", f"{k['repeat_rate']:.1f}%"],
    ]
    return _xlsx_response(
        f"pawstay-report-{report.start:%Y%m%d}-{report.end:%Y%m%d}.xlsx",
        {"日结摘要": summary, "每日明细": _daily_rows(report), "订单明细": _order_rows(report)},
    )
