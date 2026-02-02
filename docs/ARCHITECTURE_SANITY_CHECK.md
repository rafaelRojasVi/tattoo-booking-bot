# Architecture sanity-check report

Review of the FastAPI WhatsApp booking assistant across seven categories. For each issue: severity, location, production impact, and fix strategy.

---

## 1) Separation of concerns (API vs services vs db)

### 1.1 Webhook does business logic before delegating

**Severity:** Minor  
**Location:** `app/api/webhooks.py` ~246–275 (out-of-order check, timestamp comparison), and pilot-mode message content inline ~196–201.

**Why it matters:** Webhook layer contains timestamp comparison and pilot message copy; small changes (e.g. cooldown policy) require touching the API layer.

**Fix:** Move out-of-order policy (e.g. “ignore if older than last_client_message_at”) into a small service (e.g. `conversation.should_process_message(lead, message_timestamp)`) and call it from the webhook. Move pilot message text to copy/YAML or a single constant in a copy or config module so it’s not a raw string in the route.

---

### 1.2 Conversation status changes bypass state machine

**Severity:** Major  
**Location:** `app/services/conversation.py` — all `lead.status = ...` (e.g. 459, 486, 538, 554, 561, 574, 682, 924, 963, 983, 1003, 1028, 1153, 1233, 1322, 1374, 1396, 1422). `app/services/state_machine.py` defines `ALLOWED_TRANSITIONS` and `transition()` but is **never called** from conversation or webhooks.

**Why it matters:** Invalid transitions (e.g. OPTOUT → NEW for “opt back in”, or ABANDONED/STALE → NEW for restart) are allowed in code but marked terminal in the state machine. No row-level lock on status change in conversation, so two parallel requests can both read the same status and both transition — last write wins, risking double side effects or inconsistent state.

**Fix strategy:**

1. **Option A (recommended):** Use `state_machine.transition()` for every status change in `conversation.py` (and anywhere else that sets `lead.status`). Extend `ALLOWED_TRANSITIONS` where product intent is “restart” (e.g. OPTOUT → NEW, ABANDONED → NEW, STALE → NEW) so those are explicit allowed transitions. That gives you one place for allowed transitions, row locking (SELECT FOR UPDATE inside `transition()`), and consistent timestamps.
2. **Option B:** If you keep direct assignment, add a guard: `if not is_transition_allowed(lead.status, new_status): raise ValueError(...)` and document that conversation is the source of truth and state_machine is advisory. Still no locking; concurrency issues remain unless you add locking in conversation.

**Concrete (Option A):** In `state_machine.py`, add to `ALLOWED_TRANSITIONS`:

- `STATUS_OPTOUT: [STATUS_NEW]`
- `STATUS_ABANDONED: [STATUS_NEW]`
- `STATUS_STALE: [STATUS_NEW]`

Then in `conversation.py`, replace each `lead.status = X; db.commit()` with:

```python
from app.services.state_machine import transition
transition(db, lead, X, reason=..., update_timestamp=True, lock_row=True)
```

(and handle `ValueError` for invalid transitions).

---

## 2) State machine correctness and invariants

### 2.1 Terminal states allow “restart” in conversation only

**Severity:** Major (same as 1.2)  
**Location:** `app/services/state_machine.py` 126–128 (`STATUS_OPTOUT` terminal); `app/services/conversation.py` 534–539 (OPTOUT → NEW on START/RESUME/CONTINUE/YES), 552–561 (ABANDONED/STALE → NEW).

**Why it matters:** State machine says OPTOUT/ABANDONED/STALE are terminal; conversation implements “opt back in” and “restart” by setting status to NEW. So either the state machine is wrong (should allow these transitions) or conversation is wrong. As written, invariants are not enforced at runtime.

**Fix:** Align state machine with product: add OPTOUT → NEW, ABANDONED → NEW, STALE → NEW to `ALLOWED_TRANSITIONS` (see 1.2), then enforce via `transition()`.

---

### 2.2 STATUS_BOOKING_LINK_SENT not in state machine

**Severity:** Minor  
**Location:** `app/services/conversation.py` 357–365 (branch `lead.status == STATUS_BOOKING_LINK_SENT`, then `lead.status = STATUS_BOOKING_PENDING`). `app/services/state_machine.py` does not list `STATUS_BOOKING_LINK_SENT` in `ALLOWED_TRANSITIONS`.

**Why it matters:** Legacy or alternate flows that set BOOKING_LINK_SENT are not validated; if something else sets it, the state machine doesn’t document or enforce the only valid next step (BOOKING_PENDING).

**Fix:** Add `STATUS_BOOKING_LINK_SENT` to the state machine with a single allowed transition to `STATUS_BOOKING_PENDING`, and use `transition()` there (or at least `is_transition_allowed` before assigning).

---

## 3) Message sending consistency (compose_message vs raw strings)

### 3.1 Holding message is a raw string

**Severity:** Minor  
**Location:** `app/services/conversation.py` ~493:  
`holding_msg = "I've paused the automated flow. The artist will reply to you directly."`

**Why it matters:** Copy changes and localization require code edits; inconsistent with the rest of the flow (compose_message / YAML).

**Fix:** Add a key to copy (e.g. `handover_holding_reply`) in `app/copy/en_GB.yml` and map it in `message_composer.INTENT_TO_KEY`. In conversation, use `compose_message("HANDOVER_HOLDING_REPLY", {"lead_id": lead.id})` (or equivalent) instead of the raw string.

---

### 3.2 Pilot-mode message is a raw string in webhook

**Severity:** Minor  
**Location:** `app/api/webhooks.py` ~196–201: pilot message is a long inline string.

**Why it matters:** Same as 3.1 — copy and locale live in code instead of a single place.

**Fix:** Move to YAML (e.g. `pilot_mode_blocked`) or a constant in a copy/config module; webhook should pass a key or constant into messaging, not define the text.

---

### 3.3 Stripe payment confirmation appends raw policy text

**Severity:** Minor  
**Location:** `app/api/webhooks.py` ~634–639:  
`confirmation_message += "\n\n*Important:* Your deposit is non-refundable. ..."`

**Why it matters:** Policy wording should be in one place (copy/config) for consistency and legal updates.

**Fix:** Add a copy key (e.g. `deposit_policy_reminder`) and append `compose_message(...)` or `render_message(...)` result instead of a raw string.

---

## 4) Idempotency and out-of-order handling

### 4.1 WhatsApp: ProcessedMessage recorded after handle_inbound_message (good)

**Location:** `app/api/webhooks.py` 286–297: message_id is recorded only after successful `handle_inbound_message`. Duplicate delivery returns 200 and skips processing (162–174).  
**Verdict:** Correct — no change needed.

---

### 4.2 Stripe: record_processed_event after side effects (good)

**Location:** `app/api/webhooks.py` ~617–620 (comment), 695–704: `record_processed_event` is called after Sheets and WhatsApp.  
**Verdict:** Correct — retry-safe. If you later add more side effects, keep recording last.

---

### 4.3 Stripe idempotency check uses read-only check then atomic update

**Location:** `app/api/webhooks.py` 514–525: `check_processed_event` then `update_lead_status_if_matches`. Duplicate event_id returns early (518–525).  
**Verdict:** Correct. `record_processed_event` handles IntegrityError for concurrent duplicate (safety.py 156–166).

---

### 4.4 Out-of-order WhatsApp messages

**Location:** `app/api/webhooks.py` 249–275: if `message_timestamp < last_client_message_at`, request is ignored and 200 returned.  
**Verdict:** Policy is clear. Ensure `last_client_message_at` is updated in the same transaction as the main conversation update so ordering is consistent (currently updated inside `handle_inbound_message` on the same lead/commit — OK).

---

## 5) Concurrency / race conditions

### 5.1 Conversation status changes are not locked

**Severity:** Major  
**Location:** `app/services/conversation.py` — all status and step updates (e.g. 459, 476, 487, 574, 682, 868, 887, 1422) use plain `lead.status = ...; db.commit()` with no `SELECT FOR UPDATE`.

**Why it matters:** Two concurrent requests for the same lead (e.g. two tabs or retries) can both read the same status/step, both run qualification logic, both commit — last write wins. Result: duplicate messages, double advance, or inconsistent state (e.g. two “next question” sends).

**Fix:** Use `state_machine.transition()` (which uses SELECT FOR UPDATE) for all status changes. For step advances (e.g. `lead.current_step = current_step + 1`), either: (a) do them inside a transaction that also locks the lead row (`select(Lead).where(Lead.id == lead.id).with_for_update()`), or (b) use an atomic “increment step only if status and step match” update (similar to `update_lead_status_if_matches`) to avoid lost updates.

---

### 5.2 ProcessedMessage insert race

**Location:** `app/services/safety.py` 146–166: `record_processed_event` catches IntegrityError and returns existing record.  
**Verdict:** Safe — duplicate message_id from two concurrent webhooks results in one processing and one no-op after insert conflict.

---

### 5.3 Stripe webhook: atomic status update

**Location:** `app/api/webhooks.py` 539–545, 561–567: `update_lead_status_if_matches` does an atomic UPDATE ... WHERE status = expected.  
**Verdict:** Prevents double application of payment; good.

---

## 6) Data integrity (LeadAnswer, latest-wins, Sheets)

### 6.1 answers_dict “latest-wins” not deterministic in conversation

**Severity:** Major  
**Location:**  
- `app/services/conversation.py` 1080–1082 (`_maybe_send_confirmation_summary`):  
  `stmt = select(LeadAnswer).where(LeadAnswer.lead_id == lead.id)` — **no order_by**.  
- `app/services/conversation.py` 1201–1205 (`_complete_qualification`): same.

**Why it matters:** LeadAnswer allows multiple rows per (lead_id, question_key) (e.g. resume from handover). Building `answers_dict = {ans.question_key: ans.answer_text for ans in answers_list}` with unordered query means “latest” is arbitrary. Summary, confirmation, and qualification can use stale or wrong answers (e.g. old budget, old location).

**Fix:** Use a deterministic latest-wins: order by `created_at`, `id` and take the last occurrence per key. Example:

```python
stmt = (
    select(LeadAnswer)
    .where(LeadAnswer.lead_id == lead.id)
    .order_by(LeadAnswer.created_at, LeadAnswer.id)
)
answers_list = db.execute(stmt).scalars().all()
answers_dict = {ans.question_key: ans.answer_text for ans in answers_list}
```

Apply this in both `_maybe_send_confirmation_summary` and `_complete_qualification` (and any other place that builds answers_dict from LeadAnswer without ordering).

---

### 6.2 handover_packet answers_dict from relationship

**Severity:** Minor  
**Location:** `app/services/handover_packet.py` 59–62: `for answer in lead.answers` then `answers_dict[answer.question_key] = answer.answer_text`. Relationship load order is not guaranteed.

**Why it matters:** Same as 6.1 — if there are multiple answers per key, which value is used is undefined.

**Fix:** Build answers_dict from an ordered query (e.g. `select(LeadAnswer).where(LeadAnswer.lead_id == lead.id).order_by(LeadAnswer.created_at, LeadAnswer.id)`) and then `{a.question_key: a.answer_text for a in answers_list}` so last wins.

---

### 6.3 Sheets logging uses ordered latest-wins (good)

**Location:** `app/services/sheets.py` 146–152: `order_by(LeadAnswer.created_at, LeadAnswer.id)` then dict build.  
**Verdict:** Correct — no change.

---

## 7) Error handling & observability

### 7.1 Correlation ID not propagated

**Severity:** Minor  
**Location:** `app/api/webhooks.py` 47–59: `correlation_id` is generated and logged at entry, but not passed to `handle_inbound_message`, `send_whatsapp_message`, or system_event_service.

**Why it matters:** When debugging a single request (e.g. “why did this user get this reply?”), logs from conversation, messaging, and Sheets are not tied to the same correlation_id, so tracing is manual.

**Fix:** Add an optional `correlation_id: str | None = None` to `handle_inbound_message` and pass it from the webhook. Thread it through to key log lines and to `system_event_service.info/warn/error` payloads. Use a context var or request-scoped dependency if you prefer not to pass it explicitly everywhere.

---

### 7.2 Conversation exceptions returned as 200

**Location:** `app/api/webhooks.py` 332–363: On exception in `handle_inbound_message`, webhook logs, records a system event, and returns `{"received": True, ...}` with an error field.

**Why it matters:** WhatsApp sees 200 and may not retry; the message is effectively dropped. Acceptable if you want to avoid duplicate processing on retry, but you lose the message unless you have a dead-letter or manual replay.

**Fix (optional):** If you want Meta to retry on transient failures, return 500 on certain exceptions (e.g. timeout, DB deadlock) and 200 only when you have successfully processed or deliberately skipped (duplicate, out-of-order). Document the contract (which errors → 500 vs 200).

---

### 7.3 No structured retry/backoff for external calls

**Severity:** Minor  
**Location:** `app/services/messaging.py` (send_whatsapp_message), Sheets, Stripe — no explicit retry with backoff in the reviewed code.

**Why it matters:** Transient failures (network, Meta/Google rate limits) cause one-off failures; retries with backoff improve success rate without overloading the provider.

**Fix:** Add a small retry helper (e.g. tenacity or a few lines with exponential backoff) around `send_whatsapp_message`, Sheets write, and Stripe API calls (if any) in the webhook path. Prefer “retry a few times then fail” so the webhook can return 500 and Meta/Stripe can retry the event.

---

## Summary table

| #   | Severity  | Category        | One-line description |
|-----|-----------|------------------|----------------------|
| 1.1 | Minor     | Separation       | Move OOO + pilot copy out of webhook |
| 1.2 | Major     | Separation       | Use state_machine.transition() in conversation |
| 2.1 | Major     | State machine    | Allow OPTOUT/ABANDONED/STALE → NEW; enforce via transition() |
| 2.2 | Minor     | State machine    | Add BOOKING_LINK_SENT to state machine |
| 3.1 | Minor     | Message consistency | Holding message from copy |
| 3.2 | Minor     | Message consistency | Pilot message from copy |
| 3.3 | Minor     | Message consistency | Deposit policy from copy |
| 5.1 | Major     | Concurrency      | Lock lead row (or use transition()) when changing status/step |
| 6.1 | Major     | Data integrity   | Order LeadAnswer by created_at, id for latest-wins in conversation |
| 6.2 | Minor     | Data integrity   | handover_packet answers_dict from ordered query |
| 7.1 | Minor     | Observability    | Pass correlation_id through conversation and events |
| 7.2 | Minor     | Error handling   | Document 200 vs 500; optionally 500 on transient errors |
| 7.3 | Minor     | Error handling   | Retry with backoff for send_whatsapp_message / Sheets |

Recommended order of work: **1.2 + 2.1 + 5.1** (state machine and locking), then **6.1** (answers_dict ordering), then the minor items (copy, correlation_id, retries).
