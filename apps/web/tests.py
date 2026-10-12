import io
import re
import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.bookings.models import Order, Payment, Waitlist
from apps.care.models import Review
from apps.images import thumbnail_name, thumbnail_url
from apps.notifications.models import Notification
from apps.security import sms
from apps.testing import PASSWORD, days, make_order, make_owner, make_pet, make_room


class PublicPagesTests(TestCase):
    def setUp(self):
        self.room = make_room(name="阳光房", is_listed=True)

    def test_pages_render(self):
        for url in [
            reverse("web:home"),
            reverse("web:room_list"),
            reverse("web:room_detail", args=[self.room.pk]),
            reverse("web:page", args=["terms"]),
            reverse("web:page", args=["privacy"]),
            reverse("web:page", args=["credits"]),
            reverse("web:login"),
            reverse("web:register"),
            reverse("web:password_reset"),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_healthz(self):
        response = self.client.get("/healthz", HTTP_HOST="10.0.0.1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")

    def test_unknown_page_404(self):
        self.assertEqual(self.client.get(reverse("web:page", args=["nope"])).status_code, 404)

    def test_unlisted_room_hidden(self):
        hidden = make_room(is_listed=False)
        self.assertEqual(self.client.get(reverse("web:room_detail", args=[hidden.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("web:room_list")), hidden.number)

    def test_room_search_shows_only_available(self):
        busy = make_room(name="满房", pet_type="dog")
        make_order(room=busy, start=1, nights=3)
        url = reverse("web:room_list") + f"?species=dog&check_in={days(1)}&check_out={days(3)}"
        response = self.client.get(url)
        self.assertContains(response, "阳光房")
        self.assertNotContains(response, "满房")

    def test_home_hides_private_reviews(self):
        order = make_order(start=0)
        order.start_boarding()
        order.finish_boarding()
        Review.objects.create(order=order, rating=5, content="不想公开的评价", is_public=False)
        self.assertNotContains(self.client.get(reverse("web:home")), "不想公开的评价")


def issue_sms(test: TestCase, phone: str, purpose: str = "register") -> str:
    cache.delete(f"sms:sent:{purpose}:{phone}")
    with test.assertLogs("apps.security.sms", "WARNING"):
        return sms.issue_code(phone, purpose)


def solve_captcha(client) -> str:
    client.get(reverse("security:captcha"))
    return client.session["captcha"]["text"]


class AccountTests(TestCase):
    def setUp(self):
        cache.clear()

    def _register(self, **overrides):
        data = {
            "name": "小明",
            "phone": "13711112222",
            "password1": "Sunny-day-2026",
            "password2": "Sunny-day-2026",
            "agree": "on",
            **overrides,
        }
        if "sms_code" not in data and len(data["phone"]) == 11:
            data["sms_code"] = issue_sms(self, data["phone"])
        return self.client.post(reverse("web:register"), data)

    def test_register_requires_valid_sms_code(self):
        issue_sms(self, "13711112222")
        self.assertContains(self._register(sms_code="000000"), "短信验证码错误或已过期")
        self.assertFalse(get_user_model().objects.exists())

    def test_sms_code_survives_other_form_errors(self):
        code = issue_sms(self, "13711112222")
        self.assertContains(self._register(sms_code=code, password2="other"), "两次输入的密码不一致")
        response = self._register(sms_code=code)
        self.assertRedirects(response, reverse("web:pet_create"), fetch_redirect_response=False)

    def test_password_reset_by_sms(self):
        owner = make_owner()
        url = reverse("web:password_reset_sms")
        data = {"phone": owner.phone, "new_password1": "Brand-new-2026", "new_password2": "Brand-new-2026"}
        self.assertContains(self.client.post(url, {**data, "sms_code": "123456"}), "短信验证码错误或已过期")
        response = self.client.post(url, {**data, "sms_code": issue_sms(self, owner.phone, "reset")})
        self.assertRedirects(response, reverse("web:login"), fetch_redirect_response=False)
        self.assertTrue(self.client.login(username=owner.phone, password="Brand-new-2026"))

    def test_login_requires_captcha_after_failures(self):
        owner = make_owner()
        login_url = reverse("web:login")
        for _ in range(3):
            self.client.post(login_url, {"username": owner.phone, "password": "wrong"})
        self.assertContains(self.client.get(login_url), "图形验证码")
        response = self.client.post(login_url, {"username": owner.phone, "password": PASSWORD, "captcha": "XXXX"})
        self.assertContains(response, "图形验证码错误")
        captcha = solve_captcha(self.client)
        response = self.client.post(login_url, {"username": owner.phone, "password": PASSWORD, "captcha": captcha})
        self.assertRedirects(response, reverse("web:dashboard"), fetch_redirect_response=False)

    def test_register_creates_owner_and_logs_in(self):
        response = self._register()
        self.assertRedirects(response, reverse("web:pet_create"), fetch_redirect_response=False)
        user = get_user_model().objects.get(username="13711112222")
        self.assertEqual(user.owner_profile.name, "小明")
        self.assertEqual(self.client.get(reverse("web:dashboard")).status_code, 200)

    def test_register_validation(self):
        response = self._register(phone="123")
        self.assertContains(response, "请输入 11 位手机号")
        response = self._register(password2="other")
        self.assertContains(response, "两次输入的密码不一致")
        response = self._register(agree="")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.exists())

    def test_register_rejects_front_desk_phone(self):
        make_owner(with_account=False, phone="13711112222")
        self.assertContains(self._register(), "已在门店登记")

    def test_login_redirects_by_role(self):
        owner = make_owner()
        response = self.client.post(reverse("web:login"), {"username": owner.phone, "password": PASSWORD})
        self.assertRedirects(response, reverse("web:dashboard"), fetch_redirect_response=False)
        self.client.logout()
        get_user_model().objects.create_superuser("boss", "", PASSWORD)
        response = self.client.post(reverse("web:login"), {"username": "boss", "password": PASSWORD})
        self.assertRedirects(response, reverse("admin:index"), fetch_redirect_response=False)

    def test_login_throttled_after_repeated_failures(self):
        owner = make_owner()
        for attempt in range(5):
            data = {"username": owner.phone, "password": "wrong"}
            if attempt >= 3:
                data["captcha"] = solve_captcha(self.client)
            self.client.post(reverse("web:login"), data)
        response = self.client.post(
            reverse("web:login"),
            {"username": owner.phone, "password": PASSWORD, "captcha": solve_captcha(self.client)},
        )
        self.assertContains(response, "登录失败次数过多")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_required_keeps_query(self):
        url = reverse("web:booking_create") + "?room=1&check_in=2030-01-01"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("next=/book/%3Froom%3D1%26check_in%3D2030-01-01", response["Location"])

    def test_password_reset_by_email(self):
        owner = make_owner(email="pet@example.com")
        owner.user.email = "pet@example.com"
        owner.user.save()
        response = self.client.post(reverse("web:password_reset"), {"email": "pet@example.com"})
        self.assertRedirects(response, reverse("web:password_reset_done"), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(owner.phone, mail.outbox[0].body)

        link = re.search(r"https?://[^/]+(/account/password/reset/\S+)", mail.outbox[0].body).group(1)
        set_password_url = self.client.get(link)["Location"]
        response = self.client.post(
            set_password_url, {"new_password1": "Brand-new-2026", "new_password2": "Brand-new-2026"}
        )
        self.assertRedirects(response, reverse("web:password_reset_complete"), fetch_redirect_response=False)
        self.assertTrue(self.client.login(username=owner.phone, password="Brand-new-2026"))

    def test_password_reset_unknown_email_reveals_nothing(self):
        response = self.client.post(reverse("web:password_reset"), {"email": "nobody@example.com"})
        self.assertRedirects(response, reverse("web:password_reset_done"), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 0)

    def test_staff_without_owner_sent_to_admin(self):
        staff = get_user_model().objects.create_user("clerk", password=PASSWORD, is_staff=True)
        self.client.force_login(staff)
        self.assertRedirects(
            self.client.get(reverse("web:dashboard")), reverse("admin:index"), fetch_redirect_response=False
        )


class OwnerAreaTests(TestCase):
    def setUp(self):
        self.owner = make_owner()
        self.pet = make_pet(owner=self.owner, name="旺财")
        self.room = make_room(price=Decimal("100"))
        self.client.force_login(self.owner.user)

    def test_member_pages_render(self):
        for name in [
            "dashboard",
            "pet_list",
            "pet_create",
            "order_list",
            "notifications",
            "profile",
            "password_change",
        ]:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(f"web:{name}")).status_code, 200)

    def test_pet_crud(self):
        data = {
            "name": "豆豆",
            "species": "dog",
            "breed": "柯基",
            "gender": "female",
            "age": 2,
            "weight": "11",
            "temperament": "gentle",
            "health_status": "健康",
            "vaccine_expiry": days(200).isoformat(),
        }
        response = self.client.post(reverse("web:pet_create"), data)
        self.assertRedirects(response, reverse("web:pet_list"), fetch_redirect_response=False)
        pet = self.owner.pets.get(name="豆豆")
        self.client.post(reverse("web:pet_delete", args=[pet.pk]))
        self.assertFalse(self.owner.pets.filter(name="豆豆").exists())

    def test_pet_form_rejects_external_next(self):
        data = {
            "name": "咪咪",
            "species": "cat",
            "breed": "英短",
            "gender": "male",
            "age": 1,
            "weight": "4",
            "temperament": "gentle",
            "health_status": "健康",
        }
        response = self.client.post(reverse("web:pet_create") + "?next=https://evil.example.com/", data)
        self.assertRedirects(response, reverse("web:pet_list"), fetch_redirect_response=False)

    def test_pet_with_orders_cannot_be_deleted(self):
        make_order(pet=self.pet)
        self.client.post(reverse("web:pet_delete", args=[self.pet.pk]))
        self.assertTrue(type(self.pet).objects.filter(pk=self.pet.pk).exists())

    def test_cannot_touch_other_owners_data(self):
        stranger_pet = make_pet()
        order = make_order(pet=stranger_pet)
        self.assertEqual(self.client.get(reverse("web:pet_edit", args=[stranger_pet.pk])).status_code, 404)
        self.assertEqual(self.client.get(order.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.post(reverse("web:order_cancel", args=[order.order_no])).status_code, 404)

    def test_booking_quote_preview(self):
        url = reverse("web:booking_create") + f"?room={self.room.pk}&check_in={days(1)}&check_out={days(3)}"
        response = self.client.get(url)
        self.assertEqual(response.context["quote"].total, Decimal("200.00"))
        self.assertContains(response, "旺财（柯基）")

    def test_book_pay_cancel_flow(self):
        response = self.client.post(
            reverse("web:booking_create"),
            {"pet": self.pet.pk, "room": self.room.pk, "check_in": days(1), "check_out": days(3), "note": "怕打雷"},
        )
        order = Order.objects.get()
        self.assertEqual(order.source, Order.Source.ONLINE)
        self.assertRedirects(response, reverse("web:order_pay", args=[order.order_no]), fetch_redirect_response=False)

        pay = self.client.post(reverse("web:order_pay", args=[order.order_no]), {"method": "alipay"})
        self.assertIn("/pay/sandbox/", pay["Location"])
        payment = order.payments.get()
        self.client.post(pay["Location"], {"token": self.client.session[f"pay_token:{payment.pk}"]})
        order.refresh_from_db()
        self.assertEqual(order.payment_status, Order.PaymentStatus.PAID)
        self.assertContains(self.client.get(order.get_absolute_url()), "完成支付")

        self.client.post(reverse("web:order_cancel", args=[order.order_no]), {"reason": "临时有事"})
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(order.payments.filter(kind=Payment.Kind.REFUND).count(), 1)

    def test_quote_fragment(self):
        url = reverse("web:quote_preview")
        response = self.client.get(url, {"room": self.room.pk, "check_in": days(1), "check_out": days(4)})
        self.assertContains(response, "¥300.00")
        self.assertNotContains(response, "<html")
        for bad in ({"room": "x"}, {"room": self.room.pk, "check_in": days(3), "check_out": days(1)}):
            with self.subTest(params=bad):
                self.assertContains(self.client.get(url, bad), "选择房间与日期后显示逐晚价格")

    def test_quote_fragment_shows_reschedule_difference(self):
        order = make_order(pet=self.pet, room=self.room, start=2, nights=2)
        order.pay(Payment.Method.WECHAT)
        params = {"order": order.order_no, "room": self.room.pk, "check_in": days(2), "check_out": days(5)}
        self.assertContains(self.client.get(reverse("web:quote_preview"), params), "需补差价")
        stranger = make_order(start=2)
        params["order"] = stranger.order_no
        self.assertEqual(self.client.get(reverse("web:quote_preview"), params).status_code, 404)

    def test_reschedule_flow(self):
        order = make_order(pet=self.pet, room=self.room, start=2, nights=2)
        order.pay(Payment.Method.WECHAT)
        url = reverse("web:order_reschedule", args=[order.order_no])
        self.assertContains(self.client.get(order.get_absolute_url()), "改期 / 换房")
        self.assertContains(self.client.get(url), "无需补退差价")

        response = self.client.post(url, {"room": self.room.pk, "check_in": days(2), "check_out": days(5)})
        self.assertRedirects(response, reverse("web:order_pay", args=[order.order_no]), fetch_redirect_response=False)
        self.assertContains(self.client.get(response["Location"]), "¥100.00")
        pay = self.client.post(response["Location"], {"method": "alipay"})
        self.assertIn("/pay/sandbox/", pay["Location"])
        sandbox = pay["Location"]
        payment_id = int(sandbox.rstrip("/").rsplit("/", 1)[-1])
        self.client.post(sandbox, {"token": self.client.session[f"pay_token:{payment_id}"]})
        order.refresh_from_db()
        self.assertEqual((order.amount, order.payment_status), (Decimal("300.00"), Order.PaymentStatus.PAID))

        response = self.client.post(url, {"room": self.room.pk, "check_in": days(3), "check_out": days(4)})
        self.assertRedirects(response, order.get_absolute_url(), fetch_redirect_response=False)
        order.refresh_from_db()
        self.assertEqual(order.net_paid, Decimal("100.00"))

    def test_reschedule_errors_are_shown(self):
        order = make_order(pet=self.pet, room=self.room, start=2, nights=2)
        make_order(room=self.room, start=6, nights=2)
        url = reverse("web:order_reschedule", args=[order.order_no])
        response = self.client.post(url, {"room": self.room.pk, "check_in": days(6), "check_out": days(7)})
        self.assertContains(response, "该房间在所选时间段已满")
        order.refresh_from_db()
        self.assertEqual(order.check_in, days(2))
        today_order = make_order(pet=make_pet(owner=self.owner), start=0)
        response = self.client.get(reverse("web:order_reschedule", args=[today_order.order_no]))
        self.assertRedirects(response, today_order.get_absolute_url(), fetch_redirect_response=False)

    def test_cancel_modal_previews_late_fee(self):
        order = make_order(pet=self.pet, room=self.room, start=0, nights=2)
        order.pay(Payment.Method.WECHAT)
        self.assertContains(self.client.get(order.get_absolute_url()), "扣除首晚房费 <strong>¥100.00</strong>")

    def test_booking_errors_are_shown(self):
        make_order(room=self.room, start=1, nights=2)
        response = self.client.post(
            reverse("web:booking_create"),
            {"pet": self.pet.pk, "room": self.room.pk, "check_in": days(1), "check_out": days(3)},
        )
        self.assertContains(response, "该房间在所选时间段已满")

    @override_settings(PAYMENT_TIMEOUT_MINUTES=30)
    def test_expired_order_cannot_be_paid(self):
        order = make_order(pet=self.pet, room=self.room, source=Order.Source.ONLINE)
        Order.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(minutes=45))
        self.client.post(reverse("web:order_pay", args=[order.order_no]), {"method": "wechat"})
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertFalse(order.payments.exists())

    def test_review_after_completion(self):
        order = make_order(pet=self.pet, start=0)
        self.assertEqual(self.client.get(reverse("web:order_review", args=[order.order_no])).status_code, 302)
        order.start_boarding()
        order.finish_boarding()
        self.client.post(
            reverse("web:order_review", args=[order.order_no]),
            {"rating": 4, "content": "很好", "feedback": "", "is_public": "on"},
        )
        self.assertEqual(order.review.rating, 4)

    def test_waitlist_join_and_cancel(self):
        make_order(room=self.room, start=5, nights=2)
        self.client.post(
            reverse("web:waitlist_create"),
            {"pet": self.pet.pk, "room_type": "", "check_in": days(5), "check_out": days(7)},
        )
        entry = Waitlist.objects.get(pet=self.pet)
        self.assertEqual(entry.status, Waitlist.Status.WAITING)
        self.client.post(reverse("web:waitlist_cancel", args=[entry.pk]))
        entry.refresh_from_db()
        self.assertEqual(entry.status, Waitlist.Status.CANCELLED)

    def test_waitlist_redirects_when_rooms_free(self):
        response = self.client.post(
            reverse("web:waitlist_create"),
            {"pet": self.pet.pk, "room_type": "", "check_in": days(5), "check_out": days(7)},
        )
        self.assertTrue(response["Location"].startswith(reverse("web:booking_create")))
        self.assertFalse(Waitlist.objects.exists())

    def test_notification_open_marks_read_and_blocks_external_links(self):
        safe = Notification.objects.create(user=self.owner.user, title="a", link=reverse("web:order_list"))
        evil = Notification.objects.create(user=self.owner.user, title="b", link="https://evil.example.com/")
        self.assertRedirects(
            self.client.get(reverse("web:notification_open", args=[safe.pk])),
            reverse("web:order_list"),
            fetch_redirect_response=False,
        )
        safe.refresh_from_db()
        self.assertTrue(safe.is_read)
        self.assertRedirects(
            self.client.get(reverse("web:notification_open", args=[evil.pk])),
            reverse("web:notifications"),
            fetch_redirect_response=False,
        )
        self.client.post(reverse("web:notification_read_all"))
        self.assertFalse(Notification.objects.filter(user=self.owner.user, is_read=False).exists())


def make_photo(size=(3000, 2000), orientation=6, fmt="JPEG") -> SimpleUploadedFile:
    image = Image.new("RGB", size, (200, 120, 80))
    exif = Image.Exif()
    exif[0x0112] = orientation  # Orientation：6 = 需顺时针旋转 90°
    exif[0x010F] = "PhoneMaker"
    buffer = io.BytesIO()
    image.save(buffer, fmt, exif=exif)
    return SimpleUploadedFile("IMG_0001.JPG", buffer.getvalue(), content_type="image/jpeg")


class ImageProcessingTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.owner = make_owner()
        self.client.force_login(self.owner.user)

    def _upload(self, photo):
        data = {
            "name": "豆豆",
            "species": "dog",
            "breed": "柯基",
            "gender": "female",
            "age": 2,
            "weight": "8",
            "temperament": "gentle",
            "health_status": "健康",
            "photo": photo,
        }
        return self.client.post(reverse("web:pet_create"), data)

    def test_upload_is_rotated_resized_and_stripped(self):
        self._upload(make_photo())
        pet = self.owner.pets.get()
        self.assertTrue(pet.photo.name.startswith("pets/") and pet.photo.name.endswith(".jpg"))
        self.assertNotIn("IMG_0001", pet.photo.name)
        with Image.open(pet.photo.path) as saved:
            self.assertEqual(saved.size, (853, 1280))
            self.assertFalse(saved.getexif())

    def test_thumbnail_generated_once(self):
        self._upload(make_photo(orientation=1))
        pet = self.owner.pets.get()
        url = thumbnail_url(pet.photo, 160)
        self.assertTrue(url.endswith(".webp"))
        target = Path(self.media, thumbnail_name(pet.photo.name, 160))
        with Image.open(target) as thumb:
            self.assertEqual(max(thumb.size), 160)
        mtime = target.stat().st_mtime_ns
        self.assertEqual(thumbnail_url(pet.photo, 160), url)
        self.assertEqual(target.stat().st_mtime_ns, mtime)
        self.assertContains(self.client.get(reverse("web:pet_list")), url)

    def test_rejects_non_image(self):
        fake = SimpleUploadedFile("evil.jpg", b"<?php echo 1; ?>", content_type="image/jpeg")
        response = self._upload(fake)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.owner.pets.exists())


class AdminTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("boss", "", PASSWORD)
        self.client.force_login(self.admin)
        order = make_order(start=0)
        order.start_boarding()
        self.order = order

    def test_admin_pages_render(self):
        for url in [
            reverse("admin:index"),
            reverse("admin:bookings_order_changelist"),
            reverse("admin:bookings_order_change", args=[self.order.pk]),
            reverse("admin:bookings_order_add"),
            reverse("admin:bookings_payment_changelist"),
            reverse("admin:bookings_waitlist_changelist"),
            reverse("admin:pets_owner_changelist"),
            reverse("admin:pets_pet_changelist"),
            reverse("admin:rooms_room_changelist"),
            reverse("admin:rooms_pricerule_changelist"),
            reverse("admin:care_servicerecord_changelist"),
            reverse("admin:care_review_changelist"),
            reverse("admin:notifications_notification_changelist"),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_dashboard_stats(self):
        from apps.bookings.templatetags.admin_dashboard import dashboard_stats

        stats = dashboard_stats({"request": None, "CURRENT_STORE": None})
        self.assertEqual(stats["boarding"], 1)
        self.assertEqual(stats["capacity"], 1)
        self.assertEqual(stats["occupancy"], 100)
        self.assertContains(self.client.get(reverse("admin:index")), "运营看板")

    def test_checkout_action(self):
        self.client.post(
            reverse("admin:bookings_order_changelist"),
            {"action": "finish_boarding", "_selected_action": [self.order.pk]},
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.COMPLETED)

    def test_admin_reschedule_paid_order_settles_difference(self):
        order = make_order(start=3, nights=2)
        payment = order.pay(Payment.Method.CASH)
        data = {
            "pet": order.pet_id,
            "room": order.room_id,
            "check_in": days(3),
            "check_out": days(4),
            "note": "门店改期",
            "service_records-TOTAL_FORMS": 0,
            "service_records-INITIAL_FORMS": 0,
            "payments-TOTAL_FORMS": 1,
            "payments-INITIAL_FORMS": 1,
            "payments-0-id": payment.pk,
            "payments-0-order": order.pk,
        }
        response = self.client.post(reverse("admin:bookings_order_change", args=[order.pk]), data)
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual((order.check_out, order.amount, order.note), (days(4), Decimal("100.00"), "门店改期"))
        self.assertEqual(order.payments.get(kind=Payment.Kind.REFUND).amount, Decimal("100.00"))
