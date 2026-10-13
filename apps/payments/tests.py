from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.bookings.models import Order, Payment
from apps.testing import PASSWORD, make_order, make_owner, make_pet, make_room


class OneClickPayTests(TestCase):
    def setUp(self):
        self.owner = make_owner(phone="13900001111")
        self.pet = make_pet(owner=self.owner)
        self.room = make_room()
        self.client.login(username=self.owner.user.username, password=PASSWORD)

    def test_checkout_settles_immediately(self):
        order = make_order(pet=self.pet, room=self.room, source=Order.Source.ONLINE, start=2)
        response = self.client.post(reverse("web:order_pay", args=[order.order_no]))
        self.assertRedirects(response, order.get_absolute_url(), fetch_redirect_response=False)
        order.refresh_from_db()
        payment = order.payments.get()
        self.assertEqual(payment.status, Payment.Status.SUCCESS)
        self.assertEqual(payment.method, Payment.Method.ONLINE)
        self.assertEqual(order.payment_status, Order.PaymentStatus.PAID)
        self.assertEqual(order.net_paid, order.amount)

    def test_cannot_pay_twice(self):
        order = make_order(pet=self.pet, room=self.room, start=3)
        order.pay(Payment.Method.CASH)
        response = self.client.post(reverse("web:order_pay", args=[order.order_no]))
        self.assertRedirects(response, order.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(order.payments.count(), 1)
