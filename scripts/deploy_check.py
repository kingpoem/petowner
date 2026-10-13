"""以生产配置运行 Django 部署安全检查（manage.py check --deploy）。

未设置的生产变量会用占位值补齐，仅用于检查，不会写入 .env。
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.update(
    DJANGO_SETTINGS_MODULE="config.settings",
    DJANGO_DEBUG="false",
    DJANGO_SECRET_KEY=os.environ.get("DJANGO_SECRET_KEY") or "check-only-" + "x" * 50,
    DJANGO_HSTS_SECONDS=os.environ.get("DJANGO_HSTS_SECONDS") or "31536000",
    EMAIL_HOST=os.environ.get("EMAIL_HOST") or "smtp.example.com",
    # 部署检查默认按沙箱支付，避免未配渠道密钥时误报；上线真实支付请在环境中设 PAYMENT_SANDBOX=false
    PAYMENT_SANDBOX=os.environ.get("PAYMENT_SANDBOX") or "true",
)
if not os.environ.get("SMS_BACKEND"):
    os.environ.update(
        SMS_BACKEND="aliyun",
        SMS_ACCESS_KEY_ID="check-only",
        SMS_ACCESS_KEY_SECRET="check-only",
        SMS_SIGN_NAME="check-only",
        SMS_TEMPLATE_CODE="SMS_000000",
    )

from django.core.management import execute_from_command_line  # noqa: E402

import config.db  # noqa: E402, F401

execute_from_command_line(["manage.py", "check", "--deploy", "--fail-level", "WARNING"])
