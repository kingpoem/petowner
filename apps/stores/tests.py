from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.testing import days, make_order, make_room, make_store


class StoreScopeTests(TestCase):
    def test_calendar_add_link_on_empty_cell(self):
        room = make_room()
        admin = get_user_model().objects.create_superuser("cal2", "", "pw")
        self.client.force_login(admin)
        response = self.client.get(
            reverse("admin:bookings_order_calendar"),
            {"nights": "7", "start": days(1).isoformat()},
        )
        self.assertContains(response, "ps-cal-add")
        self.assertContains(response, f"room={room.pk}")

    def test_orders_visible_across_stores(self):
        a = make_store(code="a", name="A店", is_default=True)
        b = make_store(code="b", name="B店")
        ra, rb = make_room(store=a), make_room(store=b)
        oa, ob = make_order(room=ra), make_order(room=rb)
        admin = get_user_model().objects.create_superuser("boss2", "", "pw")
        self.client.force_login(admin)
        response = self.client.get(reverse("admin:bookings_order_changelist"))
        self.assertContains(response, oa.order_no)
        self.assertContains(response, ob.order_no)
