"""订单在线收款 / 退款编排。"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.bookings.models import Payment

from .gateways import NotifyPayload, PaymentGatewayError, get_gateway

logger = logging.getLogger(__name__)


class CheckoutError(Exception):
    pass


@transaction.atomic
def start_checkout(order, method: str, request):
    """创建待确认的在线收款流水并返回渠道会话。门店现金/刷卡请继续使用 Order.pay。"""
    if method not in (Payment.Method.WECHAT, Payment.Method.ALIPAY):
        raise CheckoutError("请选择微信或支付宝")
    if not order.can_pay:
        raise CheckoutError("该订单当前无需支付")
    # 作废同订单未完成的待支付流水，避免重复扫码
    order.payments.filter(kind=Payment.Kind.PAY, status=Payment.Status.PENDING).update(
        status=Payment.Status.FAILED, updated_at=timezone.now()
    )
    payment = Payment.objects.create(
        order=order,
        method=method,
        kind=Payment.Kind.PAY,
        amount=order.balance_due,
        status=Payment.Status.PENDING,
    )
    gateway = get_gateway(method)
    notify_url = request.build_absolute_uri(reverse("payments:notify", args=[method]))
    return_url = request.build_absolute_uri(reverse("payments:return", args=[payment.pk]))
    session = gateway.create_checkout(payment, notify_url=notify_url, return_url=return_url, request=request)
    if session.qr_content:
        request.session[f"pay_qr:{payment.pk}"] = session.qr_content
    if session.hint:
        request.session[f"pay_hint:{payment.pk}"] = session.hint
    return payment, session


@transaction.atomic
def settle_payment(payment: Payment, provider_trade_no: str = "") -> Payment:
    """渠道确认成功后入账。"""
    payment = Payment.objects.select_for_update().select_related("order").get(pk=payment.pk)
    if payment.status == Payment.Status.SUCCESS:
        return payment
    if payment.status != Payment.Status.PENDING or payment.kind != Payment.Kind.PAY:
        raise CheckoutError("流水状态不可入账")
    order = payment.order
    if not order.can_pay and order.balance_due <= 0:
        payment.status = Payment.Status.FAILED
        payment.save(update_fields=["status", "updated_at"])
        raise CheckoutError("订单已无需支付")
    if payment.amount != order.balance_due:
        # 允许因并发改价导致金额不一致时失败，要求重新发起
        payment.status = Payment.Status.FAILED
        payment.save(update_fields=["status", "updated_at"])
        raise CheckoutError("支付金额与订单应付不一致，请重新发起支付")
    top_up = order.payment_status == order.PaymentStatus.PARTIAL
    payment.status = Payment.Status.SUCCESS
    if provider_trade_no:
        payment.provider_trade_no = provider_trade_no
    payment.save(update_fields=["status", "provider_trade_no", "updated_at"])
    order._sync_payment_status()
    order.paid_at = timezone.now()
    order.save(update_fields=["payment_status", "paid_at", "updated_at"])
    title = "补款成功" if top_up else "支付成功"
    order._notify(title, f"订单 {order} 已支付 ¥{payment.amount}，期待 {order.pet.name} 的到来。", "success")
    if not top_up:
        from apps.loyalty.services import award_points

        award_points(order.owner, payment.amount, order=order)
    return payment


def apply_notify(method: str, request) -> tuple[Payment, str]:
    """处理异步通知，返回 (payment, 渠道应答正文)。"""
    gateway = get_gateway(method)
    payload: NotifyPayload = gateway.parse_notify(request)
    if not payload.success:
        raise CheckoutError("渠道返回未成功")
    try:
        payment = Payment.objects.select_related("order").get(transaction_no=payload.out_trade_no)
    except Payment.DoesNotExist as exc:
        raise CheckoutError("找不到对应流水") from exc
    if payment.amount != payload.amount:
        raise CheckoutError("回调金额不匹配")
    settle_payment(payment, payload.provider_trade_no)
    if method == "wechat" and not getattr(gateway, "name", "") == "sandbox":
        return payment, "<xml><return_code><![CDATA[SUCCESS]]></return_code></xml>"
    return payment, "success"


@transaction.atomic
def gateway_refund(order, amount: Decimal) -> Payment | None:
    """通过原支付渠道退款并记账；无成功收款时返回 None。

    渠道失败时仍登记 SUCCESS 退款流水（账本正确），provider_trade_no 标记 RETRY- 供定时任务重试。
    """
    if amount <= 0:
        return None
    last_pay = (
        order.payments.filter(kind=Payment.Kind.PAY, status=Payment.Status.SUCCESS)
        .order_by("-pk")
        .select_for_update()
        .first()
    )
    method = last_pay.method if last_pay else Payment.Method.CASH
    refund = Payment.objects.create(
        order=order,
        method=method,
        kind=Payment.Kind.REFUND,
        amount=amount,
        status=Payment.Status.PENDING,
    )
    if method in (Payment.Method.WECHAT, Payment.Method.ALIPAY) and last_pay:
        try:
            gateway = get_gateway(method)
            provider_no = gateway.refund(last_pay, refund)
            refund.provider_trade_no = provider_no
            refund.last_error = ""
        except PaymentGatewayError as exc:
            logger.warning("渠道退款失败 order=%s refund=%s: %s", order, refund.transaction_no, exc)
            refund.provider_trade_no = f"{Payment.RETRY_PREFIX}{refund.transaction_no}"
            refund.last_error = str(exc)[:200]
    refund.status = Payment.Status.SUCCESS
    refund.save(update_fields=["status", "provider_trade_no", "last_error", "updated_at"])
    return refund


@transaction.atomic
def retry_refund(payment: Payment) -> bool:
    """重试一条标记为 RETRY- 的退款流水；成功返回 True。"""
    payment = Payment.objects.select_for_update().select_related("order").get(pk=payment.pk)
    if payment.kind != Payment.Kind.REFUND or not payment.provider_trade_no.startswith(Payment.RETRY_PREFIX):
        return False
    if payment.method not in (Payment.Method.WECHAT, Payment.Method.ALIPAY):
        return False
    last_pay = (
        payment.order.payments.filter(kind=Payment.Kind.PAY, status=Payment.Status.SUCCESS, method=payment.method)
        .order_by("-pk")
        .first()
    )
    if not last_pay:
        return False
    payment.retry_count += 1
    try:
        gateway = get_gateway(payment.method)
        # 支付宝：先查单，已退成功则直接落账
        if payment.method == Payment.Method.ALIPAY and hasattr(gateway, "query_refund"):
            try:
                node = gateway.query_refund(last_pay, payment)
                if node.get("refund_status") == "REFUND_SUCCESS" or Decimal(node.get("refund_amount") or 0) >= payment.amount:
                    payment.provider_trade_no = node.get("trade_no") or last_pay.provider_trade_no or payment.transaction_no
                    payment.last_error = ""
                    payment.save(update_fields=["provider_trade_no", "last_error", "retry_count", "updated_at"])
                    return True
            except PaymentGatewayError:
                pass
        provider_no = gateway.refund(last_pay, payment)
        payment.provider_trade_no = provider_no
        payment.last_error = ""
        payment.save(update_fields=["provider_trade_no", "last_error", "retry_count", "updated_at"])
        return True
    except PaymentGatewayError as exc:
        payment.last_error = str(exc)[:200]
        payment.save(update_fields=["last_error", "retry_count", "updated_at"])
        logger.warning("退款重试失败 %s: %s", payment.transaction_no, exc)
        return False


def retry_pending_refunds(*, limit: int = 50, max_retries: int = 8) -> int:
    """批量重试渠道退款，返回成功条数。"""
    qs = (
        Payment.objects.filter(
            kind=Payment.Kind.REFUND,
            status=Payment.Status.SUCCESS,
            provider_trade_no__startswith=Payment.RETRY_PREFIX,
            retry_count__lt=max_retries,
        )
        .order_by("pk")[:limit]
    )
    ok = 0
    for payment in qs:
        if retry_refund(payment):
            ok += 1
    return ok
