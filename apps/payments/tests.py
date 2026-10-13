from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.bookings.models import Order, Payment
from apps.payments.gateways import PaymentGatewayError
from apps.payments.services import gateway_refund, retry_refund
from apps.testing import PASSWORD, make_order, make_owner, make_pet, make_room


@override_settings(PAYMENT_SANDBOX=True)
class SandboxCheckoutTests(TestCase):
    def setUp(self):
        self.owner = make_owner(phone="13900001111")
        self.pet = make_pet(owner=self.owner)
        self.room = make_room()
        self.client.login(username=self.owner.user.username, password=PASSWORD)

    def test_checkout_and_settle(self):
        order = make_order(pet=self.pet, room=self.room, source=Order.Source.ONLINE, start=2)
        response = self.client.post(reverse("web:order_pay", args=[order.order_no]), {"method": "wechat"})
        self.assertIn("/pay/sandbox/", response["Location"])
        payment = order.payments.get()
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(order.net_paid, Decimal("0.00"))
        token = self.client.session[f"pay_token:{payment.pk}"]
        self.client.post(response["Location"], {"token": token})
        order.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.SUCCESS)
        self.assertEqual(order.payment_status, Order.PaymentStatus.PAID)

    def test_pending_does_not_count_as_paid(self):
        order = make_order(pet=self.pet, room=self.room, start=3)
        response = self.client.post(reverse("web:order_pay", args=[order.order_no]), {"method": "wechat"})
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.net_paid, 0)
        self.assertTrue(order.can_pay)
        self.assertEqual(order.payments.filter(status=Payment.Status.PENDING).count(), 1)

    def test_refund_marks_retry_and_can_succeed(self):
        order = make_order(pet=self.pet, room=self.room, start=4)
        order.pay(Payment.Method.WECHAT)
        with patch("apps.payments.services.get_gateway") as gw:
            gateway = gw.return_value
            gateway.refund.side_effect = PaymentGatewayError("cert missing")
            refund = gateway_refund(order, Decimal("50.00"))
        self.assertTrue(refund.provider_trade_no.startswith(Payment.RETRY_PREFIX))
        self.assertIn("cert", refund.last_error)
        with patch("apps.payments.services.get_gateway") as gw:
            gateway = gw.return_value
            gateway.refund.return_value = "WXREFUND1"
            self.assertTrue(retry_refund(refund))
        refund.refresh_from_db()
        self.assertEqual(refund.provider_trade_no, "WXREFUND1")
        self.assertEqual(refund.retry_count, 1)
