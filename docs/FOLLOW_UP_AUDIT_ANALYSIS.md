# Follow-Up Audit — Analysis Only (No Code Changes)

**Date:** 2 February 2026  
**Scope:** Wrong-field guard, reminder idempotency, restart invariants, status consistency, ship-ready hygiene

---

## A) Wrong-Field Guard — Exact Heuristic Rules & Borderline Examples

### Exact heuristic rules (`looks_like_wrong_field_single_answer`)

1. **Scope**: Only runs for `current_question_key in ("idea", "placement")`; returns False for all other steps.
2. **Budget-only rule**: Return True if `parse_budget_from_text(text) is not None` AND `alpha_ratio < 0.3`.
   - `alpha_ratio` = `alpha_chars / total_non_space` (alpha_chars = letters; total_non_space = non-whitespace chars).
3. **Dimensions-only rule**: Return True if `dim_parsed` AND `alpha_ratio < 0.5`.
   - `dim_parsed` = `parse_dimensions(text) is not None` OR regex match for `\d+\s*[x×]\s*\d+` OR `\bcm\b` OR `\binch(es)?\b`.
4. **Otherwise**: Return False (allow).

### 10 borderline examples

| # | Step | Input | Expected | Current | Why |
|---|------|-------|----------|---------|-----|
| 1 | idea | "£500 dragon sleeve" | Allow | PASS | alpha_ratio ≈ 0.73 > 0.3; budget parses but high alphabetic content. |
| 2 | idea | "forearm, about 10cm above wrist" | Allow* | PASS | alpha_ratio ≈ 0.83 > 0.5; dim pattern (cm) present but enough text. *Semantically placement, not idea—guard does not detect wrong semantic field. |
| 3 | idea | "wrist 10x15" | Allow | PASS | alpha_ratio ≈ 0.56 > 0.5; dimension pattern present, threshold not met. |
| 4 | idea | "500 for a dragon" | Allow | PASS | alpha_ratio ≈ 0.77 > 0.3; budget parses but high alpha. |
| 5 | idea | "10x15cm dragon" | Allow | PASS | alpha_ratio ≈ 0.56 > 0.5; dimensions + word, above threshold. |
| 6 | placement | "£500 dragon sleeve" | Allow | PASS | Same logic; alpha_ratio high. |
| 7 | placement | "forearm, about 10cm above wrist" | Allow | PASS | Valid placement; alpha_ratio high. |
| 8 | placement | "wrist 10x15" | Allow | PASS | Placement + dimensions; alpha_ratio ≈ 0.56 > 0.5. |
| 9 | placement | "500 for a dragon" | Allow | PASS | Wrong semantic field (idea at placement) but guard only catches budget/dimensions-only; alpha high. |
| 10 | placement | "10x15cm dragon" | Allow | PASS | Dimensions + word; alpha_ratio above 0.5. |

**Summary**: All 10 borderline cases are correctly allowed. The heuristic avoids false positives on mixed text+numbers by requiring low alpha_ratio for reprompt.

---

## B) Reminder Idempotency & Send Semantics

### Processed-event marking: before or after send?

**Finding: Marking happens BEFORE send** (not strict).

- `check_and_record_processed_event` (safety.py L169–187) is marked DEPRECATED: *"records BEFORE processing, which can cause dropped events"*.
- Flow: (1) Check duplicate → (2) If not duplicate, **record processed event** → (3) Call `send_with_window_check` → (4) Update lead timestamp.
- If step 3 raises, the processed event is already recorded. A retry would see "duplicate" and not send again → **dropped reminder**.

### Paths where failure could mark as "sent"

| Scenario | Processed event | Lead timestamp | Effect |
|----------|-----------------|----------------|--------|
| Send raises exception | Recorded before send | Not updated | Reminder lost; retry returns "duplicate". |
| Send succeeds | Recorded before send | Updated | Correct. |
| Template not configured (window closed) | Recorded before send | Not updated (code path returns before timestamp update) | Actually: we still reach L157–161 after send_with_window_check returns. `send_with_window_check` returns a dict (no exception) when template not configured—it does not raise. So we would update lead timestamp and return "sent" even though no message was sent. **P1 risk.** |
| dry_run=True | Recorded before send | Updated | Intentional; no actual send. |

### Template-not-configured path (qualifying/booking reminder)

- `send_with_window_check` returns `{"status": "window_closed_template_not_configured", ...}` without raising.
- Reminders do not check `result["status"]`; they proceed to update lead timestamp and return "sent".
- **Consequence**: Lead is marked as sent, but no message reached the user. Idempotency prevents retry.

### At most one outbound per invocation

**Confirmed**: Each reminder function has exactly one `send_with_window_check` call. No loops. At most one outbound per invocation.

---

## C) Restart Invariants

### Statuses that can restart to NEW (per ALLOWED_TRANSITIONS)

| From status | To | Allowed |
|-------------|-----|---------|
| STATUS_ABANDONED | STATUS_NEW | Yes |
| STATUS_STALE | STATUS_NEW | Yes |
| STATUS_OPTOUT | STATUS_NEW | Yes |

### last_client_message_at & 24h-window behaviour

| Restart path | last_client_message_at updated? | 24h window for next message |
|--------------|--------------------------------|-----------------------------|
| ABANDONED → NEW | **Yes** (conversation.py L554) | Opens |
| STALE → NEW | **Yes** (same branch) | Opens |
| OPTOUT → NEW | **No** (conversation.py L534–540) | May stay closed |
| Unknown status → NEW (else L561) | **No** | May stay closed |

### Inconsistent restart path

- **OPTOUT restart**: On START/RESUME/CONTINUE/YES, we transition to NEW and call `_handle_new_lead` but do **not** set `last_client_message_at`. The window is still based on the last user message before opt-out, which can be >24h ago. The next qualification message may require a template.
- **Unknown-status restart**: Same: no `last_client_message_at` update; recovery path may hit closed window.

---

## D) Status/Result-String Consistency

### Reminder return statuses

| Function | Statuses |
|----------|----------|
| check_and_send_qualifying_reminder | `skipped`, `already_sent`, `not_due`, `duplicate`, `sent` |
| check_and_mark_abandoned | `skipped`, `already_abandoned`, `not_due`, `abandoned` |
| check_and_mark_stale | `skipped`, `already_stale`, `not_due`, `stale` |
| check_and_send_booking_reminder | `skipped`, `already_sent`, `not_due`, `duplicate`, `sent` |
| check_and_mark_deposit_expired | `skipped`, `not_due`, `expired` |
| check_and_mark_booking_pending_stale | `skipped`, `already_needs_follow_up`, `not_due`, `needs_follow_up` |

### Conversation return statuses (subset)

`panic_mode`, `pending_approval`, `awaiting_deposit`, `deposit_paid`, `slot_unavailable`, `slot_selected`, `repair_needed`, `booking_pending`, `tour_accepted`, `waitlisted`, `tour_offer_pending`, `booked`, `resumed`, `artist_reply`, `manual_followup`, `rejected`, `opted_out`, `question_sent`, `error`, `window_closed_template_sent`, `attachment_ack_reprompt`, `wrong_field_reprompt`, `one_at_a_time_reprompt`, `handover`, `step_already_advanced`, `confirmation_sent`, `artist_handover`, `handover_coverup`, `needs_follow_up_budget`, `tour_conversion_offered`, `completed`.

### Recommended vocabulary (contract traceability)

- **Idempotent no-action**: Use `skipped`, `duplicate`, or `already_sent` consistently. Prefer one canonical term per semantic (e.g. `idempotent_skip` with `reason`).
- **Timing**: Use `not_due` for "not yet" and `already_*` for "already done".
- **Reprompts**: Use `*_reprompt` suffix: `wrong_field_reprompt`, `one_at_a_time_reprompt`, `attachment_ack_reprompt`.
- **Success**: Use `sent` for reminders; `question_sent`, `completed` for conversation.
- Document in a single reference (e.g. `docs/STATUS_STRINGS.md`) for contract and log traceability.

---

## E) Ship-Ready Hygiene

### Import/formatting/style (last diffs)

| File | Line | Issue |
|------|------|-------|
| None found | — | No duplicate imports, concatenated imports, or missing newlines in recently modified files. |

### Doc updates for Schedule C / contract consistency

1. **Schedule C**: Add `PRODUCTION_CORRECTNESS_SWEEP.md` and `FOLLOW_UP_AUDIT_ANALYSIS.md` to the docs list if they are contract-relevant.
2. **Schedule C**: Consider a note on reminder idempotency: processed-event recorded before send; template-not-configured path can return "sent" without actual send.
3. **Contract**: If restart semantics are specified, document that OPTOUT restart does not update `last_client_message_at` (24h window may remain closed).
4. **Test count**: Schedule C cites "845 collected, 840 passed". Re-verify after latest changes (e.g. 873 collected, 868 passed).

---

## Findings by Risk

### P0 (blocker)

- None identified.

### P1 (high)

1. **Template-not-configured path**: Reminders can return `status: "sent"` and update lead timestamp when `send_with_window_check` returns `window_closed_template_not_configured` without raising. No message is sent. Mitigation: Check `result.get("status")` before updating lead and returning "sent"; treat `window_closed_*` as failure.
2. **Processed-event before send**: Reminders use `check_and_record_processed_event` which records before send. A send failure can lead to a dropped reminder with no retry. Mitigation: Refactor to `check_processed_event` → send → `record_processed_event` on success.
3. **OPTOUT restart**: `last_client_message_at` not updated; next message may need a template. Mitigation: Set `lead.last_client_message_at = func.now()` when transitioning OPTOUT → NEW on START/RESUME/etc.

### P2 (medium)

1. **Unknown-status restart**: Same `last_client_message_at` gap as OPTOUT.
2. **Status string consistency**: Multiple terms for similar semantics; recommend documenting a standard vocabulary.

---

## Go-Live Confidence Checklist

- [ ] Fix template-not-configured handling in reminders (check result status before marking sent).
- [ ] Consider refactoring reminder idempotency to record-after-send.
- [ ] Fix OPTOUT restart to update `last_client_message_at`.
- [ ] Update Schedule C test counts and add new docs if needed.
- [ ] Document status strings for contract traceability (optional pre–go-live).
- [ ] Run full test suite and verify no regressions.
- [ ] Verify WhatsApp template configuration (reminder_booking, consultation_reminder_2_final) for production.
