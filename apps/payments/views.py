import segno
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.bookings.models import Payment
from apps.web.views import owner_required

from .gateways import PaymentGatewayError, verify_sandbox_token
from .services import CheckoutError, apply_notify, settle_payment


@owner_required
@require_GET
def checkout(request, payment_id):
    payment = get_object_or_404(
        Payment.objects.select_related("order__pet__owner"),
        pk=payment_id,
        kind=Payment.Kind.PAY,
        order__pet__owner=request.owner,
    )
    if payment.status == Payment.Status.SUCCESS:
        messages.success(request, "支付已完成")
        return redirect(payment.order)
    if payment.status != Payment.Status.PENDING:
        messages.warning(request, "该支付已关闭，请重新发起")
        return redirect("web:order_pay", order_no=payment.order.order_no)
    if payment.provider_trade_no.startswith("SBX"):
        return redirect("payments:sandbox", payment_id=payment.pk)
    return render(
        request,
        "payments/checkout.html",
        {
            "payment": payment,
            "order": payment.order,
            "qr_content": request.session.get(f"pay_qr:{payment.pk}", ""),
            "hint": request.session.get(f"pay_hint:{payment.pk}", "请完成支付"),
        },
    )


@owner_required
@require_GET
def qr_image(request, payment_id):
    payment = get_object_or_404(Payment, pk=payment_id, order__pet__owner=request.owner)
    content = request.session.get(f"pay_qr:{payment.pk}") or payment.provider_trade_no
    if not content:
        return HttpResponseBadRequest("二维码已失效")
    qr = segno.make(content, error="m")
    response = HttpResponse(content_type="image/png")
    qr.save(response, kind="png", scale=6, border=1)
    return response


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
            return HttpResponseForbidden("无效的沙箱支付令牌")
        settle_payment(payment, payment.provider_trade_no or f"SBX-{payment.transaction_no}")
        messages.success(request, f"支付成功，流水号 {payment.transaction_no}")
        return redirect(payment.order)
    return render(request, "payments/sandbox.html", {"payment": payment, "order": payment.order, "token": token})


@csrf_exempt
@require_POST
def notify(request, method):
    try:
        _payment, body = apply_notify(method, request)
    except (CheckoutError, PaymentGatewayError, Payment.DoesNotExist) as exc:
        return HttpResponseBadRequest(str(exc))
    return HttpResponse(body)


@login_required
@require_GET
def return_pay(request, payment_id):
    payment = get_object_or_404(Payment.objects.select_related("order__pet__owner"), pk=payment_id)
    owner = getattr(request.user, "owner_profile", None)
    if not request.user.is_staff and (owner is None or payment.order.pet.owner_id != owner.pk):
        return HttpResponseForbidden()
    if payment.status == Payment.Status.PENDING:
        messages.info(request, "正在确认支付结果，请稍后刷新订单页")
    elif payment.status == Payment.Status.SUCCESS:
        messages.success(request, "支付成功")
    return redirect(payment.order)
