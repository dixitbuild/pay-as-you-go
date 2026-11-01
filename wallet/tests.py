from decimal import Decimal

from django.db import IntegrityError, transaction
from rest_framework.test import APITestCase

from accounts.models import User
from wallet.models import LedgerEntry, Wallet


class WalletTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="pw", role="USER")
        self.client.force_authenticate(self.user)

    def recharge(self, amount="500.00"):
        return self.client.post("/wallet/recharge/", {"amount": amount}).data["reference"]

    def callback(self, reference, status="success"):
        # the webhook is not authenticated
        self.client.force_authenticate(None)
        r = self.client.post("/wallet/recharge/callback/", {"reference": reference, "status": status})
        self.client.force_authenticate(self.user)
        return r

    def balance(self):
        return Decimal(self.client.get("/wallet/").data["balance"])

    def test_new_wallet_is_zero(self):
        self.assertEqual(self.balance(), Decimal("0"))

    def test_recharge_is_pending_until_callback(self):
        ref = self.recharge()
        self.assertEqual(self.balance(), Decimal("0"))
        self.assertEqual(self.callback(ref).data["status"], "success")
        self.assertEqual(self.balance(), Decimal("500"))

    # Required scenario 5
    def test_duplicate_success_callback_credits_once(self):
        ref = self.recharge()
        self.assertEqual(self.callback(ref).status_code, 200)
        self.assertEqual(self.callback(ref).status_code, 200)
        self.assertEqual(self.balance(), Decimal("500"))
        self.assertEqual(LedgerEntry.objects.filter(type="credit").count(), 1)

    def test_failed_callback_does_not_credit(self):
        ref = self.recharge()
        self.callback(ref, "failed")
        self.assertEqual(self.balance(), Decimal("0"))

    def test_failed_after_success_changes_nothing(self):
        ref = self.recharge()
        self.callback(ref, "success")
        r = self.callback(ref, "failed")
        self.assertEqual(r.data["status"], "success")
        self.assertEqual(self.balance(), Decimal("500"))

    def test_success_after_failed_does_not_credit(self):
        ref = self.recharge()
        self.callback(ref, "failed")
        self.callback(ref, "success")
        self.assertEqual(self.balance(), Decimal("0"))

    def test_unknown_reference_is_404(self):
        self.assertEqual(self.callback("rch_nope").status_code, 404)

    def test_invalid_amount_is_400(self):
        r = self.client.post("/wallet/recharge/", {"amount": "0"})
        self.assertEqual(r.status_code, 400)

    def test_requires_auth(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/wallet/").status_code, 401)

    def test_db_refuses_negative_balance(self):
        Wallet.objects.create(user=self.user, balance=10)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Wallet.objects.filter(user=self.user).update(balance=-1)
