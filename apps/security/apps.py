from django.apps import AppConfig


class SecurityConfig(AppConfig):
    name = "apps.security"
    verbose_name = "账号安全"

    def ready(self):
        from . import checks  # noqa: F401
