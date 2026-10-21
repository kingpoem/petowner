"""精简后台导航：首页直达订单列表；空壳应用页直达主列表；隐藏次要模块入口；去掉外键小图标。"""

from django.contrib.admin.options import ModelAdmin
from django.contrib.admin.sites import AdminSite
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse

# 每个应用优先落到的模型（object_name 小写）
_PRIMARY_MODEL = {
    "bookings": "order",
    "pets": "pet",
    "care": "servicerecord",
    "rooms": "room",
    "hospitality": "addonservice",
    "auth": "user",
}

# 侧栏/应用列表不展示：门店管理、收退款流水、权限组/用户
_HIDDEN_MODELS = {
    ("stores", "store"),
    ("bookings", "payment"),
    ("auth", "group"),
    ("auth", "user"),
}

_original_get_app_list = AdminSite.get_app_list
_original_index = AdminSite.index
_original_formfield_for_dbfield = ModelAdmin.formfield_for_dbfield


def _filter_apps(apps, *, superuser: bool):
    cleaned = []
    for app in apps:
        if app["app_label"] in ("stores", "auth"):
            continue
        models = []
        for model in app.get("models", []):
            key = (app["app_label"], model.get("object_name", "").lower())
            if key in _HIDDEN_MODELS:
                continue
            models.append(model)
        if not models:
            continue
        app = {**app, "models": models}
        cleaned.append(app)
    return cleaned


def _primary_admin_url(app: dict) -> str | None:
    preferred = _PRIMARY_MODEL.get(app["app_label"])
    models = [m for m in app.get("models", []) if m.get("admin_url")]
    if not models:
        return None
    if preferred:
        for model in models:
            if model.get("object_name", "").lower() == preferred:
                return model["admin_url"]
    return models[0]["admin_url"]


def get_app_list(self, request, app_label=None):
    apps = _original_get_app_list(self, request, app_label)
    return _filter_apps(apps, superuser=request.user.is_superuser)


def index(self, request, extra_context=None):
    """运营后台首页：直接进入寄养订单列表（方案一）。"""
    if request.user.has_perm("bookings.view_order"):
        return redirect(reverse("admin:bookings_order_changelist"))
    for app in self.get_app_list(request):
        url = _primary_admin_url(app)
        if url:
            return redirect(url)
    return _original_index(self, request, extra_context)


def app_index(self, request, app_label, extra_context=None):
    """原应用索引页仅重复列出模型，改为 302 到主模型列表。"""
    if app_label == "stores":
        return redirect("admin:index")
    for app in self.get_app_list(request):
        if app["app_label"] != app_label:
            continue
        url = _primary_admin_url(app)
        if url:
            return redirect(url)
        break
    raise Http404(f"No admin models available for app {app_label}")


def formfield_for_dbfield(self, db_field, request, **kwargs):
    """去掉外键旁的 编辑/新增/删除/查看 小图标。"""
    formfield = _original_formfield_for_dbfield(self, db_field, request, **kwargs)
    widget = getattr(formfield, "widget", None)
    if widget is not None and hasattr(widget, "can_add_related"):
        widget.can_add_related = False
        widget.can_change_related = False
        widget.can_delete_related = False
        widget.can_view_related = False
    return formfield


def patch_admin_nav() -> None:
    AdminSite.get_app_list = get_app_list
    AdminSite.index = index
    AdminSite.app_index = app_index
    ModelAdmin.formfield_for_dbfield = formfield_for_dbfield
