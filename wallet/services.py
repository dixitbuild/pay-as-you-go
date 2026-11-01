import uuid

from django.db import transaction
from rest_framework.exceptions import NotFound

from config.exceptions import DomainError, InsufficientBalance

from .models import LedgerEntry, RechargeTransaction, Wallet


def get_wallet(user):
    wallet, _ = Wallet.objects.get_or_create(user=user)
    return wallet


def _locked_wallet(user):
    """Row-lock the user's wallet. Must be called inside transaction.atomic()."""
    get_wallet(user)
    return Wallet.objects.select_for_update().get(user=user)


@transaction.atomic
def credit(user, amount, recharge=None):
    wallet = _locked_wallet(user)
    wallet.balance += amount
    wallet.save(update_fields=["balance"])
    LedgerEntry.objects.create(wallet=wallet, type=LedgerEntry.Type.CREDIT, amount=amount, recharge=recharge)
    return wallet


@transaction.atomic
def debit(user, amount, session, minute_index):
    """Take `amount` from the wallet. Raises InsufficientBalance instead of going negative."""
    wallet = _locked_wallet(user)
    if wallet.balance < amount:
        raise InsufficientBalance("Insufficient wallet balance.")
    wallet.balance -= amount
    wallet.save(update_fields=["balance"])
    LedgerEntry.objects.create(
        wallet=wallet, type=LedgerEntry.Type.DEBIT, amount=amount, session=session, minute_index=minute_index
    )
    return wallet


def create_recharge(user, amount):
    return RechargeTransaction.objects.create(
        user=user, amount=amount, reference=f"rch_{uuid.uuid4().hex[:12]}"
    )


@transaction.atomic
def process_callback(reference, new_status):
    """Mock payment webhook. Safe to call many times for the same reference."""
    try:
        txn = RechargeTransaction.objects.select_for_update().get(reference=reference)
    except RechargeTransaction.DoesNotExist:
        raise NotFound("Unknown recharge reference.")

    # Only a pending transaction can change. Anything else is a repeat: do nothing.
    if txn.status != RechargeTransaction.Status.PENDING:
        return txn

    if new_status == RechargeTransaction.Status.SUCCESS:
        credit(txn.user, txn.amount, recharge=txn)
    elif new_status != RechargeTransaction.Status.FAILED:
        raise DomainError("status must be 'success' or 'failed'.")
    txn.status = new_status
    txn.save(update_fields=["status"])
    return txn
