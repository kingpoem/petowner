from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.bookings.models import Order
from apps.rooms.pricing import quote
from apps.testing import days, make_order, make_owner, make_pet, make_room

from .models import AddonService, Billing, HolidayRate
from .pulse import breathe, fold_clock, layout_atlas, quiet_index, quiet_line, weave
from .seed import seed_catalog


class CommercePricingTests(TestCase):
    def setUp(self):
        self.owner = make_owner()
        self.pet = make_pet(owner=self.owner, name="旺财", breed="柯基")
        self.room = make_room(price=Decimal("100"))
        self.client.force_login(self.owner.user)
        self.service = AddonService.objects.create(
            code="bath",
            name="离店洗护",
            summary="洗澡吹干",
            price=Decimal("50"),
            billing=Billing.ONCE,
        )

    def _book(self, **extra):
        data = {
            "pet": self.pet.pk,
            "room": self.room.pk,
            "check_in": days(2),
            "check_out": days(4),
            "note": "",
        }
        data.update(extra)
        return self.client.post(reverse("web:booking_create"), data)

    def test_addon_is_included(self):
        self._book(addons=[self.service.pk])
        order = Order.objects.get()
        self.assertEqual(order.amount, Decimal("250.00"))
        self.assertEqual(order.addons.get().line_total, Decimal("50.00"))

    def test_holiday_rate_changes_nightly_quote(self):
        HolidayRate.objects.create(day=days(1), label="店庆", multiplier=Decimal("1.50"))
        priced = quote(self.room, days(1), days(3))
        self.assertEqual(priced.total, Decimal("250.00"))
        self.assertEqual(priced.surcharged_nights[0].rule, "店庆")

    def test_catalog_pages(self):
        seed_catalog()
        # 旧 /services/ 入口并入护理服务页
        response = self.client.get(reverse("hospitality:services"), follow=True)
        self.assertContains(response, "视频探视")
        self.assertContains(response, "护理服务")


class CatalogAuthTests(TestCase):
    def test_services_are_public(self):
        response = self.client.get(reverse("hospitality:services"), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "护理服务")
        self.assertFalse(get_user_model().objects.exists())


class HouseAndReceiptTests(TestCase):
    def test_receipt_stays_with_the_owner(self):
        owner = make_owner()
        order = make_order(pet=make_pet(owner=owner, name="布丁"))
        url = reverse("web:order_receipt", args=[order.order_no])
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(owner.user)
        response = self.client.get(url)
        self.assertContains(response, "布丁")
        self.assertContains(response, order.order_no)

class _Room:
    def __init__(self, pk, pet_type, room_type, number, name):
        self.pk = pk
        self.pet_type = pet_type
        self.room_type = room_type
        self.number = number
        self.name = name

    @property
    def display_name(self):
        return self.name


class PulseTests(SimpleTestCase):
    def test_a_good_meal_breathes_slower_than_an_alert(self):
        meal = breathe("早餐按量喂食，饮水正常，精神很好")
        alarm = breathe("异常：轻微腹泻", alert=True)
        self.assertIn("进食", meal.labels)
        self.assertGreater(meal.calm, alarm.calm)
        self.assertGreater(meal.breath, alarm.breath)
        self.assertLess(alarm.breath, 2.6)
        self.assertEqual(breathe("早餐按量喂食，饮水正常，精神很好"), meal)

    def test_cats_sit_to_the_right_of_dogs(self):
        rooms = [
            _Room(1, "dog", "standard", "A01", "阳光标准间"),
            _Room(2, "cat", "suite", "C01", "观景猫套房"),
        ]
        atlas = layout_atlas(rooms, {1: {"name": "旺财", "caption": "进食", "breath": 4.2, "alert": False}})
        dog = next(cell for cell in atlas["cells"] if cell["room_id"] == 1)
        cat = next(cell for cell in atlas["cells"] if cell["room_id"] == 2)
        self.assertLess(dog["x"], cat["x"])
        self.assertTrue(dog["live"])
        self.assertFalse(cat["live"])
        self.assertEqual(cat["name"], "空房")
        busy = layout_atlas(
            rooms,
            {2: {"name": "咪咪", "caption": "进食 · 洗护 · 日照", "breath": 4.5, "alert": False}},
        )
        cat_live = next(cell for cell in busy["cells"] if cell["room_id"] == 2)
        self.assertEqual(cat_live["caption"], "进食 · 洗护")

    def test_empty_house_is_quiet(self):
        self.assertEqual(quiet_index([], 0), 100)
        self.assertIn("很静", quiet_line(100, 0))

    def test_evening_care_stays_hidden_until_that_hour(self):
        events = [
            {"room_id": 1, "minute": 8 * 60, "stamp": 10, "text": "早餐只吃了一半", "alert": False},
            {"room_id": 1, "minute": 17 * 60, "stamp": 20, "text": "草坪遛弯，玩得很开心", "alert": False},
            {"room_id": 1, "minute": 20 * 60, "stamp": 30, "text": "洗澡、吹干、梳毛", "alert": False},
        ]
        frames = fold_clock(events)
        self.assertNotIn("1", frames["7"])
        self.assertIn("进食", frames["8"]["1"]["caption"])
        self.assertIn("遛弯", frames["17"]["1"]["caption"])
        self.assertNotIn("洗护", frames["17"]["1"]["caption"])
        self.assertIn("洗护", frames["20"]["1"]["caption"])

    def test_a_timid_cat_asks_a_dog_to_keep_distance(self):
        easy = weave("dog", "gentle", [("dog", "gentle")])
        risky = weave("dog", "gentle", [("cat", "timid")])
        self.assertGreater(easy.score, risky.score)
        self.assertEqual(risky.threads[0].label, "胆小的猫")
        self.assertEqual(risky.threads[0].tone, "watch")
        self.assertIn("安静", weave("cat", "timid", []).line)
