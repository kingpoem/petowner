from .access import allowed_stores_for, resolve_store
from .models import Store


class CurrentStoreMiddleware:
    """解析当前门店：?store=编码 或 session；员工受 StaffStore 约束。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        code = request.GET.get("store") or request.session.get("current_store")
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.is_staff:
            allowed = allowed_stores_for(user)
            request.allowed_stores = allowed
            store = resolve_store(user, code)
        else:
            request.allowed_stores = Store.objects.filter(is_active=True)
            store = None
            if code:
                store = Store.objects.filter(code=code, is_active=True).first()
            if store is None:
                store = (
                    Store.objects.filter(is_default=True, is_active=True).first()
                    or Store.objects.filter(is_active=True).first()
                )
        request.store = store
        if store and request.GET.get("store") == store.code:
            request.session["current_store"] = store.code
        return self.get_response(request)
