from django.conf import settings


def site(request):
    unread = 0
    if request.user.is_authenticated and not request.path.startswith("/admin/"):
        unread = request.user.notifications.filter(is_read=False).count()
    return {
        "SITE": {
            "name": settings.SITE_NAME,
            "slogan": settings.SITE_SLOGAN,
            "phone": settings.SITE_PHONE,
            "address": settings.SITE_ADDRESS,
            "hours": settings.SITE_HOURS,
            "icp": settings.SITE_ICP,
            "payment_sandbox": settings.PAYMENT_SANDBOX,
            "long_stay_days": settings.LONG_STAY_DAYS,
            "long_stay_rate": f"{settings.LONG_STAY_RATE * 10:g}",
        },
        "unread_notifications": unread,
    }
