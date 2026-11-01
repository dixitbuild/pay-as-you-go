from django.conf import settings
from django.db import models
from django.db.models import Q


class Session(models.Model):
    class Status(models.TextChoices):
        UNASSIGNED = "unassigned"
        ASSIGNED = "assigned"
        ACCEPTED = "accepted_by_provider"
        IN_PROGRESS = "in_progress"
        COMPLETED = "completed"
        CANCELLED = "cancelled"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sessions")
    provider = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="provider_sessions"
    )
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.UNASSIGNED)
    rate_per_minute = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    billed_minutes = models.PositiveIntegerField(default=0)
    total_billed = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    billable_seconds = models.PositiveIntegerField(default=0)
    ended_by = models.CharField(max_length=40, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # Database-level guarantee: one active session per user.
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(status="in_progress"),
                name="one_in_progress_session_per_user",
            ),
        ]
