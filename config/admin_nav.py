"""精简后台导航：取消应用空壳索引页，直达主模型列表；隐藏门店管理入口。"""

from django.contrib.admin.sites import AdminSite
from django.http import Http404
from django.shortcuts import redirect

# 每个应用优先落到的模型（object_name 小写）
_PRIMARY_MODEL = {
    "bookings": "order",
    "pets": "pet",
    "care": "servicerecord",
    "rooms": "room",
    "hospitality": "caretask",
    "auth": "user",
}

_original_get_app_list = AdminSite.get_app_list


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


def patch_admin_nav() -> None:
    AdminSite.app_index = app_index
