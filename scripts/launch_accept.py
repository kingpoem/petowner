"""上线前验收：关键路由可达、支付沙箱、短信与域名配置自检。

用法：uv run python scripts/launch_accept.py
退出码 0 = 通过；非 0 = 有阻断项。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import config.db  # noqa: E402, F401
import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.test import Client  # noqa: E402
from django.urls import reverse  # noqa: E402


def check(name: str, ok: bool, detail: str = "") -> bool:
    mark = "OK" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    fails = 0
    host = settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS else "localhost"
    if host.startswith("."):
        host = "localhost"
    client = Client(HTTP_HOST=host)

    for label, path in [
        ("首页", "/"),
        ("房间列表", "/rooms/"),
        ("健康检查", "/healthz"),
        ("登录页", reverse("web:login")),
    ]:
        try:
            resp = client.get(path)
            ok = 200 <= resp.status_code < 400
            fails += 0 if check(label, ok, f"HTTP {resp.status_code}") else 1
        except Exception as exc:  # noqa: BLE001
            fails += 0 if check(label, False, str(exc)) else 1

    secure_key = not str(settings.SECRET_KEY).startswith("django-insecure-")
    if settings.DEBUG:
        if not secure_key:
            print("[WARN] SECRET_KEY 仍为开发占位（生产必须更换）")
        else:
            check("SECRET_KEY", True)
        print("[WARN] DJANGO_DEBUG=true（生产应关闭）")
    else:
        fails += 0 if check("SECRET_KEY 非开发占位", secure_key) else 1
        check("DEBUG 关闭", True)

    fails += 0 if check("ALLOWED_HOSTS 已配置", bool(settings.ALLOWED_HOSTS)) else 1

    if settings.PAYMENT_SANDBOX:
        print("[WARN] PAYMENT_SANDBOX=true（真实收款前请关闭并配置微信/支付宝密钥）")
    else:
        fails += 0 if check("微信支付配置", bool(settings.WECHAT_APP_ID and settings.WECHAT_MCH_ID and settings.WECHAT_API_KEY)) else 1
        fails += 0 if check(
            "支付宝配置", bool(settings.ALIPAY_APP_ID and settings.ALIPAY_PRIVATE_KEY and settings.ALIPAY_PUBLIC_KEY)
        ) else 1
        fails += 0 if check("微信退款证书", bool(settings.WECHAT_CERT_PATH)) else 1

    if settings.SMS_BACKEND == "console":
        print("[WARN] SMS_BACKEND=console（生产请改 aliyun 并配置模板）")
    else:
        fails += 0 if check("短信配置", bool(settings.SMS_ACCESS_KEY_ID and settings.SMS_SIGN_NAME)) else 1

    print()
    if fails:
        print(f"验收未通过：{fails} 项阻断。详见 .env.example 与 docs/LAUNCH.md")
        return 1
    print("验收通过（警告项请上线前人工确认）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
