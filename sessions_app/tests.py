from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest import mock

from django.db import IntegrityError, transaction
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from sessions_app.models import Session
from wallet import services as wallet_services
from wallet.models import LedgerEntry

T0 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=dt_timezone.utc)
CLOCK = "sessions_app.services.timezone.now"


def at(**delta):
    """Patch the service clock to T0 + delta, so tests never sleep."""
    return mock.patch(CLOCK, return_value=T0 + timedelta(**delta))


class SessionBase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="pw", role="USER")
        self.provider = User.objects.create_user("dr_bob", password="pw", role="PROVIDER")
        self.user_api = APIClient()
        self.user_api.force_authenticate(self.user)
        self.provider_api = APIClient()
        self.provider_api.force_authenticate(self.provider)

    def fund(self, amount, user=None):
        user = user or self.user
        txn = wallet_services.create_recharge(user, Decimal(amount))
        wallet_services.process_callback(txn.reference, "success")

    def balance(self, user=None):
        return wallet_services.get_wallet(user or self.user).balance

    def accepted_session(self, api=None):
        api = api or self.user_api
        sid = api.post("/sessions/").data["id"]
        api.post(f"/sessions/{sid}/assign/", {"provider_id": self.provider.id})
        self.provider_api.post(f"/sessions/{sid}/accept/")
        return sid

    def in_progress_session(self):
        sid = self.accepted_session()
        with at():
            r = self.user_api.post(f"/sessions/{sid}/start/")
        self.assertEqual(r.status_code, 200, r.data)
        return sid


class RequiredScenarios(SessionBase):
    # 1
    def test_insufficient_balance_cannot_start(self):
        self.fund("249")  # needs 5 x 50 = 250
        sid = self.accepted_session()
        r = self.user_api.post(f"/sessions/{sid}/start/")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Insufficient balance", r.data["error"])
        self.assertEqual(Session.objects.get(pk=sid).status, "accepted_by_provider")

    # 2
    def test_happy_path(self):
        wallet_services.create_recharge(self.user, Decimal("500"))
        ref = self.user.recharges.get().reference
        self.assertEqual(self.client.post("/wallet/recharge/callback/", {"reference": ref, "status": "success"}).status_code, 200)

        sid = self.accepted_session()
        with at():
            started = self.user_api.post(f"/sessions/{sid}/start/")
        self.assertEqual(started.data["status"], "in_progress")

        with at(minutes=2, seconds=5):
            self.assertEqual(self.user_api.post(f"/sessions/{sid}/bill/").data["billed_minutes"], 2)
            ended = self.user_api.post(f"/sessions/{sid}/end/")

        self.assertEqual(ended.status_code, 200)
        self.assertEqual(ended.data["status"], "completed")
        self.assertEqual(ended.data["ended_by"], "user")
        self.assertEqual(Decimal(ended.data["total_billed"]), Decimal("100"))
        self.assertEqual(self.balance(), Decimal("400"))  # 500 - 2 x 50
        self.assertEqual(LedgerEntry.objects.filter(type="debit").count(), 2)

    # 3
    def test_balance_runs_out_auto_ends_session(self):
        self.fund("260")
        sid = self.in_progress_session()
        with at(minutes=5):
            self.user_api.post(f"/sessions/{sid}/bill/")
        self.assertEqual(self.balance(), Decimal("10"))
        with at(minutes=6):
            r = self.user_api.post(f"/sessions/{sid}/bill/")
        self.assertEqual(r.data["status"], "completed")
        self.assertEqual(r.data["ended_by"], "system:insufficient_balance")
        self.assertEqual(r.data["billed_minutes"], 5)
        self.assertEqual(r.data["billable_seconds"], 300)
        self.assertEqual(self.balance(), Decimal("10"))  # never negative, nothing taken for minute 6

    def test_spec_example_wallet_stays_at_40(self):
        # Balance 40, rate 50: the next minute can't be paid, wallet untouched.
        self.fund("250")
        sid = self.in_progress_session()
        Session.objects.filter(pk=sid).update(billed_minutes=0)
        wallet_services.debit(self.user, Decimal("210"), None, None)  # leave 40
        with at(minutes=1):
            r = self.user_api.post(f"/sessions/{sid}/bill/")
        self.assertEqual(r.data["ended_by"], "system:insufficient_balance")
        self.assertEqual(self.balance(), Decimal("40"))

    # 4
    def test_end_before_start_is_400(self):
        sid = self.accepted_session()
        r = self.user_api.post(f"/sessions/{sid}/end/")
        self.assertEqual(r.status_code, 400)
        self.assertIn("accepted_by_provider", r.data["error"])

    # 5 lives in wallet/tests.py

    # 6
    def test_duplicate_billing_charges_once(self):
        self.fund("500")
        sid = self.in_progress_session()
        with at(minutes=1, seconds=10):
            first = self.user_api.post(f"/sessions/{sid}/bill/")
            second = self.user_api.post(f"/sessions/{sid}/bill/")
            third = self.provider_api.post(f"/sessions/{sid}/bill/")
        self.assertEqual(first.data["billed_minutes"], 1)
        self.assertEqual(second.data["billed_minutes"], 1)
        self.assertEqual(third.data["billed_minutes"], 1)
        self.assertEqual(self.balance(), Decimal("450"))
        self.assertEqual(LedgerEntry.objects.filter(type="debit").count(), 1)


class StateMachineTests(SessionBase):
    def test_invalid_transitions_return_400(self):
        sid = self.user_api.post("/sessions/").data["id"]
        self.assertEqual(self.user_api.post(f"/sessions/{sid}/start/").status_code, 400)  # unassigned
        self.assertEqual(self.user_api.post(f"/sessions/{sid}/end/").status_code, 400)
        self.user_api.post(f"/sessions/{sid}/assign/", {"provider_id": self.provider.id})
        self.assertEqual(self.user_api.post(f"/sessions/{sid}/assign/", {"provider_id": self.provider.id}).status_code, 400)
        self.assertEqual(self.user_api.post(f"/sessions/{sid}/start/").status_code, 400)  # not accepted yet
        self.provider_api.post(f"/sessions/{sid}/accept/")
        self.assertEqual(self.provider_api.post(f"/sessions/{sid}/accept/").status_code, 400)

    def test_cannot_end_twice_or_after_auto_end(self):
        self.fund("250")
        sid = self.in_progress_session()
        wallet_services.debit(self.user, Decimal("250"), None, None)
        with at(minutes=1):
            self.user_api.post(f"/sessions/{sid}/bill/")  # auto-ends
        r = self.user_api.post(f"/sessions/{sid}/end/")
        self.assertEqual(r.status_code, 400)

    def test_provider_can_end_session(self):
        self.fund("500")
        sid = self.in_progress_session()
        with at(minutes=1, seconds=30):
            r = self.provider_api.post(f"/sessions/{sid}/end/")
        self.assertEqual(r.data["ended_by"], "provider")
        self.assertEqual(r.data["billed_minutes"], 1)  # partial half minute is free
        self.assertEqual(r.data["billable_seconds"], 90)

    def test_cancel_before_start(self):
        sid = self.accepted_session()
        r = self.user_api.post(f"/sessions/{sid}/cancel/")
        self.assertEqual(r.data["status"], "cancelled")
        self.assertEqual(self.user_api.post(f"/sessions/{sid}/cancel/").status_code, 400)

    def test_cannot_cancel_in_progress(self):
        self.fund("500")
        sid = self.in_progress_session()
        self.assertEqual(self.user_api.post(f"/sessions/{sid}/cancel/").status_code, 400)

    def test_billing_not_started_session_does_nothing(self):
        sid = self.accepted_session()
        r = self.user_api.post(f"/sessions/{sid}/bill/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["billed_minutes"], 0)

    def test_assign_unknown_provider_is_400(self):
        sid = self.user_api.post("/sessions/").data["id"]
        r = self.user_api.post(f"/sessions/{sid}/assign/", {"provider_id": self.user.id})  # a USER, not provider
        self.assertEqual(r.status_code, 400)


class RuleTests(SessionBase):
    def test_one_active_session_per_user(self):
        self.fund("1000")
        self.in_progress_session()
        second = self.accepted_session()
        r = self.user_api.post(f"/sessions/{second}/start/")
        self.assertEqual(r.status_code, 400)
        self.assertIn("already have a session in progress", r.data["error"])

    def test_db_constraint_blocks_two_in_progress(self):
        Session.objects.create(user=self.user, status="in_progress")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Session.objects.create(user=self.user, status="in_progress")

    def test_rate_is_fixed_after_start(self):
        self.fund("500")
        sid = self.in_progress_session()
        with self.settings(SESSION_RATE_PER_MINUTE=999):
            with at(minutes=2):
                r = self.user_api.post(f"/sessions/{sid}/bill/")
        self.assertEqual(Decimal(r.data["rate_per_minute"]), Decimal("50"))
        self.assertEqual(self.balance(), Decimal("400"))

    def test_wallet_never_negative_over_long_gap(self):
        self.fund("250")
        sid = self.in_progress_session()
        with at(hours=3):  # billing finally runs 180 minutes late
            r = self.user_api.post(f"/sessions/{sid}/bill/")
        self.assertEqual(r.data["status"], "completed")
        self.assertEqual(r.data["billed_minutes"], 5)
        self.assertEqual(self.balance(), Decimal("0"))

    def test_billing_command(self):
        from django.core.management import call_command
        self.fund("500")
        sid = self.in_progress_session()
        with at(minutes=3):
            call_command("bill_active_sessions", stdout=mock.MagicMock())
        self.assertEqual(Session.objects.get(pk=sid).billed_minutes, 3)


class PermissionTests(SessionBase):
    def test_provider_cannot_create_session(self):
        self.assertEqual(self.provider_api.post("/sessions/").status_code, 403)

    def test_user_cannot_accept(self):
        sid = self.user_api.post("/sessions/").data["id"]
        self.user_api.post(f"/sessions/{sid}/assign/", {"provider_id": self.provider.id})
        self.assertEqual(self.user_api.post(f"/sessions/{sid}/accept/").status_code, 403)

    def test_other_provider_cannot_accept(self):
        other = User.objects.create_user("dr_eve", password="pw", role="PROVIDER")
        api = APIClient()
        api.force_authenticate(other)
        sid = self.user_api.post("/sessions/").data["id"]
        self.user_api.post(f"/sessions/{sid}/assign/", {"provider_id": self.provider.id})
        self.assertEqual(api.post(f"/sessions/{sid}/accept/").status_code, 403)

    def test_other_user_cannot_touch_session(self):
        stranger = User.objects.create_user("mallory", password="pw", role="USER")
        api = APIClient()
        api.force_authenticate(stranger)
        sid = self.user_api.post("/sessions/").data["id"]
        self.assertEqual(api.get(f"/sessions/{sid}/").status_code, 403)
        self.assertEqual(api.post(f"/sessions/{sid}/assign/", {"provider_id": self.provider.id}).status_code, 403)

    def test_provider_cannot_start(self):
        sid = self.accepted_session()
        self.assertEqual(self.provider_api.post(f"/sessions/{sid}/start/").status_code, 403)

    def test_unauthenticated_is_401(self):
        self.assertEqual(APIClient().post("/sessions/").status_code, 401)

    def test_missing_session_is_404(self):
        self.assertEqual(self.user_api.get("/sessions/9999/").status_code, 404)
