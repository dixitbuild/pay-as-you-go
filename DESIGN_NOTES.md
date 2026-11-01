# Design Notes

## Structure
Business rules live in `services.py` (`wallet/`, `sessions_app/`). Views parse input, call one service function and return the result. Domain errors (`InvalidTransition`, `InsufficientBalance`, `DomainError`) are mapped to HTTP 400 in one place, `config/exceptions.py`.

## Money
- `DecimalField` everywhere. No floats.
- `CheckConstraint(balance >= 0)` is the last line of defence. The `debit` service refuses first, so the constraint should never fire.
- Every credit and debit writes a `LedgerEntry`, so any balance can be reconciled.

## Idempotent recharge
`reference` is unique. The callback locks the transaction row (`select_for_update`) inside `atomic()` and only acts while the status is `pending`. Any later callback, `success` or `failed`, returns 200 and changes nothing, so the wallet is credited once and a late `failed` cannot undo a `success`.

## State machine
One dict, `TRANSITIONS`, maps each action to the states it may start from. Every service calls `_check_transition` and raises `InvalidTransition` (400, naming the current state). Ownership and role checks come first and raise 403. The one-active-session rule is enforced twice: a check in `start`, and a partial unique constraint on `user` where `status = in_progress` for races.

## Billing
- `bill_session(session_id, now=None)`: `now` is injectable, so tests use a mocked clock and never sleep.
- `to_charge = floor(elapsed / 60s) - billed_minutes`, charged one minute at a time. A second call for the same minute computes zero.
- Backup guard: a unique `(session, minute_index)` on debit ledger entries.
- If a minute cannot be paid: no debit, the session becomes `completed` with `ended_by = system:insufficient_balance`, and `billable_seconds = billed_minutes * 60`.
- Late billing is safe. If billing runs hours late, it charges minute by minute and stops at the first unaffordable one.

## Partial minutes (decision)
Only full minutes are charged. A user or provider ending at 1:30 pays for 1 minute, and the extra 30 seconds are free. The real talk time is still saved in `billable_seconds`. This is the simplest rule to explain and never charges for time the user did not complete. The trade-off is that the provider is not paid for the last partial minute.

## Rate
One global setting, `SESSION_RATE_PER_MINUTE`, copied onto the session at start. Changing the setting later does not affect running sessions (tested).

## Concurrency
Every wallet change and billing run is in `transaction.atomic()` with `select_for_update()`. Lock order is always session, then wallet. SQLite ignores row locks (it serializes writes), PostgreSQL honors them.

## Not done on purpose
No background worker. Billing is triggered by `POST /sessions/<id>/bill/` or `python manage.py bill_active_sessions` from cron.
