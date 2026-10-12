import json

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from apps.api.models import ApiToken
from apps.testing import days, make_order, make_owner, make_pet, make_room


class ApiV1Tests(TestCase):
    def setUp(self):
        self.owner = make_owner()
        self.pet = make_pet(owner=self.owner)
        self.room = make_room()
        self.token = ApiToken.objects.create(user=self.owner.user, name="test")

    def auth(self):
        return {"HTTP_AUTHORIZATION": f"Bearer {self.token.key}"}

    def test_health_and_availability(self):
        r = self.client.get(reverse("api:health"))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        r = self.client.get(
            reverse("api:rooms_availability"),
            {"check_in": days(2).isoformat(), "check_out": days(4).isoformat(), "species": "dog"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.json()["data"]["rooms"]), 1)

    def test_calendar(self):
        r = self.client.get(reverse("api:rooms_calendar"), {"nights": 7})
        self.assertEqual(r.status_code, 200)
        self.assertIn("rows", r.json()["data"])

    def test_booking_and_order(self):
        payload = {
            "pet": self.pet.pk,
            "room": self.room.pk,
            "check_in": days(5).isoformat(),
            "check_out": days(7).isoformat(),
        }
        r = self.client.post(
            reverse("api:bookings_create"),
            data=json.dumps(payload),
            content_type="application/json",
            **self.auth(),
        )
        self.assertEqual(r.status_code, 201, r.content)
        order_no = r.json()["data"]["order_no"]
        detail = self.client.get(reverse("api:orders_detail", args=[order_no]), **self.auth())
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["data"]["order_no"], order_no)

    def test_staff_check_in_out_issues_coupon(self):
        from apps.loyalty.models import Coupon

        staff = get_user_model().objects.create_user("api_staff", password="pw", is_staff=True)
        token = ApiToken.objects.create(user=staff, name="staff")
        order = make_order(pet=self.pet, room=self.room, start=0, nights=2)
        order.pay("cash")
        order.start_boarding()
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(
                reverse("api:staff_check_out", args=[order.order_no]),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {token.key}",
            )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(Coupon.objects.filter(code__startswith=f"BACK{order.pk}-").exists())

    def test_invoice_pdf(self):
        order = make_order(pet=self.pet, room=self.room, start=3, nights=2)
        order.pay("cash")
        r = self.client.post(
            reverse("api:invoices_create"),
            data=json.dumps({"order_no": order.order_no, "title": "Zhang"}),
            content_type="application/json",
            **self.auth(),
        )
        self.assertEqual(r.status_code, 201, r.content)
        pk = r.json()["data"]["id"]
        pdf = self.client.get(reverse("api:invoices_pdf", args=[pk]), **self.auth())
        self.assertEqual(pdf.status_code, 200)
        self.assertIn("pdf", pdf["Content-Type"])
