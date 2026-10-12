from __future__ import annotations

from decimal import Decimal


def money(value) -> str:
    return f"{Decimal(value):.2f}"


def room_json(room) -> dict:
    return {
        "id": room.pk,
        "number": room.number,
        "name": room.display_name,
        "room_type": room.room_type,
        "room_type_label": room.get_room_type_display(),
        "pet_type": room.pet_type,
        "price": money(room.price),
        "capacity": room.capacity,
        "store_id": room.store_id,
        "photo": room.photo.url if room.photo else "",
    }


def order_json(order, *, include_care: bool = False) -> dict:
    data = {
        "order_no": order.order_no,
        "status": order.status,
        "status_label": order.get_status_display(),
        "payment_status": order.payment_status,
        "payment_status_label": order.get_payment_status_display(),
        "pet": {"id": order.pet_id, "name": order.pet.name, "species": order.pet.species},
        "room": room_json(order.room),
        "store_id": order.store_id,
        "check_in": order.check_in.isoformat(),
        "check_out": order.check_out.isoformat(),
        "days": order.days,
        "amount": money(order.amount),
        "discount": money(order.discount),
        "net_paid": money(order.net_paid),
        "balance_due": money(order.balance_due),
        "note": order.note,
        "created_at": order.created_at.isoformat(),
    }
    if include_care:
        data["care_records"] = [care_json(r) for r in order.service_records.all()[:50]]
    return data


def care_json(record) -> dict:
    return {
        "id": record.pk,
        "staff": record.staff,
        "feeding_time": record.feeding_time.isoformat(),
        "care_content": record.care_content,
        "appetite": record.appetite,
        "health_status": record.health_status,
        "health_note": record.health_note,
        "photo": record.photo.url if record.photo else "",
    }


def quote_json(q, loyalty=None) -> dict:
    data = {
        "days": q.days,
        "subtotal": money(q.subtotal) if hasattr(q, "subtotal") else money(q.total + q.discount),
        "discount": money(q.discount),
        "discount_label": getattr(q, "discount_label", ""),
        "total": money(q.total),
        "nights": [
            {"day": n.day.isoformat(), "price": money(n.price), "rule": getattr(n, "rule", "") or ""}
            for n in q.nights
        ],
    }
    if loyalty:
        data["loyalty"] = {
            "coupon_discount": money(loyalty["coupon_discount"]),
            "points_discount": money(loyalty["points_discount"]),
            "payable": money(loyalty["payable"]),
            "coupon_error": loyalty.get("coupon_error", ""),
            "points_error": loyalty.get("points_error", ""),
        }
        data["payable"] = money(loyalty["payable"])
    else:
        data["payable"] = money(q.total)
    return data


def calendar_json(cal) -> dict:
    return {
        "start": cal.start.isoformat(),
        "days": [d.isoformat() for d in cal.days],
        "occupancy": round(cal.occupancy, 1),
        "arrivals": cal.arrivals,
        "departures": cal.departures,
        "rows": [
            {
                "room": room_json(row.room),
                "cells": [
                    {
                        "date": cell.date.isoformat(),
                        "level": cell.level,
                        "occupied": cell.occupied,
                        "capacity": cell.capacity,
                        "label": cell.label,
                        "order_nos": [o.order_no for o in cell.orders],
                    }
                    for cell in row.cells
                ],
            }
            for row in cal.rows
        ],
    }
