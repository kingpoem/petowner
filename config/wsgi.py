"""
WSGI config for config project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/wsgi/
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
from django.core.wsgi import get_wsgi_application

import config.db  # noqa: F401 — 注册 PyMySQL

application = get_wsgi_application()
