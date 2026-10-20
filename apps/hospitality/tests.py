from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.bookings.models import Order
from apps.rooms.pricing import quote
from apps.testing import days, make_order, make_owner, make_pet, make_room

from .models import AddonService, Billing, Coupon, HolidayRate, StaffMember, VaccineRecord
from .pulse import breathe, fold_clock, layout_atlas, quiet_index, quiet_line, weave
from .seed import seed_catalog
from .services import ensure_member


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
        Coupon.objects.create(
            code="WELCOME",
            name="新客立减",
            kind=Coupon.Kind.AMOUNT,
            value=Decimal("20"),
            min_spend=Decimal("100"),
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

    def test_addon_and_coupon_are_included(self):
        self._book(addons=[self.service.pk], coupon_code="welcome")
        order = Order.objects.get()
        self.assertEqual(order.amount, Decimal("230.00"))
        self.assertEqual(order.coupon_discount, Decimal("20.00"))
        self.assertEqual(order.addons.get().line_total, Decimal("50.00"))
        self.assertEqual(Coupon.objects.get().used_count, 1)

    def test_cancel_returns_coupon_use(self):
        self._book(coupon_code="WELCOME")
        order = Order.objects.get()
        order.cancel("改计划")
        self.assertEqual(Coupon.objects.get().used_count, 0)

    def test_points_redeem_and_refund(self):
        account = ensure_member(self.owner)
        account.points = 500
        account.save(update_fields=["points"])
        self._book(redeem_points=200)
        order = Order.objects.get()
        self.assertEqual((order.amount, order.points_redeemed), (Decimal("198.00"), 200))
        account.refresh_from_db()
        self.assertEqual(account.points, 300)
        order.cancel("不去了")
        account.refresh_from_db()
        self.assertEqual(account.points, 500)

    def test_member_rate_applies_only_when_chosen(self):
        account = ensure_member(self.owner)
        account.lifetime_points = 2000
        account.save(update_fields=["lifetime_points"])
        self._book(use_member="on")
        self.assertEqual(Order.objects.get().amount, Decimal("190.00"))

    def test_holiday_rate_changes_nightly_quote(self):
        HolidayRate.objects.create(day=days(1), label="店庆", multiplier=Decimal("1.50"))
        priced = quote(self.room, days(1), days(3))
        self.assertEqual(priced.total, Decimal("250.00"))
        self.assertEqual(priced.surcharged_nights[0].rule, "店庆")

    def test_vaccine_record_refreshes_pet_expiry(self):
        record = VaccineRecord.objects.create(
            pet=self.pet,
            name="狂犬疫苗",
            injected_on=days(-10),
            expires_on=days(400),
        )
        self.pet.refresh_from_db()
        self.assertEqual(self.pet.vaccine_expiry, record.expires_on)

    def test_catalog_pages(self):
        seed_catalog()
        self.assertContains(self.client.get(reverse("hospitality:services")), "视频探视")
        self.assertContains(self.client.get(reverse("hospitality:membership")), "积分")
        response = self.client.post(
            reverse("hospitality:waitlist"),
            {"pet": self.pet.pk, "room_type": "suite", "check_in": days(3), "check_out": days(6), "note": "想要套房"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.owner.waitlist.get().status, "waiting")


class CatalogAuthTests(TestCase):
    def test_membership_requires_login(self):
        response = self.client.get(reverse("hospitality:membership"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/account/login/", response["Location"])

    def test_services_are_public(self):
        self.assertEqual(self.client.get(reverse("hospitality:services")).status_code, 200)
        self.assertFalse(get_user_model().objects.exists())


class HouseAndReceiptTests(TestCase):
    def test_house_board_is_public_and_hides_phones(self):
        owner = make_owner(phone="13811112222")
        pet = make_pet(owner=owner, name="团子")
        make_order(pet=pet, room=make_room(), status=Order.Status.CHECKED_IN)
        StaffMember.objects.create(name="赵护理", role=StaffMember.Role.CARER, phone="13900001111", skills="猫咪")
        response = self.client.get(reverse("hospitality:house"))
        self.assertContains(response, "团子")
        self.assertContains(response, "房态呼吸")
        self.assertContains(response, "日课折叠")
        self.assertContains(response, "赵护理")
        self.assertNotContains(response, "13811112222")
        self.assertNotContains(response, "13900001111")

    def test_receipt_stays_with_the_owner(self):
        owner = make_owner()
        order = make_order(pet=make_pet(owner=owner, name="布丁"))
        url = reverse("web:order_receipt", args=[order.order_no])
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(owner.user)
        response = self.client.get(url)
        self.assertContains(response, "布丁")
        self.assertContains(response, order.order_no)

    def test_quote_weave_hides_other_pets_names(self):
        from apps.pets.models import Species

        owner = make_owner()
        guest = make_pet(owner=owner, species=Species.DOG, temperament="gentle")
        neighbor = make_pet(name="雪球", species=Species.CAT, temperament="timid")
        make_order(pet=neighbor, start=1, nights=4, status=Order.Status.CHECKED_IN)
        self.client.force_login(owner.user)
        response = self.client.get(
            reverse("web:quote_preview"),
            {"pet": guest.pk, "room": make_room().pk, "check_in": days(1), "check_out": days(3)},
        )
        self.assertContains(response, "入住织体")
        self.assertContains(response, "胆小的猫")
        self.assertNotContains(response, "雪球")


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
