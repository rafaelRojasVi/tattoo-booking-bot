# Production Hardening: State + Race Safety

## Summary

- **State transitions** are enforced via `app/services/state_machine.py`: hot-path status changes in `conversation.py` use `transition(db, lead, new_status, reason)` instead of direct `lead.status =`.
- **Step advance** is atomic: `advance_step_if_at(db, lead_id, expected_step)` uses `SELECT FOR UPDATE` and only increments when `current_step == expected_step`, so concurrent inbounds cannot double-advance.
- **Latest-wins** for `answers_dict` is already in place: `order_by(LeadAnswer.created_at, LeadAnswer.id)` is used in `_maybe_send_confirmation_summary`, `_complete_qualification`, and `build_handover_packet` (no code changes needed for this).

---

## Edited Files and Why

| File | Why |
|------|-----|
| **app/services/state_machine.py** | Added statuses `STATUS_COLLECTING_TIME_WINDOWS`, `STATUS_BOOKING_LINK_SENT`, `STATUS_NEEDS_MANUAL_FOLLOW_UP` and their allowed transitions; added **restart** rules: `OPTOUT`, `ABANDONED`, `STALE` → `NEW`; added **NEEDS_ARTIST_REPLY** → **OPTOUT** (opt-out wins during handover); added `advance_step_if_at(db, lead_id, expected_step)` with row lock. |
| **app/services/conversation.py** | Replaced direct `lead.status =` with `transition(...)` on hot paths; moved `state_machine` import after constants to avoid circular import; use `advance_step_if_at` for both step-advance sites (after confirmation_sent and main “next question”); **one bypass**: unknown status → `STATUS_NEW` left as direct assign (status not in ALLOWED_TRANSITIONS). Fixed `STATUS_COLLECTING_TIME_WINDOWS` to be a string (was tuple). |
| **app/services/parse_repair.py** | `trigger_handover_after_parse_failure` now calls `transition(db, lead, STATUS_NEEDS_ARTIST_REPLY, reason=...)`; kept `func.now()` for `last_bot_message_at` (re-added `from sqlalchemy import func`). |
| **app/services/time_window_collection.py** | Replaced direct status assigns with `transition(db, lead, STATUS_COLLECTING_TIME_WINDOWS)` and `transition(db, lead, STATUS_NEEDS_ARTIST_REPLY, reason=...)`. |
| **app/services/calendar_service.py** | Replaced `lead.status = STATUS_COLLECTING_TIME_WINDOWS` with `transition(db, lead, STATUS_COLLECTING_TIME_WINDOWS)`. |
| **tests/test_production_hardening.py** | Added `test_handover_packet_uses_latest_per_key` (alias of `test_handover_packet_answers_use_latest_per_key`) and refactored shared logic into `_assert_handover_packet_latest_per_key(db)`. |

---

## Minimal Diffs (conceptual)

- **state_machine.py**
  - Imports: added `STATUS_COLLECTING_TIME_WINDOWS`, `STATUS_BOOKING_LINK_SENT`, `STATUS_NEEDS_MANUAL_FOLLOW_UP`.
  - `ALLOWED_TRANSITIONS`: QUALIFYING → NEEDS_MANUAL_FOLLOW_UP; AWAITING_DEPOSIT/DEPOSIT_PAID → BOOKING_LINK_SENT; BOOKING_PENDING → COLLECTING_TIME_WINDOWS; COLLECTING_TIME_WINDOWS → NEEDS_ARTIST_REPLY, BOOKING_PENDING; BOOKING_LINK_SENT → BOOKING_PENDING; NEEDS_MANUAL_FOLLOW_UP (terminal); OPTOUT/ABANDONED/STALE → NEW; NEEDS_ARTIST_REPLY → OPTOUT.
  - New function: `advance_step_if_at(db, lead_id, expected_step)` → lock lead, check `current_step == expected_step`, set `current_step += 1`, commit, return `(True, lead)` or `(False, None)`.
- **conversation.py**
  - Import: `from app.services.state_machine import advance_step_if_at, transition` placed **after** all STATUS_* constants.
  - All `lead.status = X; db.commit()` (and related timestamp/reason sets) replaced with `transition(db, lead, X, reason=...)` where the transition is in ALLOWED_TRANSITIONS; after transition, extra fields (e.g. `tour_offer_accepted`, `location_city`) set and committed where needed.
  - Step advance: both sites use `success, lead = advance_step_if_at(db, lead.id, current_step)`; if not success, return `step_already_advanced` without sending next question.
  - Single intentional bypass: `else: lead.status = STATUS_NEW; ...` for unknown status (recovery path).

---

## Policy Decisions

1. **Restart after OPTOUT / ABANDONED / STALE**  
   User can re-engage (e.g. send START when OPTOUT). Allowed transitions: OPTOUT → NEW, ABANDONED → NEW, STALE → NEW. `test_restart_after_optout_policy` and `test_optout_cannot_transition_without_restart_rule` encode this.

2. **Opt-out during handover**  
   STOP/UNSUBSCRIBE must work even in NEEDS_ARTIST_REPLY. Allowed: NEEDS_ARTIST_REPLY → OPTOUT. No special-case bypass.

3. **Unknown status**  
   If `lead.status` is not one of the known branches, we set `lead.status = STATUS_NEW` and restart the flow without going through `transition()`, because that status is not in ALLOWED_TRANSITIONS.

4. **Step advance race**  
   If `advance_step_if_at` returns False (another request already advanced), we return `status: "step_already_advanced"` and do not send the next question, avoiding duplicate messages and double-advance.

---

## Tests

- **test_concurrent_inbound_does_not_double_advance_step** – Two concurrent `handle_inbound_message` for same lead/step; step advances once (advance_step_if_at + lock).
- **test_duplicate_message_id_race_only_one_processes** – Duplicate message_id → one ProcessedMessage (webhook idempotency).
- **test_confirmation_summary_uses_latest_per_key** – `_maybe_send_confirmation_summary` uses latest answer per key (order_by already present).
- **test_complete_qualification_uses_latest_per_key** – `_complete_qualification` uses latest budget (order_by already present).
- **test_handover_packet_answers_use_latest_per_key** / **test_handover_packet_uses_latest_per_key** – `build_handover_packet` uses latest per key (order_by already present).

All 32 tests in `test_production_hardening`, `test_handover_complications`, and `test_parse_repair` pass.
