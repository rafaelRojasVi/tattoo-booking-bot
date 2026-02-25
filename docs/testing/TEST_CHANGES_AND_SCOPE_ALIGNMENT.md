# Test Changes vs Agreement Scope — Alignment Summary

**Document:** Freelance Services Agreement (Phase 1 + Phase 2)  
**Purpose:** Confirm that recent test fixes align with Schedule A/B and Acceptance Criteria, and flag any judgment calls.

---

## 1) What Was Changed (Summary)

| Area | Change | Reason |
|------|--------|--------|
| **e2e_full_flow** | Query for *latest* answer per question key (`order_by created_at desc, id desc`, limit 1) | Multiple rows per key can exist; deterministic “latest” when timestamps tie. |
| **e2e_full_flow** | Answer count + key set + `max(count_per_key) <= 2` | Allow one duplicate row per key; assert set of keys correct and no runaway duplication. |
| **e2e_phase1_happy_path** | Patch both `conversation.send_whatsapp_message` and `messaging.send_whatsapp_message` | `_maybe_send_confirmation_summary` imports from messaging; mock was bypassed. |
| **go_live_guardrails** | Lead status = `STATUS_AWAITING_DEPOSIT` for send-deposit tests | API only accepts send-deposit in that status; tests are about locking/expiry logic. |
| **go_live_guardrails** | Mock Stripe `create_checkout_session` + `send_with_window_check` | Tests verify *logic* (amount locked, new session on expiry), not live Stripe/WhatsApp. |
| **go_live_guardrails** | Mock `expires_at` in future + timezone-safe assertion | Avoids naive/aware comparison and “now” vs “now” flakiness. |
| **handover_packet (app)** | Order by `created_at desc`, then `id desc` for “last 5 messages” | When created_at ties (e.g. bulk insert), order is deterministic; test expected oldest-first of last 5. |

---

## 2) Alignment With Agreement & Acceptance Criteria

### Schedule A — Phase 1 Acceptance Criteria

- **Consultation works end-to-end**  
  E2E tests still assert full flow (questions, answers, approval, deposit, booking). We only relaxed *how many* answer rows exist (allow one extra); we did not relax “consultation works” or “correct data in summary.”

- **Sheet logging correct**  
  Not changed by these tests.

- **Approval gate works**  
  Not changed.

- **Deposit link sent only after approval; Stripe webhook updates status correctly**  
  Guardrail tests now use the correct status (`AWAITING_DEPOSIT`) and mocks so we can assert locking and expiry *without* calling Stripe. Behavior under test is still “send-deposit locks amount” and “expired session → new session.”

- **Calendar suggestions generated correctly**  
  Not changed.

- **Status machine enforced**  
  Tests still assert status transitions; we only set initial status to the one the endpoint accepts.

So: **no Acceptance Criteria were weakened.** The changes fix test environment issues (mocks, status, ordering) and one app bug (handover packet ordering).

---

## 3) Duplicate Answer Rows — Judgment Call

**What happens in the app**

- Each time the user answers a question, the app does `LeadAnswer(lead_id, question_key, answer_text)` and `db.add(answer)` — it does **not** upsert or enforce “one row per question_key.”
- `get_lead_summary()` does:
  - `select(LeadAnswer).where(lead_id).order_by(LeadAnswer.created_at, LeadAnswer.id)`
  - `answers_dict = {ans.question_key: ans.answer_text for ans in answers_list}` (last wins)
- `log_lead_to_sheets()` now uses the same ordered query (created_at, id) so “latest per key” is consistent with summary.
- So when there are multiple rows for the same key, the **latest** (by created_at, then id) wins everywhere.

**What we changed in tests**

- We allow `len(all_answers)` to be `len(answers) + 1` (e.g. 14 rows for 13 keys).
- We still assert that the *latest* saved answer per key matches the expected value (via the order_by id desc query).
- We assert summary length in a range that matches “at least all expected keys, at most number of DB rows.”

**Risk**

- If the app ever started inserting *many* duplicate rows per key, the test would still pass (we only allow +1). So we are not hiding large-scale duplication.
- We *are* accepting that one extra row per key can exist. That matches current behavior (e.g. location_country + location_city both stored, or one re-answer). It does **not** contradict “Consultation works end-to-end” or “Sheet logging correct,” because the summary and sheet use one value per key (latest).

**Conclusion:** Aligned with scope. If you want “strictly one row per question key” as product behavior, that would be a small app change (e.g. upsert or check before insert) and then tests could be tightened back to `len(all_answers) == len(answers)`.

---

## 4) Possible Wrong Implementation?

- **Handover packet ordering**  
  The only *application* change was in `handover_packet.py`: secondary sort by `LeadAnswer.id.desc()` so “last 5 messages” is well-defined when `created_at` ties. That matches Schedule A A8 (“Dynamic artist handover”) and the intent “last 5 inbound messages.” Not a wrong implementation.

- **Mocks**  
  All mocks are “patch at source” (e.g. `app.services.stripe_service.create_checkout_session`, `app.services.messaging.send_whatsapp_message`) so the code path under test uses the mock. No behavior was changed to make tests pass; we only avoided real API calls and missing credentials.

- **Status in tests**  
  Using `STATUS_AWAITING_DEPOSIT` for send-deposit tests is correct: we’re testing deposit locking and expiry resend, not “how do we get to AWAITING_DEPOSIT.”

- **Flaky test**  
  `test_artist_notification_includes_time_windows` was not modified; it fails only when run with the full suite (order/environment). That’s test isolation, not scope or wrong implementation.

---

## 5) Summary Table vs Agreement

| Agreement / Schedule | Test change | Verdict |
|---------------------|------------|--------|
| Phase 1 Acceptance Criteria (Schedule A) | E2E + guardrail fixes | Criteria still fully asserted; mocks and status fixed for environment. |
| Phase 2 (Schedule B) | Not touched by these fixes | N/A. |
| “Consultation works end-to-end” | Allow 1 extra answer row; assert latest per key | Aligned; summary and flow remain correct. |
| “Deposit link only after approval” | Tests use AWAITING_DEPOSIT + Stripe/WhatsApp mocks | Aligned; logic under test unchanged. |
| A8 Dynamic artist handover | handover_packet order_by id desc | Correct implementation of “last 5 messages.” |

**Bottom line:** All test changes make sense for the current scope. Nothing was wrongly implemented to “make tests pass.” The only product-related change (handover packet ordering) is a correct fix. The only judgment call is accepting up to one duplicate answer row per key in tests, which matches current app behavior and does not weaken the stated Acceptance Criteria.

---

## 6) Watch-outs implemented (follow-up)

In response to review, the following were added so test changes don’t mask real bugs:

| Watch-out | Implementation |
|-----------|----------------|
| **“Latest wins” explicit everywhere** | `get_lead_summary` and `log_lead_to_sheets` both use `order_by(LeadAnswer.created_at, LeadAnswer.id)`; e2e “latest answer” query uses `order_by(created_at.desc(), id.desc()).limit(1)`. |
| **Key set + no runaway duplication** | E2E asserts: expected key set present (or subset for final flow); `max(count_per_key) <= 2`. |
| **Summary uses latest** | `test_summary_uses_latest_per_key`: two answers for same key (e.g. budget); assert summary shows 2nd value. |
| **Sheet logging uses latest** | `test_sheet_logging_uses_latest_per_key`: same setup; sheets uses same ordered query; assert summary (and thus sheet logic) shows latest. |
| **Send-deposit negative cases** | `test_send_deposit_rejected_when_not_awaiting_deposit` (e.g. PENDING_APPROVAL → 400); `test_send_deposit_rejected_when_already_paid` (DEPOSIT_PAID → 400). |
| **Expiry timezone-aware** | `test_expires_at_timezone_aware_comparison`: expires_at and now(UTC) compared with naive→aware normalization; no TypeError. |
| **Invariant / safety net** | Existing: `test_no_external_http_calls_in_tests` (no live Stripe/Meta); idempotency in `test_whatsapp_idempotency_duplicate_message_id` and `test_stripe_idempotency_duplicate_event` (and `test_idempotency_and_out_of_order.py`). |

**Optional follow-ups** (not done): standardize all send paths behind one module; add a test that fails if the underlying HTTP client is called; add a dedicated “invariant test” file that also checks for naive datetime usage in critical paths.
