from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied

from accounts.models import User
from config.exceptions import DomainError, InsufficientBalance, InvalidTransition
from wallet import services as wallet_services

from .models import Session

S = Session.Status

# The state machine: for each action, the states it may start from.
TRANSITIONS = {
    "assign": {S.UNASSIGNED},
    "accept": {S.ASSIGNED},
    "start": {S.ACCEPTED},
    "end": {S.IN_PROGRESS},
    "cancel": {S.UNASSIGNED, S.ASSIGNED, S.ACCEPTED},
}

ENDED_BY_USER = "user"
ENDED_BY_PROVIDER = "provider"
ENDED_BY_SYSTEM_NO_BALANCE = "system:insufficient_balance"


def _lock(session_id):
    """Row-lock a session. Must be called inside transaction.atomic()."""
    try:
        return Session.objects.select_for_update().get(pk=session_id)
    except Session.DoesNotExist:
        raise NotFound("Session not found.")


def _check_transition(session, action):
    if session.status not in TRANSITIONS[action]:
        raise InvalidTransition(f"Cannot {action} a session that is {session.status}.")


def _require_owner(session, user):
    if session.user_id != user.id:
        raise PermissionDenied("Only the user who owns this session can do this.")


def _require_assigned_provider(session, user):
    if session.provider_id != user.id:
        raise PermissionDenied("Only the provider assigned to this session can do this.")


def _is_participant(session, user):
    return user.id in (session.user_id, session.provider_id)


def get_session(session_id, user):
    session = Session.objects.filter(pk=session_id).first()
    if session is None:
        raise NotFound("Session not found.")
    if not _is_participant(session, user):
        raise PermissionDenied("You are not part of this session.")
    return session


def create_session(user):
    return Session.objects.create(user=user)


@transaction.atomic
def assign(session_id, user, provider_id):
    session = _lock(session_id)
    _require_owner(session, user)
    _check_transition(session, "assign")
    provider = User.objects.filter(pk=provider_id, role=User.Role.PROVIDER).first()
    if provider is None:
        raise DomainError("Provider not found.")
    session.provider = provider
    session.status = S.ASSIGNED
    session.save()
    return session


@transaction.atomic
def accept(session_id, user):
    session = _lock(session_id)
    _require_assigned_provider(session, user)
    _check_transition(session, "accept")
    session.status = S.ACCEPTED
    session.save()
    return session


@transaction.atomic
def start(session_id, user, now=None):
    now = now or timezone.now()
    session = _lock(session_id)
    _require_owner(session, user)
    _check_transition(session, "start")

    rate = settings.SESSION_RATE_PER_MINUTE
    required = rate * settings.MIN_START_MINUTES
    if wallet_services.get_wallet(user).balance < required:
        raise InsufficientBalance(f"Insufficient balance. At least {required} is required to start a session.")

    if Session.objects.filter(user=user, status=S.IN_PROGRESS).exists():
        raise DomainError("You already have a session in progress.")

    session.rate_per_minute = rate  # fixed for the life of the session
    session.started_at = now
    session.status = S.IN_PROGRESS
    try:
        with transaction.atomic():  # savepoint, so the DB constraint becomes a clean error
            session.save()
    except IntegrityError:
        raise DomainError("You already have a session in progress.")
    return session


def _bill(session, now):
    """Charge every full elapsed minute not yet charged. Caller holds the session lock."""
    elapsed_minutes = int((now - session.started_at).total_seconds() // 60)
    for _ in range(elapsed_minutes - session.billed_minutes):
        try:
            wallet_services.debit(
                session.user, session.rate_per_minute, session, minute_index=session.billed_minutes + 1
            )
        except InsufficientBalance:
            session.status = S.COMPLETED
            session.ended_by = ENDED_BY_SYSTEM_NO_BALANCE
            session.ended_at = now
            session.billable_seconds = session.billed_minutes * 60
            break
        session.billed_minutes += 1
        session.total_billed += session.rate_per_minute
    session.save()


@transaction.atomic
def bill_session(session_id, now=None):
    """Bill an in-progress session. Calling it again for the same minute charges nothing."""
    now = now or timezone.now()
    session = _lock(session_id)
    if session.status == S.IN_PROGRESS:
        _bill(session, now)
    return session


@transaction.atomic
def end(session_id, user, now=None):
    now = now or timezone.now()
    session = _lock(session_id)
    if not _is_participant(session, user):
        raise PermissionDenied("You are not part of this session.")
    _check_transition(session, "end")

    _bill(session, now)  # settle any full minutes owed first
    if session.status == S.IN_PROGRESS:  # not already auto-ended for lack of balance
        session.status = S.COMPLETED
        session.ended_by = ENDED_BY_USER if user.id == session.user_id else ENDED_BY_PROVIDER
        session.ended_at = now
        session.billable_seconds = int((now - session.started_at).total_seconds())
        session.save()
    return session


@transaction.atomic
def cancel(session_id, user):
    session = _lock(session_id)
    if not _is_participant(session, user):
        raise PermissionDenied("You are not part of this session.")
    _check_transition(session, "cancel")
    session.status = S.CANCELLED
    session.save()
    return session
