# Production Correctness Sweep — Guards & Reminder Template Fallback

**Date:** 2 February 2026  
**Scope:** `looks_like_wrong_field_single_answer`, bundle guard, restart behavior, reminder 24h template fallback, code quality review

---

## 1) Wrong-Field Guard — False Positive Review

### Verified behavior

| Input | Step | Result | Rationale |
|-------|------|--------|-----------|
| "2 dragons fighting" | idea | **Allowed** | alpha_ratio ≈ 0.82 (> 0.3); budget parses but high alpha |
| "10cm above wrist" | placement | **Allowed** | alpha_ratio ≈ 0.67 (> 0.5); dimension pattern present but sufficient alphabetic content |
| "500" | idea | **Reprompt** | budget-only, alpha_ratio 0 |
| "10x15cm" | idea | **Reprompt** | dimensions-only, alpha_ratio < 0.5 |

### Tests added

- `test_idea_step_allows_numbers_in_description` — unit: heuristic returns False
- `test_placement_step_allows_measurement_phrases` — unit: heuristic returns False
- `test_idea_step_allows_numbers_in_description_integration` — full flow: "2 dragons fighting" advances
- `test_placement_step_allows_measurement_phrases_integration` — full flow: "10cm above wrist" advances

---

## 2) Ordering in conversation.py

### Verified

- **Wrong-field guard** (L704–729) runs **before** bundle guard (L731–768)
- **Neither advances step**: both return early with `current_step` in payload (unchanged)
- **Exactly one outbound per inbound**: each guard sends one message via `send_whatsapp_message` and returns immediately; no second send

### Call flow (qualifying path)

1. Wrong-field check → if True: send reprompt, return (`wrong_field_reprompt`)
2. Bundle guard → if True and not valid single answer: send reprompt, return (`one_at_a_time_reprompt`)
3. Handover check → if True: transition, send handover, return
4. Parse, save, advance (normal path)

---

## 3) Restart Behavior

### Verified

- On ABANDONED/STALE → NEW restart, `last_client_message_at = func.now()` is set (conversation.py L554)
- 24h window opens for the next message (window = last_client_message_at + 24h)
- Test `test_restart_then_new_answers_override_old_answers_in_summary` now asserts:
  - After "sleeve tattoo flowers", `lead.current_step == 1` (processed normally, not template-only)
  - Exactly one bot reply for that message

---

## 4) Reminder Template Fallback

### Patch site

- **Correct**: `app.services.template_registry.get_all_required_templates` — patched where defined; `whatsapp_window` imports from `template_registry`, so the patch applies to the call inside `send_with_window_check` (L125–127)

### Status contract

| Reminder | First call | Second call | Meaning |
|----------|------------|-------------|---------|
| Qualifying 2 | `sent` | `duplicate` | Idempotency via `check_and_record_processed_event` |
| Booking 24h | `sent` | `already_sent` or `duplicate` | `already_sent` = lead field set; `duplicate` = processed event. Both mean "no second send". |

**Recommendation:** Document in `app/services/reminders.py` module docstring that `already_sent` and `duplicate` are equivalent for "idempotent no-resend" contract.

---

## 5) Code Quality / Architecture Review

### Duplication & smells

- **Repeated setup mocks** in `test_bundle_guard.py`: `patch("app.services.conversation.send_whatsapp_message")`, `patch("app.services.tour_service.is_city_on_tour")`, `patch("app.services.handover_service.should_handover")` appear in many integration tests. Consider a `@pytest.fixture` or `_make_qualifying_patches()` context manager.
- **Repeated transcript logic**: `format_transcript(user_messages, bot_messages, max_line=None)` + assert with `transcript` in failure message — could be a helper `assert_one_reply_and_advance(db, lead, msg, expected_step, ...)`.
- **Both guards use same reprompt**: `ONE_AT_A_TIME_REPROMPT` for wrong-field and bundle — acceptable; same user-facing copy.

### Refactor suggestions (only if clearly reduces complexity)

- **GuardRail interface**: Not recommended. The two guards have different triggers (wrong-field vs multi-answer); a single interface would add indirection without real gain.
- **QuestionAnswerValidator**: Could centralize `_is_valid_single_answer_for_current_question` + `looks_like_wrong_field_single_answer` in a small module, but current nesting in conversation is readable. **Leave as-is** unless more guards are added.
- **InboundMessagePolicy object**: Would encapsulate guards + handover + parse order. Overkill for current size. **Leave as-is**.

### Import hygiene & formatting

- `tests/test_phase1_reminders.py` L12: `STATUS_BOOKING_LINK_SENT` imported but unused — **remove**.
- No duplicate imports or accidental concatenations found in modified files.

### Guard isolation & test levels

- **Pure unit tests** in `test_bundle_guard.py` for `looks_like_multi_answer_bundle` and `looks_like_wrong_field_single_answer` — correct level.
- **Integration tests** exercise full `handle_inbound_message` with mocks for external services (WhatsApp, tour, handover) — appropriate; not over-mocking internals.
- **Recommendation**: Keep heuristic logic in `bundle_guard.py` and avoid testing implementation details of `conversation.py` (e.g. internal function names).

### Performance / DB efficiency

- **Commits**: Both guards call `db.commit()` before return — necessary to persist `last_bot_message_at`.
- **Refreshes**: Tests use `db.refresh(lead)` frequently; production path does not add extra refreshes.
- **Row locking**: No change; `advance_step_if_at` and state transitions use existing locking.
- **Optimisation opportunity**: If reminder jobs run at high frequency, `check_and_record_processed_event` could be checked before any other logic to short-circuit early (currently idempotency is after timing checks, which is fine for cron-style jobs).

### Return payload / status standardisation

- Status strings: `wrong_field_reprompt`, `one_at_a_time_reprompt`, `duplicate`, `already_sent` — used in tests and potentially in logging.
- **Recommendation**: Add a short enum or constants module for status strings used in contract/logging (`ReminderStatus`, `RepromptStatus`) for traceability. No behavior change required now.

---

## 6) Remaining Edge Cases (Ranked by Impact)

| Rank | Edge case | Impact | Mitigation |
|------|-----------|--------|------------|
| 1 | Idea step: "£50" or "50" (ambiguous — budget vs quantity) | Medium | Current heuristic: "50" at idea has alpha_ratio 0, budget parses → reprompt. "£50" same. Acceptable; user can rephrase. |
| 2 | Placement: "upper arm 10x15" (placement + dimensions) | Low | Would trigger bundle guard (2 signals) if not valid single answer for placement. Placement has no `_is_valid_single_answer`; would reprompt. Consider adding placement validation if this becomes common. |
| 3 | Qualifying reminder 1 (12h): no template when window closed | Medium | Reminder 1 uses `template_name=None`; if window closed, message is not sent. 12h reminder is usually within window; document that reminder 1 has no template fallback. |
| 4 | Restart from STALE (pending approval): same behavior as ABANDONED | Low | Both transition to NEW and reset step. Verified; no change needed. |

---

## 7) Ship-Ready Cleanup (Exact Hints)

| File | Line | Action |
|------|------|--------|
| `tests/test_phase1_reminders.py` | 12 | Remove unused import `STATUS_BOOKING_LINK_SENT` |

---

## 8) Nice-to-Have After Go-Live

1. **Fixture for qualifying patches** in `test_bundle_guard.py`: reduce boilerplate in integration tests.
2. **Module docstring** in `app/services/reminders.py`: document `already_sent` vs `duplicate` as equivalent for idempotency.
3. **Status constants**: centralise `wrong_field_reprompt`, `one_at_a_time_reprompt`, `duplicate`, `already_sent` for contract traceability.
4. **Qualifying reminder 1 template**: add optional template fallback when window closed (e.g. `consultation_reminder_1`) for edge cases where 12h reminder fires but window is already closed.
