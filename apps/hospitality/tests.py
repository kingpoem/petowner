from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.bookings.models import Order
from apps.rooms.pricing import quote
from apps.testing import days, make_order, make_owner, make_pet, make_room

from .models import AddonService, Billing, Coupon, HolidayRate, StaffMember, VaccineRecord
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
