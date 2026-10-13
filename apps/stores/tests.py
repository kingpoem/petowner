from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.testing import PASSWORD, STORE_PASSWORD, make_order, make_room, make_store, make_store_user


class StoreScopeTests(TestCase):
    def test_orders_visible_across_stores(self):
        a = make_store(code="a", name="A店", is_default=True)
        b = make_store(code="b", name="B店")
        ra, rb = make_room(store=a), make_room(store=b)
        oa, ob = make_order(room=ra), make_order(room=rb)
        admin = make_store_user(role="admin", username="boss2")
        self.client.force_login(admin)
        response = self.client.get(reverse("admin:bookings_order_changelist"))
        self.assertContains(response, oa.order_no)
        self.assertContains(response, ob.order_no)


class StoreStaffFactoryTests(TestCase):
    """门店账号测试注入。"""

    def test_make_store_user_front(self):
        user = make_store_user(role="front", username="front01", name="前台甲")
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.groups.filter(name="前台").exists())
        self.assertTrue(user.check_password(STORE_PASSWORD))

    def test_make_store_user_carer(self):
        user = make_store_user(role="carer", username="carer01")
        self.assertTrue(user.is_staff)
        self.assertTrue(user.groups.filter(name="护理师").exists())
        self.assertFalse(user.groups.filter(name="前台").exists())

    def test_make_store_user_admin(self):
        user = make_store_user(role="admin", username="storeboss")
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)

    def test_front_can_open_store_index(self):
        user = make_store_user(role="front", username="desk01")
        self.client.force_login(user)
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "门店功能")
        self.assertNotContains(response, "ps-kpi-card")

    def test_front_can_mark_paid_via_admin(self):
        user = make_store_user(role="front", username="desk02")
        order = make_order(start=2)
        self.client.force_login(user)
        self.client.post(
            reverse("admin:bookings_order_changelist"),
            {"action": "mark_paid", "_selected_action": [order.pk]},
        )
        order.refresh_from_db()
        from apps.bookings.models import Order

        self.assertEqual(order.payment_status, Order.PaymentStatus.PAID)

    def test_store_login_via_website(self):
        user = make_store_user(role="front", username="13988880001", password=PASSWORD)
        response = self.client.post(
            reverse("web:login"),
            {"role": "store", "username": user.username, "password": PASSWORD},
        )
        self.assertRedirects(response, reverse("admin:index"), fetch_redirect_response=False)
        self.assertTrue(reverse("admin:index").startswith("/store/"))


class SeedDemoStoreInjectionTests(TestCase):
    """seed_demo 门店数据注入。"""

    def test_seed_creates_store_staff_accounts(self):
        call_command("seed_demo")
        User = get_user_model()
        admin = User.objects.get(username="admin")
        front = User.objects.get(username="13900000001")
        carer = User.objects.get(username="13900000002")
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.check_password("admin123"))
        self.assertTrue(front.is_staff)
        self.assertTrue(front.groups.filter(name="前台").exists())
        self.assertTrue(front.check_password("pawstay123"))
        self.assertTrue(carer.is_staff)
        self.assertTrue(carer.groups.filter(name="护理师").exists())
        self.assertTrue(Group.objects.filter(name="前台").exists())
        self.assertTrue(Group.objects.filter(name="护理师").exists())

    def test_seed_is_idempotent_for_store_staff(self):
        call_command("seed_demo")
        call_command("seed_demo")
        self.assertEqual(get_user_model().objects.filter(username="13900000001").count(), 1)
        self.assertEqual(get_user_model().objects.filter(username="admin").count(), 1)
