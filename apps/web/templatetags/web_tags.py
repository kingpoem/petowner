from django import template
from django.templatetags.static import static

from apps.images import thumbnail_url

register = template.Library()

STATUS_BADGES = {
    "pending": "info",
    "checked_in": "primary",
    "completed": "success",
    "cancelled": "secondary",
    "unpaid": "warning",
    "partial": "warning",
    "paid": "success",
    "refunded": "secondary",
    "waiting": "info",
    "notified": "success",
    "good": "success",
    "normal": "warning",
    "abnormal": "danger",
}

FALLBACK_IMAGES = {
    "room": "img/stock/room-any.jpg",
    "dog": "img/stock/pet-golden.jpg",
    "cat": "img/stock/pet-british.jpg",
    "other": "img/stock/room-any.jpg",
}


@register.filter
def badge(value: str) -> str:
    return STATUS_BADGES.get(value, "secondary")


@register.simple_tag
def image_url(obj, field: str = "photo", fallback: str = "room", size: int | None = None) -> str:
    """上传图片地址（传入 size 时返回 WebP 缩略图）；未上传时按物种/房间返回默认配图。"""
    file = getattr(obj, field, None)
    if file and getattr(file, "_committed", True):
        return thumbnail_url(file, size) if size else file.url
    key = getattr(obj, "species", fallback)
    return static(FALLBACK_IMAGES.get(key, FALLBACK_IMAGES["room"]))


@register.simple_tag
def thumb(file, size: int = 480) -> str:
    return thumbnail_url(file, size)


@register.filter
def stars(value) -> range:
    return range(int(round(float(value or 0))))


@register.filter
def empty_stars(value) -> range:
    return range(5 - int(round(float(value or 0))))
