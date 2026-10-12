from .models import Store


def stores(request):
    allowed = getattr(request, "allowed_stores", None)
    if allowed is None:
        allowed = Store.objects.filter(is_active=True)
    return {
        "CURRENT_STORE": getattr(request, "store", None),
        "ALL_STORES": allowed,
    }
