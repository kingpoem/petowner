from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.loyalty.models import Coupon, PointLedger
from apps.loyalty.services import (
    apply_coupon,
    available_coupons,
    award_points,
    lookup_coupon,
    membership_tier,
    preview_loyalty_discount,
    redeem_points,
)
from apps.testing import days, make_order, make_owner, make_store


class LoyaltyTests(TestCase):
    @override_settings(LOYALTY_POINTS_PER_YUAN=1, LOYALTY_POINTS_PER_YUAN_REDEEM=100)
    def test_award_and_redeem(self):
        owner = make_owner()
        order = make_order()
        award_points(owner, Decimal("188.50"), order=order)
        owner.refresh_from_db()
        self.assertEqual(owner.points, 188)
        self.assertEqual(PointLedger.objects.filter(owner=owner, kind=PointLedger.Kind.EARN).count(), 1)
        # 同单不重复发分
        award_points(owner, Decimal("50"), order=order)
        owner.refresh_from_db()
        self.assertEqual(owner.points, 188)

        money, ledger = redeem_points(owner, 100, order=order)
        self.assertEqual(money, Decimal("1.00"))
        owner.refresh_from_db()
        self.assertEqual(owner.points, 88)
        self.assertEqual(ledger.points, -100)

    def test_coupon_fixed(self):
        owner = make_owner()
        store = make_store(is_default=True)
        today = timezone.localdate()
        coupon = Coupon.objects.create(
            code="SAVE20",
            name="满减",
            kind=Coupon.Kind.FIXED,
            value=Decimal("20"),
            min_amount=Decimal("100"),
            store=store,
            valid_from=today,
            valid_until=days(30),
        )
        c, discount = lookup_coupon("save20", owner, Decimal("150"), store=store)
        self.assertEqual(c.pk, coupon.pk)
        self.assertEqual(discount, Decimal("20"))
        order = make_order()
        apply_coupon(coupon, owner, order, discount)
        self.assertEqual(coupon.redemptions.count(), 1)
        with self.assertRaises(ValidationError):
            lookup_coupon("SAVE20", owner, Decimal("150"), store=store)

    def test_membership_and_preview(self):
        owner = make_owner()
        tier = membership_tier(owner)
        self.assertEqual(tier.key, "bronze")
        preview = preview_loyalty_discount(owner, Decimal("200"), coupon_code="", redeem_points=0)
        self.assertEqual(preview["payable"], Decimal("200"))
        self.assertEqual(available_coupons(owner), [])

    def test_loyalty_page(self):
        from django.urls import reverse

        from apps.testing import PASSWORD

        owner = make_owner()
        self.client.login(username=owner.phone, password=PASSWORD)
        response = self.client.get(reverse("web:loyalty"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "可用积分")
