"""订单在线收款（课程版：仅沙箱一键已付）。"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.bookings.models import Payment

from .gateways import SandboxGateway


class CheckoutError(Exception):
    pass


@transaction.atomic
def start_checkout(order, request):
    """创建待确认流水并返回沙箱会话。"""
    if not order.can_pay:
        raise CheckoutError("该订单当前无需支付")
    order.payments.filter(kind=Payment.Kind.PAY, status=Payment.Status.PENDING).update(
        status=Payment.Status.FAILED, updated_at=timezone.now()
    )
    payment = Payment.objects.create(
        order=order,
        method=Payment.Method.ONLINE,
        kind=Payment.Kind.PAY,
        amount=order.balance_due,
        status=Payment.Status.PENDING,
    )
    session = SandboxGateway().create_checkout(payment, request=request)
    return payment, session


@transaction.atomic
def settle_payment(payment: Payment, provider_trade_no: str = "") -> Payment:
    """确认入账。"""
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
        payment.status = Payment.Status.FAILED
        payment.save(update_fields=["status", "updated_at"])
        raise CheckoutError("支付金额与订单应付不一致，请重新发起支付")
    payment.status = Payment.Status.SUCCESS
    if provider_trade_no:
        payment.provider_trade_no = provider_trade_no
    payment.save(update_fields=["status", "provider_trade_no", "updated_at"])
    order._sync_payment_status()
    order.paid_at = timezone.now()
    order.save(update_fields=["payment_status", "paid_at", "updated_at"])
    return payment


@transaction.atomic
def record_refund(order, amount: Decimal) -> Payment | None:
    """记账退款（无真实渠道）。"""
    if amount <= 0:
        return None
    return Payment.objects.create(
        order=order,
        method=Payment.Method.ONLINE,
        kind=Payment.Kind.REFUND,
        amount=amount,
        status=Payment.Status.SUCCESS,
    )
