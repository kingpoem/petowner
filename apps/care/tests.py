from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.testing import make_order, make_owner, make_pet

from .models import Review, ServiceRecord


class ServiceRecordTests(TestCase):
    def setUp(self):
        self.owner = make_owner()
        self.order = make_order(pet=make_pet(owner=self.owner), start=0)
        self.order.start_boarding()

    def test_only_for_boarding_or_completed_orders(self):
        pending = make_order()
        with self.assertRaises(ValidationError):
            ServiceRecord(order=pending, staff="小王", care_content="喂食").full_clean()
        ServiceRecord(order=self.order, staff="小王", care_content="喂食").full_clean()

    def test_assigns_record_code(self):
        record = ServiceRecord.objects.create(order=self.order, staff="小王", care_content="早餐吃完")
        self.assertTrue(record.code.startswith("S"))
        self.assertEqual(record.code, f"S{record.pk:05d}")

    def test_normal_record_saves(self):
        record = ServiceRecord.objects.create(
            order=self.order, staff="小王", care_content="早餐吃完", health_status="良好", appetite="全部吃完"
        )
        self.assertEqual(record.care_content, "早餐吃完")
        self.assertFalse(record.needs_attention)

    def test_abnormal_record_flags_pet(self):
        record = ServiceRecord.objects.create(
            order=self.order,
            staff="小王",
            care_content="精神不振",
            health_status="异常",
            health_note="轻微腹泻",
        )
        self.assertTrue(record.needs_attention)
        self.order.pet.refresh_from_db()
        self.assertIn("轻微腹泻", self.order.pet.health_status)

    def test_poor_appetite_needs_attention(self):
        record = ServiceRecord(
            order=self.order, staff="小王", care_content="晚餐", appetite="未进食", health_status="良好"
        )
        self.assertTrue(record.needs_attention)

    def test_editing_preserves_record(self):
        record = ServiceRecord.objects.create(order=self.order, staff="小王", care_content="遛弯")
        record.care_content = "遛弯 30 分钟"
        record.save()
        record.refresh_from_db()
        self.assertEqual(record.care_content, "遛弯 30 分钟")


class ReviewTests(TestCase):
    def test_requires_completed_order(self):
        order = make_order(start=0)
        with self.assertRaises(ValidationError):
            Review(order=order, rating=5).full_clean()
        order.start_boarding()
        order.finish_boarding()
        Review(order=order, rating=5).full_clean()

    def test_rating_range(self):
        order = make_order(start=0)
        order.start_boarding()
        order.finish_boarding()
        with self.assertRaises(ValidationError):
            Review(order=order, rating=6).full_clean()
