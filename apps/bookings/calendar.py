"""房态日历：房间 × 日期占用矩阵。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from django.db import models

from apps.rooms.models import Room

from .models import Order


@dataclass
class Cell:
    date: date
    occupied: int = 0
    capacity: int = 1
    orders: list = field(default_factory=list)

    @property
    def next_day(self) -> date:
        return self.date + timedelta(days=1)

    @property
    def level(self) -> str:
        if self.occupied <= 0:
            return "free"
        if self.occupied >= self.capacity:
            return "full"
        return "partial"

    @property
    def label(self) -> str:
        if not self.orders:
            return "空"
        names = "、".join(o.pet.name for o in self.orders[:2])
        more = f" 等{self.occupied}只" if self.occupied > 2 else ""
        return names + more


@dataclass
class Row:
    room: Room
    cells: list[Cell]


@dataclass
class Calendar:
    start: date
    days: list[date]
    rows: list[Row]
    arrivals: int = 0
    departures: int = 0
    occupied_nights: int = 0
    capacity_nights: int = 0

    @property
    def occupancy(self) -> float:
        return self.occupied_nights * 100 / self.capacity_nights if self.capacity_nights else 0.0


def build_calendar(start: date, nights: int = 14, store=None) -> Calendar:
    nights = max(7, min(nights, 31))
    days = [start + timedelta(days=i) for i in range(nights)]
    end = days[-1] + timedelta(days=1)
    rooms_qs = Room.objects.exclude(status=Room.Status.MAINTENANCE).order_by("number")
    if store is not None:
        rooms_qs = rooms_qs.filter(store=store)
    rooms = list(rooms_qs)
    orders_qs = Order.objects.filter(status__in=Order.ACTIVE_STATUSES, check_in__lt=end, check_out__gt=start)
    if store is not None:
        orders_qs = orders_qs.filter(models.Q(store=store) | models.Q(room__store=store))
    orders = orders_qs.select_related("pet", "room").order_by("check_in")
    by_room: dict[int, list[Order]] = {r.pk: [] for r in rooms}
    for order in orders:
        by_room.setdefault(order.room_id, []).append(order)

    cal = Calendar(start=start, days=days, rows=[])
    for room in rooms:
        cells = []
        for day in days:
            staying = [o for o in by_room.get(room.pk, []) if o.check_in <= day < o.check_out]
            cell = Cell(date=day, occupied=len(staying), capacity=room.capacity, orders=staying)
            cells.append(cell)
            cal.occupied_nights += cell.occupied
            cal.capacity_nights += room.capacity
            if any(o.check_in == day for o in staying):
                cal.arrivals += 1
            if any(o.check_out == day for o in by_room.get(room.pk, [])):
                cal.departures += 1
        cal.rows.append(Row(room=room, cells=cells))
    return cal
