import json
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.testing import PASSWORD, make_owner

from . import captcha, sms, totp
from .models import TOTPDevice
from .views import VERIFIED_SESSION_KEY

RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # base32("12345678901234567890")


def current_code(device: TOTPDevice, offset: int = 0) -> str:
    return totp.code_at(device.secret, totp.current_step() + offset)


class TOTPTests(TestCase):
    def test_rfc6238_vectors(self):
        self.assertEqual(totp.code_at(RFC_SECRET, 59 // 30), "287082")
        self.assertEqual(totp.code_at(RFC_SECRET, 1111111109 // 30), "081804")
        self.assertEqual(totp.match_step(RFC_SECRET, "287 082", now=59), 1)
        self.assertEqual(totp.match_step(RFC_SECRET, "287082", now=59 + 30), 1)
        self.assertIsNone(totp.match_step(RFC_SECRET, "287082", now=59 + 90))
        self.assertIsNone(totp.match_step(RFC_SECRET, "12345"))

    def test_device_rejects_replay(self):
        device = TOTPDevice.objects.create(user=get_user_model().objects.create_user("clerk"))
        code = current_code(device)
        self.assertTrue(device.verify(code))
        self.assertTrue(device.confirmed)
        self.assertFalse(device.verify(code))
        self.assertIn("otpauth://totp/", device.provisioning_uri())


class CaptchaTests(TestCase):
    def test_image_and_one_time_answer(self):
        response = self.client.get(reverse("security:captcha"))
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertTrue(response.content.startswith(b"\x89PNG"))
        self.assertIn("no-cache", response["Cache-Control"])
        request = mock.Mock(session=self.client.session)
        answer = request.session["captcha"]["text"]
        self.assertTrue(captcha.verify(request, answer.lower()))
        self.assertFalse(captcha.verify(request, answer))


class SmsTests(TestCase):
    def setUp(self):
        cache.clear()

    def _issue(self, phone="13800001111", purpose="register", **kwargs):
        with self.assertLogs("apps.security.sms", "WARNING") as logs:
            code = sms.issue_code(phone, purpose, **kwargs)
        self.assertIn(code, logs.output[0])
        return code

    def test_code_is_single_use(self):
        code = self._issue()
        self.assertFalse(sms.verify_code("13800001111", "reset", code))
        self.assertTrue(sms.verify_code("13800001111", "register", code))
        self.assertFalse(sms.verify_code("13800001111", "register", code))

    def test_resend_cooldown_and_attempt_limit(self):
        code = self._issue()
        with self.assertRaisesMessage(sms.SmsError, "秒后再试"):
            sms.issue_code("13800001111", "register")
        for _ in range(sms.MAX_ATTEMPTS):
            self.assertFalse(sms.verify_code("13800001111", "register", "000000"))
        self.assertFalse(sms.verify_code("13800001111", "register", code))

    def test_daily_and_ip_limits(self):
        cache.set("sms:day:13800001111", sms.MAX_PER_PHONE_DAY)
        with self.assertRaisesMessage(sms.SmsError, "今日"):
            sms.issue_code("13800001111", "register")
        cache.set("sms:ip:1.2.3.4", sms.MAX_PER_IP_HOUR)
        with self.assertRaisesMessage(sms.SmsError, "过于频繁"):
            sms.issue_code("13800002222", "register", ip="1.2.3.4")

    @override_settings(
        SMS_BACKEND="aliyun",
        SMS_ACCESS_KEY_ID="ak",
        SMS_ACCESS_KEY_SECRET="secret",
        SMS_SIGN_NAME="宠爱",
        SMS_TEMPLATE_CODE="SMS_1",
    )
    def test_aliyun_backend_signs_request(self):
        resp = mock.MagicMock()
        resp.__enter__.return_value = resp
        resp.read.return_value = json.dumps({"Code": "OK"}).encode()
        with mock.patch("apps.security.sms.urlopen", return_value=resp) as urlopen:
            code = sms.issue_code("13800001111", "register")
        query = parse_qs(urlparse(urlopen.call_args.args[0]).query)
        self.assertEqual(query["PhoneNumbers"], ["13800001111"])
        self.assertEqual(json.loads(query["TemplateParam"][0]), {"code": code})
        params = {k: v[0] for k, v in query.items() if k != "Signature"}
        expected = parse_qs(sms.aliyun_signed_query(params, "secret"))["Signature"]
        self.assertEqual(query["Signature"], expected)

        resp.read.return_value = json.dumps({"Code": "isv.BUSINESS_LIMIT_CONTROL"}).encode()
        with mock.patch("apps.security.sms.urlopen", return_value=resp), self.assertLogs("apps.security.sms", "ERROR"):
            with self.assertRaises(sms.SmsError):
                sms.issue_code("13800002222", "register")


class SendSmsViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.url = reverse("security:send_sms")

    def _send(self, phone, purpose="register", captcha_text=None):
        if captcha_text is None:
            self.client.get(reverse("security:captcha"))
            captcha_text = self.client.session["captcha"]["text"]
        return self.client.post(self.url, {"phone": phone, "purpose": purpose, "captcha": captcha_text})

    def test_requires_captcha(self):
        response = self._send("13800001111", captcha_text="ZZZZ")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["field"], "captcha")

    @override_settings(DEBUG=True)
    def test_sends_code_and_exposes_it_only_in_debug_console_mode(self):
        with self.assertLogs("apps.security.sms", "WARNING"):
            data = self._send("13800001111").json()
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["debug_code"]), 6)
        self.assertIn("138****1111", data["message"])
        self.assertEqual(self._send("13800001111").status_code, 429)

    def test_no_debug_code_in_production(self):
        with self.assertLogs("apps.security.sms", "WARNING"):
            self.assertNotIn("debug_code", self._send("13800001111").json())

    def test_register_rejects_existing_phone(self):
        owner = make_owner()
        self.assertEqual(self._send(owner.phone).status_code, 400)

    def test_reset_does_not_reveal_unknown_phone(self):
        response = self._send("13899998888", purpose="reset")
        self.assertTrue(response.json()["ok"])
        self.assertIsNone(cache.get("sms:code:reset:13899998888"))


class AdminTwoFactorTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = get_user_model().objects.create_superuser("boss", "", PASSWORD)

    def _login(self):
        self.client.post(reverse("admin:login"), {"username": "boss", "password": PASSWORD})

    def _bind(self) -> TOTPDevice:
        device = TOTPDevice.objects.create(user=self.admin)
        device.verify(current_code(device, -1))
        return device

    def test_setup_flow(self):
        self._login()
        response = self.client.get(reverse("security:2fa_setup"))
        self.assertContains(response, "<svg")
        device = TOTPDevice.objects.get(user=self.admin)
        self.assertContains(self.client.post(reverse("security:2fa_setup"), {"code": "000000"}), "动态码不正确")
        response = self.client.post(reverse("security:2fa_setup"), {"code": current_code(device)})
        self.assertRedirects(response, reverse("admin:index"), fetch_redirect_response=False)
        device.refresh_from_db()
        self.assertTrue(device.confirmed)
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)

    def test_bound_admin_must_verify_after_login(self):
        device = self._bind()
        self._login()
        response = self.client.get(reverse("admin:bookings_order_changelist"))
        self.assertTrue(response["Location"].startswith(reverse("security:2fa_verify")))
        verify_url = response["Location"]
        self.assertContains(self.client.get(verify_url), "动态码")
        response = self.client.post(verify_url, {"code": current_code(device)})
        self.assertRedirects(response, reverse("admin:bookings_order_changelist"), fetch_redirect_response=False)
        self.assertEqual(self.client.session[VERIFIED_SESSION_KEY], self.admin.pk)
        # 重新登录后需要再次验证
        self._login()
        self.assertNotIn(VERIFIED_SESSION_KEY, self.client.session)

    def test_verify_lockout_logs_out(self):
        self._bind()
        self._login()
        for _ in range(5):
            response = self.client.post(reverse("security:2fa_verify"), {"code": "000000"})
        self.assertRedirects(response, reverse("admin:login"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_verify_rejects_external_next(self):
        device = self._bind()
        self._login()
        url = reverse("security:2fa_verify") + "?next=https://evil.example.com/"
        response = self.client.post(url, {"code": current_code(device)})
        self.assertRedirects(response, reverse("admin:index"), fetch_redirect_response=False)

    @override_settings(ADMIN_REQUIRE_2FA=True)
    def test_required_policy_forces_binding(self):
        self._login()
        response = self.client.get(reverse("admin:index"))
        self.assertRedirects(response, reverse("security:2fa_setup"), fetch_redirect_response=False)
        self.assertContains(self.client.get(response["Location"]), "要求员工启用二次验证")

    def test_disable_requires_code(self):
        device = self._bind()
        self._login()
        self.client.post(reverse("security:2fa_verify"), {"code": current_code(device)})
        self.client.post(reverse("security:2fa_disable"), {"code": "000000"})
        self.assertTrue(TOTPDevice.objects.exists())
        self.client.post(reverse("security:2fa_disable"), {"code": current_code(device, 1)})
        self.assertFalse(TOTPDevice.objects.exists())

    def test_admin_login_requires_captcha_after_failures(self):
        for _ in range(3):
            self.client.post(reverse("admin:login"), {"username": "boss", "password": "wrong"})
        self.assertContains(self.client.get(reverse("admin:login")), "图形验证码")
        self.client.post(reverse("admin:login"), {"username": "boss", "password": PASSWORD, "captcha": "XXXX"})
        self.assertNotIn("_auth_user_id", self.client.session)


class SecurityHeaderTests(TestCase):
    def test_csp_and_permissions_policy(self):
        response = self.client.get(reverse("web:home"))
        csp = response["Content-Security-Policy"]
        self.assertIn("script-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertNotIn("unsafe-inline", csp.split("script-src")[1].split(";")[0])
        self.assertIn("camera=(self)", response["Permissions-Policy"])
