from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.stores.models import StaffStore
from apps.testing import days, make_order, make_room, make_store


class StoreScopeTests(TestCase):
    def test_calendar_add_link_on_empty_cell(self):
        room = make_room()
        admin = get_user_model().objects.create_superuser("cal2", "", "pw")
        self.client.force_login(admin)
        session = self.client.session
        session["current_store"] = room.store.code
        session.save()
        response = self.client.get(reverse("admin:bookings_order_calendar"), {"nights": "7", "start": days(1).isoformat()})
        self.assertContains(response, "ps-cal-add")
        self.assertContains(response, f"room={room.pk}")

    def test_order_list_filtered_by_store(self):
        a = make_store(code="a", name="A店", is_default=True)
        b = make_store(code="b", name="B店")
        ra, rb = make_room(store=a), make_room(store=b)
        oa, ob = make_order(room=ra), make_order(room=rb)
        admin = get_user_model().objects.create_superuser("boss2", "", "pw")
        self.client.force_login(admin)
        session = self.client.session
        session["current_store"] = a.code
        session.save()
        response = self.client.get(reverse("admin:bookings_order_changelist"))
        self.assertContains(response, oa.order_no)
        self.assertNotContains(response, ob.order_no)

    def test_staff_store_restricts_session_store(self):
        a = make_store(code="sa", name="南店", is_default=True)
        b = make_store(code="sb", name="北店")
        User = get_user_model()
        clerk = User.objects.create_user("clerk_store", password="pw", is_staff=True)
        StaffStore.objects.create(user=clerk, store=b)
        self.client.force_login(clerk)
        response = self.client.get("/", {"store": a.code})
        self.assertEqual(response.wsgi_request.store, b)
