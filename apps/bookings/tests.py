from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.pets.models import Pet, PetSize
from apps.rooms.models import Room
from apps.testing import days, make_order, make_owner, make_pet, make_room, make_store_user

from .models import (
    Order,
    Payment,
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

    def test_vaccine_must_cover_whole_stay(self):
        from django.test import override_settings

        with override_settings(REQUIRE_VACCINE=True):
            pet = make_pet(vaccine_expiry=days(2))
            self.assertEqual(room_problem_for_pet(make_room(), pet, days(3))[0], "pet")
            self.assertIsNone(room_problem_for_pet(make_room(), pet, days(2)))

    def test_vaccine_check_can_be_disabled(self):
        from django.test import override_settings

        with override_settings(REQUIRE_VACCINE=False):
            self.assertIsNone(room_problem_for_pet(make_room(), make_pet(vaccine_expiry=None), days(3)))

    def test_maintenance_room_rejected(self):
        room = make_room(status=Room.Status.MAINTENANCE)
        self.assertIn("维护", room_problem_for_pet(room, make_pet(), days(3))[1])

    def test_cleaning_room_rejected(self):
        room = make_room(status=Room.Status.CLEANING)
        self.assertIn("清洁", room_problem_for_pet(room, make_pet(), days(3))[1])

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
        make_order(room=room, start=1, nights=2)
        make_order(room=room, start=3, nights=2)
        self.assertTrue(is_room_available(room, days(1), days(5)))
        make_order(room=room, start=2, nights=2)
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

    def test_max_boarding_days(self):
        from django.test import override_settings

        with override_settings(MAX_BOARDING_DAYS=5):
            with self.assertRaises(ValidationError):
                make_order(nights=6)

    def test_order_no(self):
        order = make_order()
        self.assertRegex(order.order_no, rf"^O\d{{8}}{order.pk:05d}$")
        self.assertEqual(Order.objects.get(pk=order.pk).order_no, order.order_no)


class OrderLifecycleTests(TestCase):
    def setUp(self):
        self.owner = make_owner()
        self.order = make_order(pet=make_pet(owner=self.owner), start=0, nights=3)

    def test_pay_records_payment(self):
        payment = self.order.pay(Payment.Method.CASH)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PAID)
        self.assertIsNotNone(self.order.paid_at)
        self.assertEqual(payment.amount, self.order.amount)
        self.assertTrue(payment.transaction_no.startswith("T"))
        with self.assertRaises(ValidationError):
            self.order.pay(Payment.Method.CASH)

    def test_cancel_paid_order_records_full_refund(self):
        order = make_order(start=2, nights=3)
        order.pay(Payment.Method.ONLINE)
        order.cancel("行程变更")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(order.payment_status, Order.PaymentStatus.REFUNDED)
        refund = order.payments.get(kind=Payment.Kind.REFUND)
        self.assertEqual(refund.signed_amount, Decimal("-300.00"))
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

    def test_finish_boarding_frees_room(self):
        self.order.start_boarding()
        self.order.finish_boarding()
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.COMPLETED)
        self.assertTrue(is_room_available(self.order.room, days(0), days(3)))


class AdminOrderTests(TestCase):
    def test_available_rooms_page(self):
        room = make_room()
        admin = make_store_user(role="admin", username="cal", password="pw")
        self.client.force_login(admin)
        response = self.client.get(
            reverse("admin:bookings_order_available_rooms"),
            {
                "species": "dog",
                "check_in": days(1).isoformat(),
                "check_out": days(3).isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, room.number)

    def test_mark_paid_action(self):
        order = make_order(start=2)
        admin = make_store_user(role="front", username="pay", password="pw")
        self.client.force_login(admin)
        self.client.post(
            reverse("admin:bookings_order_changelist"),
            {"action": "mark_paid", "_selected_action": [order.pk]},
        )
        order.refresh_from_db()
        self.assertEqual(order.payment_status, Order.PaymentStatus.PAID)
