from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.notifications.models import Notification
from apps.pets.models import Pet, PetSize
from apps.rooms.models import Room
from apps.testing import days, make_order, make_owner, make_pet, make_room

from .models import (
    Order,
    Payment,
    expire_unpaid_orders,
    find_available_rooms,
    is_room_available,
    room_problem_for_pet,
)


class RoomMatchingTests(TestCase):
    def test_species_mismatch(self):
        room = make_room(pet_type=Room.PetType.CAT)
        self.assertEqual(room_problem_for_pet(room, make_pet(), days(3))[0], "room")

    def test_size_limit(self):
        room = make_room(max_pet_size=PetSize.SMALL)
        problem = room_problem_for_pet(room, make_pet(weight=Decimal("30")), days(3))
        self.assertIn("体型超出", problem[1])

    def test_aggressive_pet_needs_single_room(self):
        pet = make_pet(temperament=Pet.Temperament.AGGRESSIVE)
        self.assertIsNotNone(room_problem_for_pet(make_room(capacity=2), pet, days(3)))
        self.assertIsNone(room_problem_for_pet(make_room(capacity=1), pet, days(3)))

    @override_settings(REQUIRE_VACCINE=True)
    def test_vaccine_must_cover_whole_stay(self):
        pet = make_pet(vaccine_expiry=days(2))
        self.assertEqual(room_problem_for_pet(make_room(), pet, days(3))[0], "pet")
        self.assertIsNone(room_problem_for_pet(make_room(), pet, days(2)))

    @override_settings(REQUIRE_VACCINE=False)
    def test_vaccine_check_can_be_disabled(self):
        self.assertIsNone(room_problem_for_pet(make_room(), make_pet(vaccine_expiry=None), days(3)))

    def test_maintenance_room_rejected(self):
        room = make_room(status=Room.Status.MAINTENANCE)
        self.assertIn("维护", room_problem_for_pet(room, make_pet(), days(3))[1])

    def test_find_available_rooms_filters(self):
        pet = make_pet(weight=Decimal("30"))
        small = make_room(max_pet_size=PetSize.SMALL)
        cat = make_room(pet_type=Room.PetType.CAT)
        ok = make_room(pet_type=Room.PetType.DOG, room_type=Room.RoomType.DELUXE)
        hidden = make_room(is_listed=False)
        rooms = find_available_rooms("dog", days(1), days(3), pet=pet)
        self.assertIn(ok, rooms)
        self.assertNotIn(small, rooms)
        self.assertNotIn(cat, rooms)
        self.assertNotIn(hidden, find_available_rooms("dog", days(1), days(3), listed_only=True))
        self.assertEqual(find_available_rooms("dog", days(1), days(3), pet=pet, room_type="deluxe"), [ok])

    def test_find_available_rooms_uses_constant_queries(self):
        rooms = [make_room(capacity=2) for _ in range(6)]
        make_order(room=rooms[0], start=1, nights=2)
        make_order(room=rooms[0], start=1, nights=2)
        make_order(room=rooms[1], start=2, nights=1)
        with self.assertNumQueries(2):
            available = find_available_rooms("dog", days(1), days(3))
        self.assertNotIn(rooms[0], available)
        self.assertIn(rooms[1], available)


class AvailabilityTests(TestCase):
    def test_capacity_counted_per_day(self):
        room = make_room(capacity=2)
        make_order(room=room, start=1, nights=2)  # 第1-2晚
        make_order(room=room, start=3, nights=2)  # 第3-4晚，与上一单不重叠
        self.assertTrue(is_room_available(room, days(1), days(5)))
        make_order(room=room, start=2, nights=2)  # 第2-3晚
        self.assertFalse(is_room_available(room, days(2), days(3)))
        self.assertTrue(is_room_available(room, days(5), days(6)))

    def test_cancelled_orders_release_room(self):
        room = make_room()
        order = make_order(room=room)
        self.assertFalse(is_room_available(room, order.check_in, order.check_out))
        order.cancel()
        self.assertTrue(is_room_available(room, order.check_in, order.check_out))

    def test_full_room_rejected_on_clean(self):
        room = make_room()
        make_order(room=room)
        with self.assertRaises(ValidationError) as ctx:
            make_order(room=room)
        self.assertIn("room", ctx.exception.message_dict)

    def test_same_pet_cannot_double_book(self):
        pet = make_pet()
        make_order(pet=pet)
        with self.assertRaises(ValidationError) as ctx:
            make_order(pet=pet)
        self.assertIn("pet", ctx.exception.message_dict)


class OrderValidationTests(TestCase):
    def test_dates(self):
        with self.assertRaises(ValidationError):
            make_order(start=2, nights=0)
        with self.assertRaises(ValidationError):
            make_order(start=-1, nights=2)

    @override_settings(MAX_BOARDING_DAYS=5)
    def test_max_boarding_days(self):
        with self.assertRaises(ValidationError):
            make_order(nights=6)

    def test_order_no(self):
        order = make_order()
        self.assertRegex(order.order_no, rf"^O\d{{8}}{order.pk:05d}$")
        self.assertEqual(Order.objects.get(pk=order.pk).order_no, order.order_no)

    def test_paid_order_cannot_change_dates(self):
        order = make_order()
        order.pay(Payment.Method.WECHAT)
        order.check_out += timedelta(days=1)
        with self.assertRaises(ValidationError):
            order.full_clean()

    def test_amount_frozen_after_payment(self):
        room = make_room(price=Decimal("100"))
        order = make_order(room=room)
        order.pay(Payment.Method.WECHAT)
        Room.objects.filter(pk=room.pk).update(price=Decimal("999"))
        order.refresh_from_db()
        order.note = "改备注"
        order.save()
        self.assertEqual(order.amount, Decimal("200.00"))


class OrderLifecycleTests(TestCase):
    def setUp(self):
        self.owner = make_owner()
        self.order = make_order(pet=make_pet(owner=self.owner), start=0, nights=3)

    def test_pay_records_payment_and_notifies(self):
        payment = self.order.pay(Payment.Method.ALIPAY)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PAID)
        self.assertIsNotNone(self.order.paid_at)
        self.assertEqual(payment.amount, self.order.amount)
        self.assertTrue(payment.transaction_no.startswith("T"))
        self.assertTrue(Notification.objects.filter(user=self.owner.user, title="支付成功").exists())
        with self.assertRaises(ValidationError):
            self.order.pay(Payment.Method.ALIPAY)

    def test_cancel_paid_order_before_check_in_refunds_in_full(self):
        order = make_order(start=2, nights=3)
        order.pay(Payment.Method.WECHAT)
        order.cancel("行程变更")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(order.payment_status, Order.PaymentStatus.REFUNDED)
        refund = order.payments.get(kind=Payment.Kind.REFUND)
        self.assertEqual(refund.method, Payment.Method.WECHAT)
        self.assertEqual(refund.signed_amount, Decimal("-300.00"))
        self.assertTrue(refund.transaction_no.startswith("R"))
        self.assertEqual(order.cancel_fee, 0)
        self.assertEqual(order.net_paid, 0)

    def test_cancel_unpaid_has_no_refund(self):
        self.order.cancel()
        self.assertFalse(self.order.payments.exists())
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.UNPAID)

    def test_state_machine(self):
        with self.assertRaises(ValidationError):
            self.order.finish_boarding()
        self.order.start_boarding()
        self.assertIsNotNone(self.order.checked_in_at)
        with self.assertRaises(ValidationError):
            self.order.cancel()
        with self.assertRaises(ValidationError):
            self.order.start_boarding()

    def test_early_checkout_shortens_stay_and_frees_room(self):
        self.order.start_boarding()
        with self.captureOnCommitCallbacks(execute=True):
            self.order.finish_boarding()
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.COMPLETED)
        self.assertEqual(self.order.check_out, days(1))
        self.assertTrue(is_room_available(self.order.room, days(1), days(3)))


class MoneyRuleTests(TestCase):
    """取消违约金、提前离店退款、改期多退少补。房价 100/晚。"""

    def test_same_day_cancel_keeps_first_night(self):
        order = make_order(start=0, nights=3)
        order.pay(Payment.Method.ALIPAY)
        self.assertEqual(order.cancellation_fee(), Decimal("100.00"))
        order.cancel()
        order.refresh_from_db()
        self.assertEqual(order.cancel_fee, Decimal("100.00"))
        self.assertEqual(order.amount, Decimal("100.00"))
        self.assertEqual(order.net_paid, Decimal("100.00"))
        self.assertEqual(order.payment_status, Order.PaymentStatus.PAID)
        refund = order.payments.get(kind=Payment.Kind.REFUND)
        self.assertEqual((refund.amount, refund.method), (Decimal("200.00"), Payment.Method.ALIPAY))
        self.assertIn("扣除首晚房费", Notification.objects.get(title="预约已取消").body)

    def test_store_can_waive_cancel_fee(self):
        order = make_order(start=0, nights=2)
        order.pay(Payment.Method.WECHAT)
        order.cancel("门店原因", waive_fee=True)
        self.assertEqual(order.cancel_fee, 0)
        self.assertEqual(order.payment_status, Order.PaymentStatus.REFUNDED)

    @override_settings(LATE_CANCEL_NIGHTS=0)
    def test_free_cancellation_policy(self):
        order = make_order(start=0, nights=2)
        order.pay(Payment.Method.WECHAT)
        self.assertEqual(order.cancellation_fee(), 0)

    def test_unpaid_same_day_cancel_has_no_fee(self):
        order = make_order(start=0, nights=2)
        order.cancel()
        self.assertEqual(order.cancel_fee, 0)
        self.assertEqual(order.amount, Decimal("200.00"))
        self.assertFalse(order.payments.exists())

    def test_early_checkout_refunds_unused_nights(self):
        order = make_order(start=0, nights=3)
        order.pay(Payment.Method.WECHAT)
        order.start_boarding()
        order.finish_boarding()
        order.refresh_from_db()
        self.assertEqual(order.check_out, days(1))
        self.assertEqual(order.amount, Decimal("100.00"))
        self.assertEqual(order.payments.get(kind=Payment.Kind.REFUND).amount, Decimal("200.00"))
        self.assertEqual(order.payment_status, Order.PaymentStatus.PAID)
        self.assertIn("¥200.00 已原路退回", Notification.objects.get(title="寄养已完成").body)

    @override_settings(EARLY_CHECKOUT_REFUND=False)
    def test_early_checkout_refund_can_be_disabled(self):
        order = make_order(start=0, nights=3)
        order.pay(Payment.Method.WECHAT)
        order.start_boarding()
        order.finish_boarding()
        self.assertEqual(order.amount, Decimal("300.00"))
        self.assertFalse(order.payments.filter(kind=Payment.Kind.REFUND).exists())

    def test_reschedule_longer_stay_requires_top_up(self):
        order = make_order(start=2, nights=2)
        order.pay(Payment.Method.WECHAT)
        due = order.reschedule(order.room, days(2), days(5))
        order.refresh_from_db()
        self.assertEqual(due, Decimal("100.00"))
        self.assertEqual(order.amount, Decimal("300.00"))
        self.assertEqual(order.payment_status, Order.PaymentStatus.PARTIAL)
        self.assertTrue(order.can_pay)
        payment = order.pay(Payment.Method.ALIPAY)
        self.assertEqual(payment.amount, Decimal("100.00"))
        self.assertEqual(order.payment_status, Order.PaymentStatus.PAID)
        self.assertTrue(Notification.objects.filter(title="补款成功").exists())

    def test_reschedule_cheaper_room_refunds_difference(self):
        order = make_order(start=2, nights=2)
        order.pay(Payment.Method.WECHAT)
        original_room, cheap = order.room, make_room(price=Decimal("60"))
        self.assertEqual(order.reschedule(cheap, days(3), days(5)), 0)
        order.refresh_from_db()
        self.assertEqual((order.room, order.check_in, order.amount), (cheap, days(3), Decimal("120.00")))
        self.assertEqual(order.payments.get(kind=Payment.Kind.REFUND).amount, Decimal("80.00"))
        self.assertEqual(order.payment_status, Order.PaymentStatus.PAID)
        self.assertTrue(is_room_available(original_room, days(2), days(4)))

    def test_reschedule_respects_availability_and_window(self):
        room = make_room()
        make_order(room=room, start=5, nights=2)
        order = make_order(start=2, nights=2)
        with self.assertRaises(ValidationError):
            order.reschedule(room, days(5), days(6))
        order.refresh_from_db()
        with self.assertRaises(ValidationError):
            order.reschedule(order.room, order.check_in, order.check_out)
        today_order = make_order(start=0, nights=1)
        self.assertFalse(today_order.can_reschedule)
        with self.assertRaises(ValidationError):
            today_order.reschedule(today_order.room, days(3), days(4))

    def test_unpaid_reschedule_just_reprices(self):
        order = make_order(start=2, nights=2)
        order.reschedule(order.room, days(2), days(6))
        order.refresh_from_db()
        self.assertEqual(order.amount, Decimal("400.00"))
        self.assertEqual(order.payment_status, Order.PaymentStatus.UNPAID)
        self.assertEqual(order.balance_due, Decimal("400.00"))


class CalendarTests(TestCase):
    def test_calendar_page(self):
        room = make_room()
        paid = make_order(room=room, start=0, nights=2, source=Order.Source.ONLINE)
        paid.pay(Payment.Method.WECHAT)
        admin = get_user_model().objects.create_superuser("cal", "", "pw")
        self.client.force_login(admin)
        response = self.client.get(reverse("admin:bookings_order_calendar"), {"nights": "14"})
        self.assertContains(response, "房态日历")
        self.assertContains(response, paid.room.number)


@override_settings(PAYMENT_TIMEOUT_MINUTES=30)
class ExpireOrdersTests(TestCase):
    def _age(self, order, minutes):
        Order.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(minutes=minutes))

    def test_only_stale_unpaid_online_orders_expire(self):
        stale = make_order(source=Order.Source.ONLINE)
        fresh = make_order(source=Order.Source.ONLINE)
        desk = make_order(source=Order.Source.FRONT_DESK)
        paid = make_order(source=Order.Source.ONLINE)
        paid.pay(Payment.Method.WECHAT)
        for order in (stale, desk, paid):
            self._age(order, 31)
        self._age(fresh, 5)

        self.assertEqual(expire_unpaid_orders(), 1)
        statuses = dict(Order.objects.values_list("pk", "status"))
        self.assertEqual(statuses[stale.pk], Order.Status.CANCELLED)
        self.assertEqual(statuses[fresh.pk], Order.Status.PENDING)
        self.assertEqual(statuses[desk.pk], Order.Status.PENDING)
        self.assertEqual(statuses[paid.pk], Order.Status.PENDING)

    def test_pay_deadline(self):
        order = make_order(source=Order.Source.ONLINE)
        self.assertEqual(order.pay_deadline, order.created_at + timedelta(minutes=30))
        self.assertIsNone(make_order(source=Order.Source.FRONT_DESK).pay_deadline)

    def test_command(self):
        self._age(make_order(source=Order.Source.ONLINE), 60)
        out = StringIO()
        call_command("expire_orders", stdout=out)
        self.assertIn("已取消超时订单 1 笔", out.getvalue())
