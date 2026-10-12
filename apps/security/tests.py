import json
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.testing import PASSWORD, make_owner

from . import captcha, sms


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


class AdminLoginTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = get_user_model().objects.create_superuser("boss", "", PASSWORD)

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
