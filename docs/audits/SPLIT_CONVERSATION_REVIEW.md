# Split Conversation – Code Quality & Reproducibility Review

**Branch:** `refactor/split-conversation`  
**Scope:** `conversation.py` split into orchestrator + `conversation_qualifying.py` + `conversation_booking.py` + `app/constants/statuses.py`

---

## 1) Architecture / structure

**Good**
- Clear split: orchestrator (`conversation.py`) dispatches by `lead.status`; qualifying vs booking live in separate modules.
- Single source of truth for statuses (`app/constants/statuses.py`) avoids circular imports; `state_machine` and conversation import from there.
- Backward compatibility: `conversation` re-exports `STATUS_*` and handlers so existing callers and tests need not change.
- Late-binding `_get_send_whatsapp()` in qualifying and booking keeps tests’ `patch("app.services.conversation.send_whatsapp_message")` effective.

**Risky / to watch**
- **Cross-module imports:** `conversation_booking` imports `_handle_new_lead` and `_handle_opt_out` from `conversation_qualifying`. If qualifying ever imports from booking, a cycle could appear. Today there is no cycle.
- **Orchestrator “else” branch:** `handle_inbound_message`’s final `else` sets `lead.status = STATUS_NEW` and restarts (bypassing `state_machine.transition`). That’s intentional recovery for unknown statuses but is a single place where status is written without going through the state machine; keep it documented and covered by tests.

**Could be cleaner**
- **Naming:** `_handle_*` is clear. Consider documenting in each module’s docstring which statuses it owns (e.g. qualifying: NEW, QUALIFYING, opt-out; booking: BOOKING_PENDING, TOUR_CONVERSION_OFFERED, NEEDS_ARTIST_REPLY).
- **`__all__`:** `conversation.__all__` omits `_handle_new_lead` and `_handle_opt_out` (they are still importable). Adding them would make the public surface explicit; optional.

---

## 2) Reproducibility / ops

**Determinism & idempotency**
- Webhook idempotency is enforced in `webhooks.py` via `ProcessedMessage(provider, message_id)`; duplicate message_id is detected and returns “duplicate” without calling `handle_inbound_message` again. Unchanged by the split.
- State transitions go through `state_machine.transition` (SELECT FOR UPDATE, validation). Qualifying and booking call `transition()`; no direct status writes except the orchestrator’s unknown-status reset.

**Logging / trace IDs**
- `webhooks.whatsapp_inbound` uses `get_correlation_id(request)` and logs it. Conversation handlers do not take a correlation_id; correlation remains at the webhook layer. Acceptable; no change suggested for this review.

**Config / env**
- Feature flags and config are read via `settings` (e.g. panic mode, 24h window, handover cooldown). No env handling inside the split modules that would hurt reproducibility.

**Timezones**
- `conversation_booking` uses `datetime.now(UTC)` and `dt_replace_utc(lead.handover_last_hold_reply_at)` for cooldown. Consistent UTC usage.

**Rate limits / retry**
- Handover holding reply is rate-limited by `HANDOVER_HOLD_REPLY_COOLDOWN_HOURS` (6h) in booking; logic is in one place. Outbox retry and webhook rate limiting are outside the split; unchanged.

**Verdict:** Reproducibility and ops behavior are intact; no small diffs required here.

---

## 3) Functionality correctness

**Status transitions**
- Orchestrator branches by `lead.status` and delegates to the right handler. ORDER of branches matters: NEW → QUALIFYING → … → OPTOUT → ABANDONED/STALE → else. No duplicate branches; BOOKING_LINK_SENT legacy branch correctly maps to BOOKING_PENDING behavior.

**Handler dispatch**
- NEW → `_handle_new_lead` (qualifying).
- QUALIFYING → `_handle_qualifying_lead` (qualifying).
- BOOKING_PENDING → `_handle_booking_pending` (booking).
- TOUR_CONVERSION_OFFERED → `_handle_tour_conversion_offered` (booking).
- NEEDS_ARTIST_REPLY → `_handle_needs_artist_reply` (booking); opt-out and CONTINUE handled inside that handler.

**Edge cases**
- **Handover:** Qualifying calls `should_handover`; on true, `transition(..., STATUS_NEEDS_ARTIST_REPLY, reason=...)`, notify artist, send handover message. Booking: STOP/UNSUBSCRIBE → `_handle_opt_out`; CONTINUE → resume qualification; else holding message with 6h cooldown. Behavior matches intent.
- **Opt-out / delete / refund:** Handled inside `_handle_qualifying_lead` (HUMAN, REFUND, DELETE MY DATA) and in orchestrator for OPTOUT (START/RESUME/CONTINUE/YES → NEW then _handle_new_lead). NEEDS_ARTIST_REPLY opt-out delegated to `_handle_opt_out` from booking. Correct.
- **Message sending:** All sends go through `send_whatsapp_message` (or window/template helpers). Patched in tests at `app.services.conversation.send_whatsapp_message`; late-binding in submodules preserves that.

**Cooldowns**
- Handover holding reply: only in `_handle_needs_artist_reply`; `handover_last_hold_reply_at` updated when a hold message is sent; next send only if ≥ 6h. Already covered by `test_handover_holding_reply_rate_limited` and `test_handover_holding_reply_sent_again_after_cooldown`.

**Verdict:** No functional bugs found in the split; behavior matches pre-split design.

---

## 4) Test suite improvements

**Proposed high-value tests (3–6)**

1. **Dispatch by status – PENDING_APPROVAL:** Lead in PENDING_APPROVAL; `handle_inbound_message` returns `status == "pending_approval"` and `lead.status` unchanged. Locks orchestrator branch.
2. **Dispatch by status – BOOKED:** Lead in BOOKED; `handle_inbound_message` returns `status == "booked"` and does not call `send_whatsapp_message` (patch, assert 0 calls). Locks “already booked” branch.
3. **Dispatch by status – QUALIFYING:** Lead QUALIFYING step 0, message “A dragon”; result `question_sent`, step 1. (Already covered in `test_conversation.py`; could add a short “dispatch” test that only asserts result status and step.)
4. **Send_whatsapp patch in booking:** Lead NEEDS_ARTIST_REPLY, message “hello”; patch `conversation.send_whatsapp_message`, assert exactly one call and message contains “paused” or “artist”. (Already in `test_handover_complications`.)
5. **Handover cooldown:** Second message within 6h does not send a second holding message. (Already in `test_handover_holding_reply_rate_limited`.)
6. **Idempotency at webhook:** Same message_id twice → only one “conversation” processing. (Already in `test_whatsapp_retry_storm_same_message_id_20_concurrent_only_one_advances`.)

**Implemented in this pass**
- **test_conversation_dispatch_pending_approval_returns_ack_only** – Locks orchestrator: PENDING_APPROVAL returns ack and does not change status (behavior contract).
- **test_conversation_dispatch_booked_returns_booked_no_send** – Locks BOOKED branch and confirms no send when already booked (behavior contract).
- **test_conversation_split_regressions.py** (new file) – Direct split-regression tests:
  - **test_split_late_binding_respects_conversation_send_whatsapp_patch** – Patches `conversation.send_whatsapp_message` and asserts `conversation_qualifying._get_send_whatsapp()` and `conversation_booking._get_send_whatsapp()` both return the patched object. Locks the #1 split-specific invariant (patchability).
  - **test_handle_inbound_message_dispatches_by_status_to_qualifying_and_booking** – QUALIFYING lead and BOOKING_PENDING lead; mocks `_handle_qualifying_lead` and `_handle_booking_pending` on the conversation module; asserts each handler is called exactly once. Locks dispatch routing across qualifying vs booking.

---

## 5) Type checking (mypy)

- Remaining ~47 mypy errors are almost all SQLAlchemy `DateTime` / `func.now()` assignment and comparisons. Existing approach: `[[tool.mypy.overrides]]` with `module = [..., app.services.conversation, app.services.conversation_booking, app.services.conversation_qualifying, ...]` and `disable_error_code = ["assignment"]`.

**Recommendation (smallest, safe)**
- Keep the current per-module override for `assignment` on the conversation modules, state_machine, and other files that touch Lead/ORM datetime columns. Do not broaden to entire `app` to avoid losing signal elsewhere.
- Optional: add a one-line comment in `docs/misc/MYPY_TRIAGE_PLAN.md` or `docs/audits/SPLIT_CONVERSATION_SUMMARY.md` that the split conversation modules are included in the SQLAlchemy datetime override list and why (plugin limitation with `Mapped[DateTime|None]` and `func.now()`).
- No change to `Mapped`/`mapped_column` types in models for this review; that would be a larger, cross-file change.

---

## 6) Files to touch (before proposing edits)

- `docs/audits/SPLIT_CONVERSATION_REVIEW.md` (this report) – **created**
- `tests/test_conversation.py` – **add 2 tests** (dispatch PENDING_APPROVAL, dispatch BOOKED with send_whatsapp patch)
- `tests/test_conversation_split_regressions.py` – **new file** with 2 split-regression tests (late-binding, dispatch routing)
- No other files in this pass (no broad refactors).

---

## Summary

- **Architecture:** Split is clear and safe; no import cycles. Optional: document status ownership per module and add `_handle_new_lead` / `_handle_opt_out` to `__all__`.
- **Reproducibility / ops:** Idempotency, logging, config, timezones, and rate limits are consistent; no changes required.
- **Functionality:** Dispatch, transitions, handover, opt-out, and cooldowns behave correctly.
- **Tests:** Two small tests added to lock orchestrator branches (PENDING_APPROVAL and BOOKED).
- **Types:** Keep existing mypy overrides for conversation modules; optionally document in triage doc.

**Stop condition:** Fewer than three separate issues requiring broad refactors; only small, safe diffs applied.

---

## Over-specification note

The two behavior-contract tests in `test_conversation.py` lock **policy** (PENDING_APPROVAL doesn’t mutate status; BOOKED doesn’t send). If you later add e.g. a polite autoresponder for BOOKED, `test_conversation_dispatch_booked_returns_booked_no_send` would fail. That may be desired. To soften: you could relax the BOOKED test to only assert `result["status"] == "booked"` and no status mutation, and drop the `send_whatsapp_message.assert_not_called()` requirement.

---

## Run results (after implementing tests)

| Command            | Result |
|--------------------|--------|
| `pytest -q`        | 987 passed, 2 skipped |
| `ruff format .`    | 1 file reformatted, 186 unchanged |
| `ruff check .`     | All checks passed (import order in new test file fixed with `--fix`) |
| `mypy .`           | 49 errors in 14 files (unchanged: SQLAlchemy DateTime / test annotations; new split-regression tests introduce no mypy errors) |

---

## Final readiness review (human-quality)

**Quality gate (Step 0)** — exact outputs:

| Command         | Result |
|-----------------|--------|
| `pytest -q`     | 987 passed, 2 skipped |
| `ruff format .` | 187 files left unchanged |
| `ruff check .`  | All checks passed |
| `mypy .`        | 49 errors in 14 files (exit code 1) |

**Step 1 — Mypy interpretation**

- **(a) Known false positives (no bug risk):** The 49 errors are almost entirely SQLAlchemy `DateTime` / `func.now()` assignment and comparisons, and `DateTime` missing attributes (`tzinfo`, `replace`) or operator overloads in tests. These are covered by the existing `[[tool.mypy.overrides]]` for `app.services.conversation`, `conversation_booking`, `conversation_qualifying`, `state_machine`, and several test files. No ORM model refactor needed.
- **(b) Possible real issues (low risk):** `test_production_last_mile.py:239` (Select type mix-up) and `test_adversarial_break_extended.py` (fixture typing) are test-only; worth a follow-up but not blocking the split.

**Step 2 — Human code quality**

- **Architecture:** Boundaries are clear; no import cycles; late-binding for `send_whatsapp_message` is consistent; orchestrator’s single bypass (unknown status → NEW) is documented in code.
- **Correctness:** Dispatch order, handover/opt-out/refund/delete, cooldown (6h UTC), and idempotency patterns match design.
- **Reproducibility/ops:** UTC usage, correlation at webhook layer, config/feature flags, rate limits — no issues.
- **Tests:** Behavior-contract tests (PENDING_APPROVAL, BOOKED) and split-regression tests (late-binding, dispatch) lock the right invariants; no flaky patterns observed. Unknown-status → NEW path is not explicitly tested (acceptable; state_machine and recovery are covered elsewhere).

---

### A) Report summary

**✅ What’s strong**

- Single entrypoint `handle_inbound_message` with clear status-based dispatch; qualifying vs booking modules have focused responsibility.
- Single source of truth for statuses (`app/constants/statuses.py`); state machine enforces transitions with SELECT FOR UPDATE.
- Late-binding `_get_send_whatsapp()` keeps tests patchable without touching submodule imports.
- Docs and tests added without app behavior changes; quality gate (pytest, ruff) is green.

**⚠️ Risks / footguns (ranked)**

1. **Orchestrator `else` branch** — Unknown status is reset to NEW without going through `state_machine.transition`. Intentional recovery; if someone adds a new status and forgets to add a branch, leads will reset to NEW. Mitigation: comment in code; state machine tests cover allowed transitions.
2. **Cross-module dependency** — `conversation_booking` imports `_handle_new_lead` and `_handle_opt_out` from `conversation_qualifying`. Any future import from booking → qualifying would create a cycle. Mitigation: keep qualifying free of booking imports.
3. **BOOKED test locks “no send”** — Adding a BOOKED autoresponder would require relaxing `test_conversation_dispatch_booked_returns_booked_no_send` (see over-specification note above).

**🔧 Top 3 small improvements**

1. **Explicit re-exports** — Add `_handle_new_lead` to `conversation.__all__` (the orchestrator uses it; `_handle_opt_out` is only used by booking and imported from qualifying there, so not re-exported by conversation). **Done.**
2. **Mypy triage doc** — In `docs/misc/MYPY_TRIAGE_PLAN.md`, note under the SQLAlchemy DateTime bucket that the conversation split modules are explicitly in the per-module `disable_error_code = ["assignment"]` override list (plugin limitation). **Done.**
3. **Optional: test unknown-status recovery** — Add a small test that an unknown/invalid status leads to NEW and a question_sent-style response. Low priority; only if you want the recovery path explicitly locked.
