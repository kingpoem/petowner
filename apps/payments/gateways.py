"""沙箱支付（课程演示）：确认页一点即视为支付成功。"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from decimal import Decimal

from django.urls import reverse


@dataclass
class CheckoutSession:
    mode: str
    payment_id: int
    url: str = ""
    hint: str = ""


@dataclass
class NotifyPayload:
    out_trade_no: str
    provider_trade_no: str
    amount: Decimal
    success: bool
    raw: str = ""


class PaymentGatewayError(Exception):
    pass


class SandboxGateway:
    name = "sandbox"

    def create_checkout(self, payment, *, request) -> CheckoutSession:
        token = secrets.token_urlsafe(24)
        payment.provider_trade_no = f"SBX{token[:16]}"
        payment.save(update_fields=["provider_trade_no"])
        request.session[f"pay_token:{payment.pk}"] = token
        return CheckoutSession(
            mode="form",
            payment_id=payment.pk,
            url=reverse("payments:sandbox", args=[payment.pk]),
            hint="演示环境：点击确认即完成支付，不会产生真实扣款。",
        )

    def parse_notify(self, request) -> NotifyPayload:
        data = request.POST if request.method == "POST" else request.GET
        return NotifyPayload(
            out_trade_no=data.get("out_trade_no", ""),
            provider_trade_no=data.get("provider_trade_no", ""),
            amount=Decimal(data.get("amount") or "0"),
            success=data.get("result") == "SUCCESS" and bool(data.get("token")),
            raw=str(dict(data)),
        )


def verify_sandbox_token(request, payment) -> bool:
    expected = request.session.get(f"pay_token:{payment.pk}", "")
    token = request.POST.get("token") or request.GET.get("token") or ""
    return bool(expected) and secrets.compare_digest(expected, token)
