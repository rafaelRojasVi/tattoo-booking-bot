# Conversation Policy Extraction (Pure Functions)

## What was extracted and why

**1. Keyword / intent policy (opt-out, opt-back-in, human, refund, delete)**

- **Where:** Inline checks in `conversation.py`, `conversation_qualifying.py`, `conversation_booking.py` (e.g. `message_upper in ["STOP", "UNSUBSCRIBE", ...]`).
- **Extraction:** New module `app/services/conversation_policy.py` with pure predicates:
  - `normalize_message(text) -> str` — strip + upper for consistent matching.
  - `is_opt_out_message(text) -> bool` — STOP, UNSUBSCRIBE, OPT OUT, OPTOUT.
  - `is_opt_back_in_message(text) -> bool` — START, RESUME, CONTINUE, YES (OPTOUT restart).
  - `is_human_request_message(text) -> bool` — HUMAN, PERSON, TALK TO SOMEONE, etc.
  - `is_refund_request_message(text) -> bool` — "REFUND" in text.
  - `is_delete_data_request_message(text) -> bool` — DELETE MY DATA, GDPR, etc.
- **Why:** Single place for compliance/policy keywords; easy to test and change; no DB/IO.

**2. Handover hold cooldown**

- **Where:** Inline logic in `conversation_booking._handle_needs_artist_reply`: `last_hold_at is None or (now_utc - last_hold_at) >= timedelta(hours=6)`.
- **Extraction:** `handover_hold_cooldown_elapsed(last_hold_at, now_utc, cooldown_hours) -> bool`.
- **Why:** Pure, testable with fixed datetimes; documents the “≥ cooldown” rule in one place.

## Files touched

| File | Change |
|------|--------|
| `app/services/conversation_policy.py` | **New** — all pure policy/cooldown functions. |
| `app/services/conversation.py` | Use `is_opt_back_in_message(message_text)` for OPTOUT branch. |
| `app/services/conversation_qualifying.py` | Use `is_opt_out_message`, `is_human_request_message`, `is_refund_request_message`, `is_delete_data_request_message`. |
| `app/services/conversation_booking.py` | Use `is_opt_out_message`, `normalize_message` for CONTINUE, `handover_hold_cooldown_elapsed`. |
| `tests/test_conversation_policy.py` | **New** — unit tests for all new functions (fast, deterministic). |

**Total: 5 files** (2 new, 3 modified). No DB models, no state machine behavior change.

## Risks / edge cases

- **Keyword changes:** Adding/removing keywords (e.g. opt-out) is now done in one module; call sites stay the same. No new risk.
- **Cooldown:** Behavior unchanged: `>= cooldown_hours` so exactly 6h ago allows send. Tests lock this.
- **Backward compatibility:** All call sites pass the same inputs (message text or datetimes); behavior is identical.

## Commands run (merge-readiness)

Run these from repo root:

```bash
pytest -q
ruff format .
ruff check .
mypy .
```

### Exact outputs (merge-readiness pass)

| Command | Result |
|--------|--------|
| **pytest -q** | 1024 passed, 2 skipped |
| **ruff format .** | 189 files left unchanged |
| **ruff check .** | All checks passed (after fixing 3× I001 import order in safety.py, state_machine.py, system_event_service.py) |
| **mypy .** | 49 errors in 14 files (exit code 1) — see below |

### Full mypy status (expected known failures)

- **Count:** 49 errors in 14 files (all in tests + a few app modules).
- **Cause:** Known SQLAlchemy DateTime / `func.now()` assignment and operator issues; per-module overrides exist for conversation/state_machine etc. (see `pyproject.toml` and `docs/misc/MYPY_TRIAGE_PLAN.md`).
- **Conversation policy:** `app/services/conversation_policy.py` has **no mypy errors** and is not in the override list; the new module is clean. No new errors were introduced by the conversation_policy extraction.

## How to add new keywords safely

1. **Add the predicate** in `app/services/conversation_policy.py`:
   - Define a `frozenset` or tuple of keywords (e.g. `NEW_KEYWORDS = frozenset({"X", "Y"})`).
   - Add a pure function, e.g. `def is_xyz_message(message_text: str) -> bool: return normalize_message(message_text) in NEW_KEYWORDS`.
2. **Add unit tests** in `tests/test_conversation_policy.py`:
   - Parametrize or single tests for `True` cases (each keyword, plus normalized/whitespace variants).
   - At least one `False` case (unrelated text).
3. **Wire the function** in the relevant handler (conversation.py, conversation_qualifying.py, or conversation_booking.py) and run the full test suite.

## CI and mypy

- **Current behavior:** `.github/workflows/quality.yml` runs `mypy app` with no `continue-on-error`. With 49 existing errors (all in tests/ORM), the mypy step **fails the pipeline** unless the workflow was already set to allow failure elsewhere.
- **Proposal (smallest change):** Add `continue-on-error: true` to the mypy step and a short comment (e.g. “Known SQLAlchemy DateTime / test assignment errors; see docs/misc/MYPY_TRIAGE_PLAN.md”). Alternative: run `mypy app/services/conversation_policy.py` as a “canary” that must pass, and keep full `mypy app` as advisory (e.g. in a separate job with continue-on-error). No CI change was made in this pass; document or adjust as needed for your branch.

## Not done (possible future extractions)

- Tour accept/decline keywords (`YES/Y/ACCEPT` vs `NO/N/DECLINE`) — could be `is_tour_accept_message` / `is_tour_decline_message` in policy.
- Coverup “yes” check (`YES/Y/TRUE/1`) in qualifying — could be `is_coverup_yes(text)`.
- No new framework or class hierarchy; all additions are small pure functions.
