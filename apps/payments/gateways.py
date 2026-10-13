"""支付渠道适配。沙箱走本站确认页；生产环境按配置调用微信 Native / 支付宝电脑网站支付。"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)


@dataclass
class CheckoutSession:
    mode: str  # qr | redirect | form
    payment_id: int
    url: str = ""
    qr_content: str = ""
    form_html: str = ""
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


def absolute(request, path: str) -> str:
    return request.build_absolute_uri(path)


def get_gateway(method: str):
    if settings.PAYMENT_SANDBOX:
        return SandboxGateway()
    if method == "wechat":
        return WechatNativeGateway()
    if method == "alipay":
        return AlipayPageGateway()
    raise PaymentGatewayError(f"不支持的支付方式：{method}")


class SandboxGateway:
    """模拟扫码支付：跳转确认页，用户点「支付成功」后走本站回调（与真实异步通知同路径）。"""

    name = "sandbox"

    def create_checkout(self, payment, *, notify_url: str, return_url: str, request) -> CheckoutSession:
        token = secrets.token_urlsafe(24)
        payment.provider_trade_no = f"SBX{token[:16]}"
        payment.save(update_fields=["provider_trade_no"])
        request.session[f"pay_token:{payment.pk}"] = token
        return CheckoutSession(
            mode="qr",
            payment_id=payment.pk,
            url=reverse("payments:sandbox", args=[payment.pk]),
            qr_content=absolute(request, reverse("payments:sandbox", args=[payment.pk])),
            hint="沙箱环境：扫码或点击下方按钮完成模拟支付，不会产生真实扣款。",
        )

    def refund(self, pay_payment, refund_payment) -> str:
        return f"SBXR{refund_payment.transaction_no}"

    def parse_notify(self, request) -> NotifyPayload:
        data = request.POST if request.method == "POST" else request.GET
        out_trade_no = data.get("out_trade_no", "")
        token = data.get("token", "")
        amount = Decimal(data.get("amount") or "0")
        return NotifyPayload(
            out_trade_no=out_trade_no,
            provider_trade_no=data.get("provider_trade_no", ""),
            amount=amount,
            success=data.get("result") == "SUCCESS" and bool(token),
            raw=str(dict(data)),
        )


class WechatNativeGateway:
    """微信支付 Native（统一下单 V2），需配置 WECHAT_APP_ID / WECHAT_MCH_ID / WECHAT_API_KEY。"""

    name = "wechat"
    API = "https://api.mch.weixin.qq.com/pay/unifiedorder"
    REFUND_API = "https://api.mch.weixin.qq.com/secapi/pay/refund"

    def __init__(self):
        self.app_id = settings.WECHAT_APP_ID
        self.mch_id = settings.WECHAT_MCH_ID
        self.api_key = settings.WECHAT_API_KEY
        if not (self.app_id and self.mch_id and self.api_key):
            raise PaymentGatewayError("未配置微信支付：请设置 WECHAT_APP_ID、WECHAT_MCH_ID、WECHAT_API_KEY")

    def _sign(self, params: dict) -> str:
        items = sorted((k, v) for k, v in params.items() if v not in (None, "") and k != "sign")
        raw = "&".join(f"{k}={v}" for k, v in items) + f"&key={self.api_key}"
        return hashlib.md5(raw.encode()).hexdigest().upper()

    def _xml(self, params: dict) -> str:
        root = ElementTree.Element("xml")
        for key, value in params.items():
            node = ElementTree.SubElement(root, key)
            node.text = str(value)
        return ElementTree.tostring(root, encoding="unicode")

    def _post(self, url: str, params: dict) -> dict:
        params = {**params, "sign": self._sign(params)}
        req = Request(url, data=self._xml(params).encode("utf-8"), headers={"Content-Type": "application/xml"})
        with urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
        root = ElementTree.fromstring(body)
        data = {child.tag: (child.text or "") for child in root}
        if data.get("return_code") != "SUCCESS" or data.get("result_code") != "SUCCESS":
            raise PaymentGatewayError(data.get("err_code_des") or data.get("return_msg") or "微信支付下单失败")
        return data

    def create_checkout(self, payment, *, notify_url: str, return_url: str, request) -> CheckoutSession:
        data = self._post(
            self.API,
            {
                "appid": self.app_id,
                "mch_id": self.mch_id,
                "nonce_str": secrets.token_hex(16),
                "body": f"{settings.SITE_NAME}订单{payment.order.order_no}",
                "out_trade_no": payment.transaction_no,
                "total_fee": str(int(payment.amount * 100)),
                "spbill_create_ip": request.META.get("REMOTE_ADDR", "127.0.0.1"),
                "notify_url": notify_url,
                "trade_type": "NATIVE",
                "product_id": payment.order.order_no,
            },
        )
        code_url = data["code_url"]
        return CheckoutSession(
            mode="qr",
            payment_id=payment.pk,
            qr_content=code_url,
            url=reverse("payments:checkout", args=[payment.pk]),
            hint="请使用微信扫一扫完成支付",
        )

    def refund(self, pay_payment, refund_payment) -> str:
        """调用 secapi/pay/refund；需配置商户 API 证书与私钥路径。"""
        cert = settings.WECHAT_CERT_PATH
        key = settings.WECHAT_KEY_PATH or cert.replace("apiclient_cert", "apiclient_key")
        if not cert:
            raise PaymentGatewayError("微信退款需配置 WECHAT_CERT_PATH（apiclient_cert.pem）")
        from pathlib import Path

        if not Path(cert).is_file() or not Path(key).is_file():
            raise PaymentGatewayError("微信退款证书或私钥文件不存在，请检查 WECHAT_CERT_PATH / WECHAT_KEY_PATH")
        total = pay_payment.amount
        data = self._post_secure(
            self.REFUND_API,
            {
                "appid": self.app_id,
                "mch_id": self.mch_id,
                "nonce_str": secrets.token_hex(16),
                "out_trade_no": pay_payment.transaction_no,
                "out_refund_no": refund_payment.transaction_no,
                "total_fee": str(int(total * 100)),
                "refund_fee": str(int(refund_payment.amount * 100)),
                "refund_desc": f"{settings.SITE_NAME}订单退款",
            },
            cert=cert,
            key=key,
        )
        return data.get("refund_id") or data.get("out_refund_no") or refund_payment.transaction_no

    def _post_secure(self, url: str, params: dict, *, cert: str, key: str) -> dict:
        import ssl
        from urllib.request import urlopen

        params = {**params, "sign": self._sign(params)}
        body = self._xml(params).encode("utf-8")
        ctx = ssl.create_default_context()
        ctx.load_cert_chain(certfile=cert, keyfile=key)
        req = Request(url, data=body, headers={"Content-Type": "application/xml"}, method="POST")
        with urlopen(req, timeout=20, context=ctx) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
        root = ElementTree.fromstring(raw)
        data = {child.tag: (child.text or "") for child in root}
        if data.get("return_code") != "SUCCESS" or data.get("result_code") != "SUCCESS":
            raise PaymentGatewayError(data.get("err_code_des") or data.get("return_msg") or "微信退款失败")
        return data

    def parse_notify(self, request) -> NotifyPayload:
        root = ElementTree.fromstring(request.body.decode("utf-8"))
        data = {child.tag: (child.text or "") for child in root}
        sign = data.pop("sign", "")
        if self._sign(data) != sign:
            raise PaymentGatewayError("微信回调签名校验失败")
        return NotifyPayload(
            out_trade_no=data.get("out_trade_no", ""),
            provider_trade_no=data.get("transaction_id", ""),
            amount=Decimal(data.get("total_fee", "0")) / 100,
            success=data.get("return_code") == "SUCCESS" and data.get("result_code") == "SUCCESS",
            raw=json.dumps(data, ensure_ascii=False),
        )


class AlipayPageGateway:
    """支付宝电脑网站支付（RSA2）。需 ALIPAY_APP_ID、ALIPAY_PRIVATE_KEY、ALIPAY_PUBLIC_KEY。"""

    name = "alipay"
    GATEWAY = "https://openapi.alipay.com/gateway.do"

    def __init__(self):
        self.app_id = settings.ALIPAY_APP_ID
        self.private_key = settings.ALIPAY_PRIVATE_KEY.replace("\\n", "\n")
        self.public_key = settings.ALIPAY_PUBLIC_KEY.replace("\\n", "\n")
        if not (self.app_id and self.private_key and self.public_key):
            raise PaymentGatewayError("未配置支付宝：请设置 ALIPAY_APP_ID、ALIPAY_PRIVATE_KEY、ALIPAY_PUBLIC_KEY")

    def _sign(self, content: str) -> str:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        key = serialization.load_pem_private_key(self._pem(self.private_key, "PRIVATE").encode(), password=None)
        signature = key.sign(content.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
        import base64

        return base64.b64encode(signature).decode()

    def _verify(self, content: str, signature: str) -> bool:
        import base64

        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        key = serialization.load_pem_public_key(self._pem(self.public_key, "PUBLIC").encode())
        try:
            key.verify(base64.b64decode(signature), content.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
            return True
        except Exception:
            return False

    @staticmethod
    def _pem(raw: str, kind: str) -> str:
        if "BEGIN" in raw:
            return raw
        lines = [raw[i : i + 64] for i in range(0, len(raw), 64)]
        return f"-----BEGIN {kind} KEY-----\n" + "\n".join(lines) + f"\n-----END {kind} KEY-----"

    def create_checkout(self, payment, *, notify_url: str, return_url: str, request) -> CheckoutSession:
        biz = {
            "out_trade_no": payment.transaction_no,
            "product_code": "FAST_INSTANT_TRADE_PAY",
            "total_amount": f"{payment.amount:.2f}",
            "subject": f"{settings.SITE_NAME} {payment.order.order_no}",
        }
        params = {
            "app_id": self.app_id,
            "method": "alipay.trade.page.pay",
            "format": "JSON",
            "charset": "utf-8",
            "sign_type": "RSA2",
            "timestamp": timezone.localtime().strftime("%Y-%m-%d %H:%M:%S"),
            "version": "1.0",
            "notify_url": notify_url,
            "return_url": return_url,
            "biz_content": json.dumps(biz, separators=(",", ":"), ensure_ascii=False),
        }
        unsigned = "&".join(f"{k}={params[k]}" for k in sorted(params))
        params["sign"] = self._sign(unsigned)
        query = urlencode(params, quote_via=quote_plus)
        form = (
            f'<form id="alipay" method="get" action="{self.GATEWAY}">'
            + "".join(f'<input type="hidden" name="{k}" value="{v}">' for k, v in params.items())
            + "</form><script>document.getElementById('alipay').submit()</script>"
        )
        return CheckoutSession(
            mode="form",
            payment_id=payment.pk,
            url=f"{self.GATEWAY}?{query}",
            form_html=form,
            hint="正在跳转支付宝…",
        )

    def _alipay_api(self, method: str, biz: dict) -> dict:
        params = {
            "app_id": self.app_id,
            "method": method,
            "format": "JSON",
            "charset": "utf-8",
            "sign_type": "RSA2",
            "timestamp": timezone.localtime().strftime("%Y-%m-%d %H:%M:%S"),
            "version": "1.0",
            "biz_content": json.dumps(biz, separators=(",", ":"), ensure_ascii=False),
        }
        unsigned = "&".join(f"{k}={params[k]}" for k in sorted(params))
        params["sign"] = self._sign(unsigned)
        req = Request(self.GATEWAY, data=urlencode(params).encode(), method="POST")
        with urlopen(req, timeout=20) as resp:  # noqa: S310
            body = json.loads(resp.read().decode())
        key = method.replace(".", "_") + "_response"
        return body.get(key, {})

    def refund(self, pay_payment, refund_payment) -> str:
        """调用 alipay.trade.refund；优先传渠道 trade_no，失败可配合 query_refund 对账。"""
        biz = {
            "refund_amount": f"{refund_payment.amount:.2f}",
            "out_request_no": refund_payment.transaction_no,
            "refund_reason": f"{settings.SITE_NAME}订单退款",
        }
        if pay_payment.provider_trade_no:
            biz["trade_no"] = pay_payment.provider_trade_no
        else:
            biz["out_trade_no"] = pay_payment.transaction_no
        node = self._alipay_api("alipay.trade.refund", biz)
        if node.get("code") != "10000":
            raise PaymentGatewayError(node.get("sub_msg") or node.get("msg") or "支付宝退款失败")
        return node.get("trade_no") or node.get("out_trade_no") or refund_payment.transaction_no

    def query_refund(self, pay_payment, refund_payment) -> dict:
        """查询退款结果，供重试任务对账。"""
        biz = {"out_request_no": refund_payment.transaction_no}
        if pay_payment.provider_trade_no:
            biz["trade_no"] = pay_payment.provider_trade_no
        else:
            biz["out_trade_no"] = pay_payment.transaction_no
        node = self._alipay_api("alipay.trade.fastpay.refund.query", biz)
        if node.get("code") != "10000":
            raise PaymentGatewayError(node.get("sub_msg") or node.get("msg") or "支付宝退款查询失败")
        return node

    def parse_notify(self, request) -> NotifyPayload:
        data = {k: v for k, v in request.POST.items()}
        sign = data.pop("sign", "")
        data.pop("sign_type", None)
        unsigned = "&".join(f"{k}={data[k]}" for k in sorted(data))
        if not self._verify(unsigned, sign):
            raise PaymentGatewayError("支付宝回调签名校验失败")
        return NotifyPayload(
            out_trade_no=data.get("out_trade_no", ""),
            provider_trade_no=data.get("trade_no", ""),
            amount=Decimal(data.get("total_amount") or "0"),
            success=data.get("trade_status") in {"TRADE_SUCCESS", "TRADE_FINISHED"},
            raw=json.dumps(data, ensure_ascii=False),
        )


def verify_sandbox_token(request, payment) -> bool:
    expected = request.session.get(f"pay_token:{payment.pk}")
    token = request.POST.get("token") or request.GET.get("token")
    return bool(expected and token and hmac.compare_digest(expected, token))
