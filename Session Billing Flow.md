# How a paid session works, start to finish

Wallet, session state machine and per-minute billing for the Django assignment. Example numbers: rate Rs 50 per minute, so a session needs at least Rs 250 to start.

1 · The whole journey

## Happy path: recharge, book, talk, pay

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant API as Django API
    participant W as Wallet
    participant P as Provider
    U->>API: POST /wallet/recharge/ (Rs 500)
    API-->>U: pending transaction + reference
    U->>API: POST /wallet/recharge/callback/ (success)
    API->>W: credit 500 (once)
    U->>API: POST /sessions/ then /assign/ (provider_id)
    Note over API: unassigned then assigned
    P->>API: POST /sessions/id/accept/
    Note over API: accepted_by_provider
    U->>API: POST /sessions/id/start/
    API->>W: check balance at least 250
    Note over API: in_progress, rate 50 saved on session
    loop every minute (endpoint or management command)
        API->>W: debit 50 for the next full minute
    end
    U->>API: POST /sessions/id/end/
    Note over API: bills any full minutes owed, then completed
    API-->>U: after 2 minutes wallet shows 400
      
```

Every arrow into the wallet goes through one locked, atomic service function. Nothing else can change the balance.

2 · Money in

## Recharge, and why a repeated callback is harmless

```mermaid
flowchart TD
    A["POST /wallet/recharge/ with amount"] --> B["Create RechargeTransaction: pending, unique reference"]
    B --> C["Mock gateway calls POST /wallet/recharge/callback/ with reference and status"]
    C --> D["Start atomic block and lock the transaction row"]
    D --> E{"Stored status?"}
    E -- pending --> F{"Callback status?"}
    F -- success --> G["Credit wallet, write credit ledger entry, set status success"]
    F -- failed --> H["Set status failed, no credit"]
    E -- "already success or failed" --> I["No-op, return 200, wallet untouched"]
      
```

The row lock makes two simultaneous callbacks queue up. The second one sees `success` and does nothing, so the wallet is credited once.

3 · Session states

## The state machine

```mermaid
stateDiagram-v2
    [*] --> unassigned: user creates
    unassigned --> assigned: assign by user
    assigned --> accepted_by_provider: accept by provider
    accepted_by_provider --> in_progress: start by user, balance at least 5 x rate
    in_progress --> completed: end by user or provider
    in_progress --> completed: system, next minute unaffordable
    unassigned --> cancelled: cancel
    assigned --> cancelled: cancel
    accepted_by_provider --> cancelled: cancel
    completed --> [*]
    cancelled --> [*]
      
```

Any arrow not drawn here is rejected with HTTP 400 and a message naming the current state. Example: ending a session that is still `accepted_by_provider`.

| Action | Who may call it | Wrong person gets |
| --- | --- | --- |
| assign, start, cancel (before start) | The user who owns the session | 403 |
| accept | The provider the session is assigned to | 403 |
| end | Owning user or assigned provider | 403 |
| bill | Owner, provider, or the management command | 403 |

4 · Money out

## Billing one call at a time

```mermaid
flowchart TD
    A["bill_session called with now"] --> B["Start atomic block, lock session then wallet"]
    B --> C{"status is in_progress?"}
    C -- no --> Z1["Return, nothing to do"]
    C -- yes --> D["to_charge = floor(elapsed seconds / 60) - billed_minutes"]
    D --> E{"to_charge above 0?"}
    E -- no --> Z2["Charge nothing: those minutes are already billed"]
    E -- yes --> F{"balance at least rate?"}
    F -- yes --> G["Debit rate, billed_minutes + 1, write ledger entry for that minute"]
    G --> H{"more minutes to charge?"}
    H -- yes --> F
    H -- no --> Z3["Done"]
    F -- no --> I["End session: completed, ended_by system:insufficient_balance, save billable_seconds. Balance unchanged"]
      
```

Calling it twice in the same minute: the second call computes `to_charge = 0` because `billed_minutes` already moved. A unique (session, minute) ledger constraint backs that up in the database.

5 · Running out of money

## Example: Rs 260 in the wallet, Rs 50 per minute

| Elapsed | Action | Wallet | billed_minutes |
| --- | --- | --- | --- |
| 0:00 | Start allowed (260 is at least 250). Rate 50 is saved. | 260 | 0 |
| 1:00 to 5:00 | Five bills, one per minute | 10 | 5 |
| 6:00 | Bill: balance 10 is below 50. Session ends, ended_by system:insufficient_balance. | 10 (never negative) | 5 |

6 · Safety nets

## What protects the money, in layers

| Risk | Service layer | Database layer |
| --- | --- | --- |
| Negative balance | Debit refuses if balance is below amount | CheckConstraint balance at least 0 |
| Duplicate recharge credit | Lock row, credit only if pending | Unique reference |
| Same minute billed twice | billed_minutes counter | Unique (session, minute_index) on ledger |
| Two active sessions | Check before start | Partial unique on user where in_progress |
| Races between requests | atomic + select_for_update, always session then wallet | Row locks |

7 · Edge cases from the review

## Details to settle in the code

- A user ends a session that bill already auto-ended: the second call gets 400, because the state is already `completed`. Correct, and worth a test.
- A `failed` callback after a `success` one, or the reverse, must not change anything. Only `pending` can move.
- Partial last minute: free (full minutes only). `billable_seconds` still stores the real talk time.
- On auto-end, `billable_seconds` is set to billed minutes times 60, since the unpaid minute was not talk time the user paid for.
- Callback endpoint: no auth in the mock, so it should only accept references that exist and return 404 for unknown ones.
- Always lock in the same order (session, then wallet) so two requests cannot deadlock.