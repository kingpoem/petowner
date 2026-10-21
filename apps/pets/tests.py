from decimal import Decimal

from django.test import TestCase

from apps.testing import make_owner, make_pet

from .models import PetSize


class PetTests(TestCase):
    def test_size_from_weight(self):
        self.assertEqual(PetSize.from_weight(Decimal("9.9")), PetSize.SMALL)
        self.assertEqual(PetSize.from_weight(Decimal("10")), PetSize.MEDIUM)
        self.assertEqual(PetSize.from_weight(Decimal("25")), PetSize.MEDIUM)
        self.assertEqual(PetSize.from_weight(Decimal("25.1")), PetSize.LARGE)
        self.assertEqual(PetSize.from_weight(None), PetSize.SMALL)

    def test_code_is_generated(self):
        pet = make_pet()
        self.assertEqual(pet.code, f"P{pet.pk:05d}")
        pet.refresh_from_db()
        self.assertEqual(pet.code, f"P{pet.pk:05d}")

    def test_owner_without_account(self):
        owner = make_owner(with_account=False)
        self.assertIsNone(owner.user)
        self.assertIn(owner.phone, str(owner))
