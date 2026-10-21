from django.conf import settings


def site(request):
    return {
        "SITE": {
            "name": settings.SITE_NAME,
            "slogan": settings.SITE_SLOGAN,
            "phone": settings.SITE_PHONE,
            "address": settings.SITE_ADDRESS,
            "hours": settings.SITE_HOURS,
            "icp": settings.SITE_ICP,
            "payment_sandbox": settings.PAYMENT_SANDBOX,
        },
    }
