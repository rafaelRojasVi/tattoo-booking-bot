# Lead status strings (reference)

Canonical status values and transitions for contract and log traceability.

## Source of truth

- **Constants:** [app/constants/statuses.py](../../app/constants/statuses.py) — all `STATUS_*` string constants.
- **Transitions:** [app/services/conversation/state_machine.py](../../app/services/conversation/state_machine.py) — `ALLOWED_TRANSITIONS`, `transition()`, `get_state_semantics()`.

## Top-level status categories

| Category | Statuses |
|----------|----------|
| **Qualifying** | `NEW`, `QUALIFYING` |
| **Approval / deposit** | `PENDING_APPROVAL`, `AWAITING_DEPOSIT`, `DEPOSIT_PAID`, `BOOKING_PENDING` |
| **Booked** | `BOOKED` |
| **Operational** | `NEEDS_ARTIST_REPLY`, `NEEDS_FOLLOW_UP`, `REJECTED` |
| **Time windows** | `COLLECTING_TIME_WINDOWS` |
| **Tour / waitlist** | `TOUR_CONVERSION_OFFERED`, `WAITLISTED` |
| **Payment / cancellation** | `DEPOSIT_EXPIRED`, `REFUNDED`, `CANCELLED` |
| **Housekeeping** | `ABANDONED`, `STALE`, `OPTOUT` |
| **Legacy** | `NEEDS_MANUAL_FOLLOW_UP`, `BOOKING_LINK_SENT` |

Terminal states (no further transitions) are defined in the state machine (e.g. `BOOKED`, `REJECTED`, `ABANDONED`, `STALE`, `WAITLISTED`, `OPTOUT`).
