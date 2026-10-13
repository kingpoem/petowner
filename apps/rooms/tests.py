from decimal import Decimal

from django.test import TestCase

from apps.pets.models import PetSize
from apps.testing import days, make_order, make_pet, make_room

from .models import Room
from .pricing import quote


class PricingTests(TestCase):
    def setUp(self):
        self.room = make_room(price=Decimal("100"))

    def test_plain_nights(self):
        q = quote(self.room, days(1), days(4))
        self.assertEqual(q.days, 3)
        self.assertEqual(q.total, Decimal("300.00"))
        self.assertEqual(q.discount, 0)
        self.assertEqual(q.surcharged_nights, [])

    def test_longer_stay_is_price_times_nights(self):
        q = quote(self.room, days(1), days(8))
        self.assertEqual(q.subtotal, Decimal("700.00"))
        self.assertEqual(q.discount, 0)
        self.assertEqual(q.total, Decimal("700.00"))
        self.assertEqual(q.discount_label, "")

    def test_order_amount_uses_quote(self):
        order = make_order(room=self.room, start=1, nights=7)
        self.assertEqual(order.amount, Decimal("700.00"))
        self.assertEqual(order.discount, 0)


class RoomModelTests(TestCase):
    def test_display_and_amenities(self):
        room = make_room(name="", number="A1", amenities="空调， 监控,,独立活动区")
        self.assertEqual(room.display_name, "标准间 A1")
        self.assertEqual(room.amenity_list, ["空调", "监控", "独立活动区"])

    def test_fits_checks_species_and_size(self):
        room = make_room(pet_type=Room.PetType.DOG, max_pet_size=PetSize.MEDIUM)
        self.assertTrue(room.fits(make_pet(weight=Decimal("20"))))
        self.assertFalse(room.fits(make_pet(weight=Decimal("30"))))
        self.assertFalse(room.fits(make_pet(species="cat", weight=Decimal("4"))))

    def test_refresh_status_follows_occupancy(self):
        room = make_room(capacity=1)
        order = make_order(room=room, start=0, nights=2)
        order.start_boarding()
        room.refresh_from_db()
        self.assertEqual(room.status, Room.Status.FULL)
        order.finish_boarding()
        room.refresh_from_db()
        self.assertEqual(room.status, Room.Status.AVAILABLE)

    def test_maintenance_status_is_sticky(self):
        room = make_room(status=Room.Status.MAINTENANCE)
        room.refresh_status()
        self.assertEqual(room.status, Room.Status.MAINTENANCE)

    def test_cleaning_status_is_sticky(self):
        room = make_room(status=Room.Status.CLEANING)
        room.refresh_status()
        self.assertEqual(room.status, Room.Status.CLEANING)

    def test_room_type_guides_cover_all_types(self):
        self.assertEqual(set(Room.ROOM_TYPE_GUIDES), set(Room.RoomType.values))
