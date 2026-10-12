from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.payments"
    verbose_name = "在线支付"

    def ready(self):
        from . import checks  # noqa: F401
