"""门店权限：StaffStore 未配置视为可管理全部门店。"""

from __future__ import annotations

from django.db.models import QuerySet

from .models import StaffStore, Store


def allowed_stores_for(user) -> QuerySet[Store]:
    qs = Store.objects.filter(is_active=True)
    if not user or not user.is_authenticated or not user.is_staff:
        return qs
    if user.is_superuser:
        return qs
    codes = StaffStore.objects.filter(user=user).values_list("store_id", flat=True)
    if not codes:
        return qs
    return qs.filter(pk__in=codes)


def resolve_store(user, preferred_code: str | None = None) -> Store | None:
    allowed = allowed_stores_for(user)
    if preferred_code:
        store = allowed.filter(code=preferred_code).first()
        if store:
            return store
    return allowed.filter(is_default=True).first() or allowed.first()
