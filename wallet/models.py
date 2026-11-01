from django.conf import settings
from django.db import models
from django.db.models import Q


class Wallet(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wallet")
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(balance__gte=0), name="wallet_balance_non_negative"),
        ]


class RechargeStatus(models.TextChoices):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class LedgerType(models.TextChoices):
    CREDIT = "credit"
    DEBIT = "debit"


class RechargeTransaction(models.Model):
    Status = RechargeStatus

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recharges")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=40, unique=True)
    status = models.CharField(max_length=10, choices=RechargeStatus.choices, default=RechargeStatus.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)


class LedgerEntry(models.Model):
    """One row per wallet credit or debit, so every balance change can be traced."""

    Type = LedgerType

    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name="entries")
    type = models.CharField(max_length=10, choices=LedgerType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    recharge = models.ForeignKey(RechargeTransaction, null=True, blank=True, on_delete=models.SET_NULL)
    session = models.ForeignKey("sessions_app.Session", null=True, blank=True, on_delete=models.SET_NULL)
    minute_index = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # A given minute of a given session can only ever be debited once.
            models.UniqueConstraint(
                fields=["session", "minute_index"],
                condition=Q(type=LedgerType.DEBIT),
                name="one_debit_per_session_minute",
            ),
        ]
