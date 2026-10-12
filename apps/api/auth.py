from functools import wraps

from django.http import JsonResponse

from .models import ApiToken


def api_json(data=None, *, status=200, error: str = "", code: str = ""):
    body = {"ok": status < 400}
    if error:
        body["error"] = error
        if code:
            body["code"] = code
    if data is not None:
        body["data"] = data
    return JsonResponse(body, status=status, json_dumps_params={"ensure_ascii": False})


def parse_json(request) -> dict:
    import json

    if not request.body:
        return {}
    try:
        data = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("JSON 无效") from exc
    return data if isinstance(data, dict) else {}


def authenticate_request(request):
    """支持 Bearer Token 或已登录 Session（业主 / 员工）。"""
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if header.lower().startswith("bearer "):
        key = header[7:].strip()
        token = ApiToken.objects.select_related("user").filter(key=key, is_active=True).first()
        if token is None:
            return None
        token.touch()
        request.api_token = token
        return token.user
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return user
    return None


def api_login_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = authenticate_request(request)
        if user is None:
            return api_json(error="未授权，请提供 Authorization: Bearer <token> 或先登录", code="unauthorized", status=401)
        request.api_user = user
        return view(request, *args, **kwargs)

    return wrapper


def api_owner_required(view):
    @wraps(view)
    @api_login_required
    def wrapper(request, *args, **kwargs):
        owner = getattr(request.api_user, "owner_profile", None)
        if owner is None:
            return api_json(error="需要业主账号", code="owner_required", status=403)
        request.api_owner = owner
        return view(request, *args, **kwargs)

    return wrapper


def api_staff_required(view):
    @wraps(view)
    @api_login_required
    def wrapper(request, *args, **kwargs):
        if not request.api_user.is_staff:
            return api_json(error="需要员工权限", code="staff_required", status=403)
        return view(request, *args, **kwargs)

    return wrapper
