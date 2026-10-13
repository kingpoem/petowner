from django.contrib import messages
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.bookings.models import Payment
from apps.web.views import owner_required

from .gateways import verify_sandbox_token
from .services import settle_payment


@owner_required
@require_http_methods(["GET", "POST"])
def sandbox_pay(request, payment_id):
    payment = get_object_or_404(
        Payment.objects.select_related("order__pet__owner"),
        pk=payment_id,
        order__pet__owner=request.owner,
        kind=Payment.Kind.PAY,
    )
    if payment.status == Payment.Status.SUCCESS:
        return redirect(payment.order)
    token = request.session.get(f"pay_token:{payment.pk}", "")
    if request.method == "POST":
        if not verify_sandbox_token(request, payment):
            return HttpResponseForbidden("无效的支付令牌")
        settle_payment(payment, payment.provider_trade_no or f"SBX-{payment.transaction_no}")
        messages.success(request, f"支付成功，流水号 {payment.transaction_no}")
        return redirect(payment.order)
    return render(request, "payments/sandbox.html", {"payment": payment, "order": payment.order, "token": token})
