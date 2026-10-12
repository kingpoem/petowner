import io
import shutil
import tempfile
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.bookings.models import Order, Payment
from apps.care.models import ServiceRecord
from apps.notifications.models import Notification
from apps.testing import PASSWORD, days, make_order, make_pet


def jpeg() -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (800, 600), (120, 160, 200)).save(buffer, "JPEG")
    return SimpleUploadedFile("care.jpg", buffer.getvalue(), content_type="image/jpeg")


class StaffBoardTests(TestCase):
    def setUp(self):
        self.carer = get_user_model().objects.create_user("carer", password=PASSWORD, is_staff=True, first_name="小李")
        self.carer.user_permissions.add(
            *Permission.objects.filter(codename__in=["change_order", "add_servicerecord", "view_order"])
        )
        self.client.force_login(self.carer)
        self.arriving = make_order(pet=make_pet(name="可乐", allergies="鸡肉"), start=0, nights=2)
        self.boarding = make_order(pet=make_pet(name="团子"), start=0, nights=1)
        self.boarding.pay(Payment.Method.WECHAT)
        self.boarding.start_boarding()
        Order.objects.filter(pk=self.boarding.pk).update(check_in=days(-1), check_out=days(0))
        self.boarding.refresh_from_db()

    def test_requires_staff(self):
        self.client.logout()
        response = self.client.get(reverse("staff:board"))
        self.assertTrue(response["Location"].startswith(reverse("admin:login")))
        customer = make_pet().owner.user
        self.client.force_login(customer)
        self.assertEqual(self.client.get(reverse("staff:board")).status_code, 403)

    def test_tabs_and_search(self):
        response = self.client.get(reverse("staff:board"), {"tab": "arrivals"})
        self.assertContains(response, "可乐")
        self.assertContains(response, "过敏：鸡肉")
        self.assertContains(response, "办理入住")
        self.assertNotContains(response, "团子")
        response = self.client.get(reverse("staff:board"), {"tab": "departures"})
        self.assertContains(response, "团子")
        self.assertContains(response, "尚无护理记录")
        response = self.client.get(reverse("staff:board"), {"tab": "boarding", "q": "不存在"})
        self.assertContains(response, "没有找到")

    def test_check_in_collect_and_check_out(self):
        board = reverse("staff:board") + "?tab=arrivals"
        response = self.client.post(reverse("staff:check_in", args=[self.arriving.pk]), {"next": board})
        self.assertRedirects(response, board, fetch_redirect_response=False)
        self.arriving.refresh_from_db()
        self.assertEqual(self.arriving.status, Order.Status.CHECKED_IN)

        self.client.post(reverse("staff:collect", args=[self.arriving.pk]), {"method": "wechat"})
        self.assertFalse(self.arriving.payments.exists())
        self.client.post(reverse("staff:collect", args=[self.arriving.pk]), {"method": "cash"})
        self.assertEqual(self.arriving.payments.get().amount, Decimal("200.00"))

        self.client.post(reverse("staff:check_out", args=[self.boarding.pk]))
        self.boarding.refresh_from_db()
        self.assertEqual(self.boarding.status, Order.Status.COMPLETED)

    def test_external_next_is_ignored(self):
        response = self.client.post(
            reverse("staff:check_in", args=[self.arriving.pk]), {"next": "https://evil.example.com/"}
        )
        self.assertRedirects(response, reverse("staff:board"), fetch_redirect_response=False)

    def test_permissions_are_enforced(self):
        self.carer.user_permissions.clear()
        self.carer = get_user_model().objects.get(pk=self.carer.pk)
        self.client.force_login(self.carer)
        self.assertEqual(self.client.post(reverse("staff:check_in", args=[self.arriving.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("staff:care", args=[self.boarding.pk])).status_code, 403)


class CareRecordTests(TestCase):
    def setUp(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=media)
        override.enable()
        self.addCleanup(override.disable)
        self.admin = get_user_model().objects.create_superuser("boss", "", PASSWORD, first_name="王店长")
        self.client.force_login(self.admin)
        self.order = make_order(start=0, nights=2)
        self.order.start_boarding()
        self.url = reverse("staff:care", args=[self.order.pk])

    def test_record_with_photo_notifies_owner(self):
        self.assertContains(self.client.get(self.url), "保存并通知主人")
        data = {"care_content": "晚餐 200g", "appetite": "full", "health_status": "good", "photo": jpeg()}
        response = self.client.post(self.url, data)
        self.assertRedirects(response, reverse("staff:board") + "?tab=boarding", fetch_redirect_response=False)
        record = ServiceRecord.objects.get()
        self.assertEqual(record.staff, "王店长")
        self.assertTrue(record.photo.name.startswith("care/"))
        self.assertTrue(Notification.objects.filter(user=self.order.pet.owner.user, body="晚餐 200g").exists())

    def test_abnormal_status_requires_note(self):
        data = {"care_content": "精神不振", "appetite": "little", "health_status": "abnormal", "health_note": ""}
        self.assertContains(self.client.post(self.url, data), "请填写具体情况")
        self.assertFalse(ServiceRecord.objects.exists())

    def test_only_boarding_orders(self):
        pending = make_order(start=1)
        response = self.client.get(reverse("staff:care", args=[pending.pk]))
        self.assertRedirects(response, reverse("staff:board"), fetch_redirect_response=False)

    def test_staff_pages_require_two_factor_when_bound(self):
        from apps.security.models import TOTPDevice
        from apps.security.tests import current_code

        device = TOTPDevice.objects.create(user=self.admin)
        device.verify(current_code(device, -1))
        response = self.client.get(self.url)
        self.assertTrue(response["Location"].startswith(reverse("security:2fa_verify")))
