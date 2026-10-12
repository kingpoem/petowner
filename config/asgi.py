import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
from django.core.asgi import get_asgi_application

import config.db  # noqa: F401

application = get_asgi_application()
