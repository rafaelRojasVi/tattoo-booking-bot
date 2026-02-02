# Conversation System & Naturalness Review

**Goal:** Make the WhatsApp conversation feel natural (less scripted) while staying deterministic, safe, and robust. No LLMs.

---

## 1) File-by-file map (paths)

| Path | Role |
|------|------|
| **Orchestrator / state** | |
| `app/services/conversation.py` | Main handler: `handle_inbound_message`, status branches, question flow, handover, tour, opt-out |
| `app/services/state_machine.py` | `ALLOWED_TRANSITIONS`, transition helpers; no copy |
| **Questions & copy** | |
| `app/services/questions.py` | `CONSULTATION_QUESTIONS` (Question dataclass: key, text, required, validation_hint); `get_question_by_index`, `get_total_questions` |
| `app/copy/en_GB.yml` | User-facing message keys + 2–3 variants each; `{variable_name}` substitution |
| `app/config/voice_pack.yml` | Tone: spelling (UK), banned_phrases, preferred_terms, emoji, greeting/sign_off |
| **Message composition** | |
| `app/services/message_composer.py` | `MessageComposer`, `render_message(key, lead_id, **kwargs)`; loads YAML, deterministic variant by `hash(key:lead_id) % len(variants)` |
| `app/services/tone.py` | `apply_voice(text, is_template)` — spelling, banned phrases, emoji limit; not applied to templates |
| **Templates (24h / Meta)** | |
| `app/services/whatsapp_templates.py` | Template names/params for next-steps, re-open window |
| `app/services/template_registry.py` | Required template list for window check |
| `app/services/template_check.py` | Validates templates exist |
| **Sending & window** | |
| `app/services/messaging.py` | `send_whatsapp_message`, `format_deposit_link_message`, `format_payment_confirmation_message` |
| `app/services/whatsapp_window.py` | 24h window check, `send_with_window_check` |
| **Handover / repair** | |
| `app/services/handover_service.py` | `should_handover`, `get_handover_message(handover_reason, lead_id)` → copy key by reason |
| `app/services/parse_repair.py` | Two-strikes logic, `trigger_handover_after_parse_failure` → `handover_bridge` |
| **Slots / calendar / time** | |
| `app/services/calendar_service.py` | Slot fetch, format slot list; uses `slot_suggestions_*` from copy |
| `app/services/slot_parsing.py` | `parse_slot_selection` (number, day+time, time-based) |
| `app/services/time_window_collection.py` | Time-window prompts (`time_window_*` keys) |
| **Other** | |
| `app/services/artist_notifications.py` | Notify artist (internal + optional client-facing lines) |
| `app/services/reminders.py` | Qualifying / stale / deposit reminders; uses window check |
| `app/api/webhooks.py` | Entry: WhatsApp/Stripe webhooks, call `handle_inbound_message` / Stripe handler |
| `app/api/admin.py` | Approve, send-deposit, reject; uses `format_deposit_link_message`, templates |

---

## 2) User-facing messages: where they live and what triggers them

| Copy key (en_GB.yml) | Trigger (status / event) | Used in |
|----------------------|---------------------------|--------|
| `welcome` | NEW → first contact | `conversation._handle_new_lead` |
| `panic_mode_response` | Panic mode on, within 24h | `conversation.handle_inbound_message` (panic branch) |
| `pending_approval` | PENDING_APPROVAL, any message | `conversation` (status branch) |
| `awaiting_deposit` | AWAITING_DEPOSIT, any message | `conversation` (status branch) |
| `deposit_paid` | DEPOSIT_PAID, any message | `conversation` (status branch) |
| `booking_pending` | BOOKING_PENDING (no slot selected) | `conversation` (status branch) |
| `tour_accept` / `tour_decline` / `tour_prompt` / `tour_waitlisted` | Tour conversion flow | `conversation` (tour branch) |
| `opt_out_confirmation` / `opt_out_prompt` | Opt-out flow | en_GB; **conversation uses hardcoded string** for opt-out confirmation (bug) |
| `handover_coverup` / `handover_high_complexity` / `handover_client_question` / `handover_generic` / `handover_question` / `handover_question_prompt` | NEEDS_ARTIST_REPLY (reason-based) | `handover_service.get_handover_message`, `conversation` |
| `handover_bridge` | Two-strikes parse handover | `parse_repair.trigger_handover_after_parse_failure` |
| `budget_below_minimum` | Budget below region min (NEEDS_FOLLOW_UP) | `conversation._complete_qualification` |
| `continue_prompt` | After CONTINUE resume | `conversation` (continue branch) |
| `deposit_link` / `payment_confirmation` | Deposit link sent / payment confirmed | `messaging.format_*`, admin / webhooks |
| `time_window_request` / `time_window_collected` / `time_window_follow_up` / `time_window_follow_up_remaining` | COLLECTING_TIME_WINDOWS | `time_window_collection` |
| `slot_suggestions_empty` / `slot_suggestions_header` / `slot_suggestions_footer` | Slot suggestions (calendar) | `calendar_service` |
| `repair_size` / `repair_budget` / `repair_location` / `repair_slot` | Parse failure (soft repair) | `conversation` (qualifying parse branches), slot branch |
| `confirmation_summary` / `confirmation_slot` | Micro-confirm (dims/budget/location); slot selected | `conversation._maybe_send_confirmation_summary`, slot selection |
| `error_no_questions` | No questions configured | Fallback in composer |

**Hardcoded (no copy key):**

- Next question text: **`next_question.text`** from `questions.py` (long, single variant).
- Opt-out confirmation in `conversation._handle_opt_out`: *"You've been unsubscribed… If you change your mind, just send us a message…"* (should use `opt_out_confirmation`).

**Voice pack:** Applied only to free-form text via `tone.apply_voice(text, is_template=False)`. Templates and many composed messages are not passed through it (composer returns string; caller would need to call `apply_voice` if desired).

---

## 3) Voice pack implementation

- **Where:** `app/config/voice_pack.yml`; loaded by `app/services/tone.py` (`load_voice_pack()`).
- **What it does:** `apply_voice(text, is_template=False)` — UK spelling, banned_phrases → phrase_replacements, preferred_terms, emoji cap, banned emojis. **Not** applied to template messages.
- **Formatting:** Copy comes from `message_composer.render_message(key, lead_id=..., **kwargs)` (YAML + `{var}`). No post-render voice application in conversation flow today; so most bot messages never go through `apply_voice`.
- **Variants:** Only in `en_GB.yml` per key (2–3 variants). Selection is deterministic: `hash(key:lead_id) % len(variants)`. No retry_count, time_of_day, or tone-based selection.

---

## 4) Naturalness audit (per step/status)

| Step / status | Rating | Why |
|---------------|--------|-----|
| Welcome + first question | **Ok** | Friendly variants; question text is long and instructional (robotic). |
| Next questions (2–12) | **Robotic** | Raw `question.text` every time; no “Got it” before next; same structure every step. |
| Soft repair (size/budget/location/slot) | **Ok** | “Just to make sure…” variants; could add retry-specific shortening. |
| Two-strikes handover | **Ok** | “I’m going to have Jonah jump in here” — natural; then handover message. |
| Micro-confirmation (dims, budget, location) | **Ok** | “Got it — X, Y, budget ~£Z”; good. |
| PENDING_APPROVAL | **Ok** | “Thanks! I’m reviewing…” — fine. |
| AWAITING_DEPOSIT | **Ok** | “Check your messages for the deposit link…” — clear. |
| Slot suggestions | **Robotic** | Header + list + “Reply with number (1–8)” — very form-like. |
| Slot repair | **Ok** | “Which option number (1–8)?” — clear. |
| Tour offer / accept / decline / waitlist | **Ok** | Variants present; prompt is a bit imperative. |
| Budget below minimum | **Ok** | States min and asks to continue. |
| Handover (coverup / complexity / question) | **Ok** | Reason-specific; “passing to Jonah” is human. |
| Opt-out | **Robotic** | Hardcoded text; “send us a message” vs copy “Send START” — inconsistent. |
| Panic mode | **Ok** | Short “Jonah will reply shortly.” |

**Repeated phrasing:** “I’ll get back to you soon” / “Jonah will get back to you” appears in many status messages. “Please reply with…”, “Just type…”, “Reply with the number (1–8)” — repetitive.

**Abrupt transitions:** After saving an answer, the next message is often the next question text with no short acknowledgement (“Got it” / “Thanks”). Exception: micro-confirmation after dimensions/budget/location.

**Overlong prompts:** `questions.py` texts are long (placement, dimensions, complexity, timing) with bullet points and examples — good for clarity, heavy for chat.

---

## 5) Message Intent + Variants system (no LLM)

### 5.1 Intents (examples)

- `ACK` — short acknowledgement before next question or after action.
- `ASK_IDEA` … `ASK_TIMING` — one per question key; or generic `ASK_QUESTION` with `question_key` in ctx.
- `REPAIR_SIZE` / `REPAIR_BUDGET` / `REPAIR_LOCATION` / `REPAIR_SLOT` — soft repair (with retry_count in ctx).
- `CONFIRMATION_SUMMARY` / `CONFIRMATION_SLOT` — micro-confirm.
- `OFFER_SLOTS` — header + list + footer (slot suggestions).
- `NEEDS_ARTIST_REPLY` — handover (reason in ctx).
- `PENDING_APPROVAL` / `AWAITING_DEPOSIT` / `DEPOSIT_PAID` / `BOOKING_PENDING` — status replies.
- `TOUR_PROMPT` / `TOUR_ACCEPT` / `TOUR_DECLINE` / `TOUR_WAITLISTED` — tour flow.
- `BUDGET_BELOW_MIN` — needs follow-up.
- `OPT_OUT` — unsubscribe confirmation.
- `PANIC_MODE` — safe holding message.

### 5.2 Variants per intent (3–5: short / medium / empathetic)

- **ACK (before next question):**  
  Short: “Got it.”  
  Medium: “Got it — next question.”  
  Empathetic: “Thanks for that. Next one:”
- **ASK_QUESTION (with question_text):**  
  Short: “{question_text}”  
  Medium: “Next: {question_text}”  
  Empathetic: “Whenever you’re ready: {question_text}”
- **REPAIR_* (retry 1 vs 2):**  
  Retry 1: current “Just to make sure…”  
  Retry 2: shorter “Could you give me [X] in a simple form? e.g. …”
- **OFFER_SLOTS:**  
  Short: “Slots: [list]. Reply with 1–8.”  
  Medium: current header + list + footer.  
  Empathetic: “Here are some options that might work — reply with the number that suits you.”

### 5.3 Selection rule (deterministic, no LLM)

- **retry_count:** For REPAIR_*, use shorter variant if `retry_count >= 1`.
- **time_of_day:** Optional: `datetime.utcnow().hour` → morning/afternoon/evening; pick variant index by `(lead_id + hour_bucket) % len(variants)` for slight variation.
- **user_tone:** Not available without LLM; skip or use “length” of last message (e.g. one-word vs paragraph) as proxy for “short” vs “detailed” and pick variant (optional).
- **language:** `lead.preferred_language` or locale from first message; if `es` load `app/copy/es.yml` and use same intent keys (future).

**Compliance:** Required info is in the **content** of each variant (e.g. min budget in BUDGET_BELOW_MIN, slot range in OFFER_SLOTS). All variants for an intent must contain the same required info; only phrasing and length differ.

---

## 6) Minimal code diff: `compose_message(intent, ctx)`

- **Add:** `app/services/message_composer.py` — `compose_message(intent: str, ctx: dict) -> str`.
  - `intent` = enum or string: `ACK`, `ASK_QUESTION`, `REPAIR_SIZE`, …, `OFFER_SLOTS`, etc.
  - `ctx` = `lead_id`, `question_text`, `retry_count`, `min_gbp`, `slot_list`, `window_count`, …
  - Implementation: map `intent` to existing copy key(s) or new keys in `en_GB.yml`; pull `retry_count` / optional time bucket; call existing `render_message(key, lead_id=ctx.get("lead_id"), **ctx)` and optionally `apply_voice(result)`.
- **Replace:** In `conversation.py`, replace direct `render_message("repair_budget", ...)` with `compose_message("REPAIR_BUDGET", { "lead_id": lead.id, "retry_count": get_failure_count(lead, "budget") })`. Same for other repair keys, status keys, handover, tour, opt-out.
- **Questions:** Keep `questions.py` for structure; optionally add a second field per question, e.g. `text_short`, and have `compose_message("ASK_QUESTION", { "question_key": key, "question_text": question.text, "question_text_short": question.text_short })` so variants can be “Next: {question_text}” vs “{question_text_short}”.
- **Opt-out:** Replace hardcoded string in `_handle_opt_out` with `compose_message("OPT_OUT", { "lead_id": lead.id })` → `opt_out_confirmation` in YAML.

No change to state machine or acceptance behaviour; only where copy is sourced and how variant is chosen.

---

## 7) Edge-case coverage (today vs missing)

| Edge case | Today | Gap / proposal |
|-----------|--------|------------------|
| Free text when expecting number / multiple fields | Parse fails → soft repair → two-strikes handover. Budget: `re.findall(r"\d+", ...)`. | **Add:** Normalise “400 gbp”, “£400”, “400 pounds” in one place; accept single number as budget. **Tests:** `test_budget_accepts_currency_symbols`, `test_budget_accepts_gbp_pounds`. |
| Ambiguous time (“tomorrow morning”, “next week”, “2ish”) | Slot parsing: day + morning/afternoon/evening; no “tomorrow” or “next week”. | **Add:** In `slot_parsing` or calendar layer, map “tomorrow” to date; “next week” → suggest “I don’t have exact dates for next week — can you pick from the slots below or say a weekday?”. **Tests:** `test_slot_ambiguous_tomorrow`, `test_slot_next_week_fallback`. |
| Currency + budget (“400”, “£400”, “400gbp”, “$500”) | Budget: digits only. Sheets/summary strip £,$. | **Add:** Single `parse_budget_from_text(text) -> int | None` (pence): strip £ $ gbp usd pounds; parse number; default currency from region. **Tests:** `test_parse_budget_currency_symbols`, `test_parse_budget_gbp_usd`. |
| Language detection / switch mid-flow | None. Locale fixed (en_GB). | **Add:** Optional `lead.preferred_language`; on first message or keyword (“español”), set and load `es.yml`; same intent keys. **Tests:** `test_preferred_language_stored`, `test_message_uses_lead_locale`. |
| Attachments at wrong step (store + ack) | Attachments create `Attachment`; webhook handles. | **Add:** If attachment when we’re on a step that doesn’t expect image, store and reply with “Got it, I’ve saved the image. For this step I need [question]: [question_text].” **Tests:** `test_attachment_at_qualifying_step_ack_and_reprompt`. |
| Duplicate webhook / out-of-order | `ProcessedMessage`; duplicate message_id returns 200 + “duplicate”; Stripe idempotent by event id. | Covered. **Tests:** existing in `test_go_live_guardrails`, `test_idempotency_and_out_of_order`. |
| “Stop”, “unsubscribe”, “human”, “refund”, “delete my data” | STOP/UNSUBSCRIBE/OPT OUT → opt-out flow. | **Add:** “human” / “talk to someone” → same as handover (NEEDS_ARTIST_REPLY). “refund” → “Refunds are handled by Jonah — I’ve passed your message to him.” (no status change) or handover. “delete my data” → “I’ve passed your request to Jonah; he’ll handle data requests.” + handover or internal flag. **Tests:** `test_human_triggers_handover`, `test_refund_ack_and_handover`, `test_delete_data_ack`. |
| Hold expires while paying; payment succeeds, calendar write fails (Phase 2) | N/A Phase 1. | **Add:** Idempotent “payment received” handling; on success create calendar event; on calendar failure retry + alert; do not double-charge. **Tests:** `test_payment_success_calendar_retry`, `test_hold_expired_payment_still_processed`. |
| DST / timezone (Europe/London) | Calendar/slots use datetimes; admin compares `expires_at` with UTC. | **Add:** Store all server-side datetimes in UTC; slot display use lead’s timezone or config. **Tests:** `test_slot_display_timezone`, `test_expires_at_utc`. |
| Concurrency: two holds, two clients, same slot | Phase 1: no holds. Phase 2: hold table + TTL; conflict on create_hold. | **Add:** Optimistic lock or unique (slot_id, start_time) and “slot no longer available” message. **Tests:** `test_two_clients_same_slot_second_fails`. |

---

## 8) Implementation plan (exact functions and insert points)

| # | Action | Where | Function / change |
|---|--------|--------|-------------------|
| 1 | Add intent→key map and ctx handling | `app/services/message_composer.py` | `compose_message(intent: str, ctx: dict) -> str`; map intent to YAML key; add `retry_count` → variant index; call `render_message` and optionally `apply_voice`. |
| 2 | Add budget parser (currency) | `app/services/estimation_service.py` or `app/services/pricing_service.py` | `parse_budget_from_text(text: str, default_currency_pence_per_unit: int = 100) -> int | None` (return pence); strip £ $ gbp usd; parse number; scale by currency. |
| 3 | Use budget parser in qualifying | `app/services/conversation.py` | In budget branch: call `parse_budget_from_text(message_text)`; if None, same repair/handover as now. |
| 4 | Opt-out use copy | `app/services/conversation.py` | In `_handle_opt_out`: replace hardcoded string with `compose_message("OPT_OUT", {"lead_id": lead.id})`. |
| 5 | Repair messages use compose + retry_count | `app/services/conversation.py` | Replace `render_message("repair_size", ...)` with `compose_message("REPAIR_SIZE", {"lead_id": lead.id, "retry_count": get_failure_count(lead, "dimensions")})`; same for budget, location, slot. |
| 6 | Optional ACK before next question | `app/services/conversation.py` | After saving answer and before sending next question: send `compose_message("ACK", {"lead_id": lead.id})` then next question; or fold into ASK_QUESTION variant “Got it. Next: {question_text}”. |
| 7 | “Human” / “refund” / “delete my data” | `app/services/conversation.py` | In `_handle_qualifying_lead`, after opt-out check: if message_upper in (“HUMAN”, “TALK TO SOMEONE”, “PERSON”, …) → handover. If “REFUND” → ack + handover. If “DELETE MY DATA” / “DELETE DATA” → ack + handover or flag. Add copy keys `refund_ack`, `delete_data_ack`. |
| 8 | Attachment at wrong step ack | `app/api/webhooks.py` or conversation | When processing image and current step is not reference_images: create attachment, send “Got it, I’ve saved the image. For this step I need [current_question.text].” (or use compose_message). |
| 9 | Slot “tomorrow” / “next week” | `app/services/slot_parsing.py` | Add `_parse_relative_day(message_lower, slots)`; if “tomorrow”/“next week” and no match, return None and let caller send “I don’t have exact times for that — here are my current options: [list].” |

---

## 9) New tests to add (pytest)

- **Naturalness / composer:**  
  - `test_compose_message_intent_maps_to_key`  
  - `test_compose_message_retry_count_selects_shorter_variant`  
  - `test_opt_out_uses_copy_not_hardcoded`

- **Budget / currency:**  
  - `test_parse_budget_from_text_plain_number`  
  - `test_parse_budget_from_text_currency_symbols`  
  - `test_parse_budget_from_text_gbp_usd`  
  - `test_budget_accepts_400_gbp_in_qualifying`

- **Slot / time:**  
  - `test_slot_ambiguous_tomorrow_returns_none_or_fallback`  
  - `test_slot_next_week_fallback_message`  
  - `test_slot_display_timezone_consistent_utc`

- **Safety / keywords:**  
  - `test_human_triggers_handover`  
  - `test_refund_ack_and_handover`  
  - `test_delete_data_ack_and_handover`

- **Attachments:**  
  - `test_attachment_at_qualifying_step_stored_and_ack_reprompt`

- **Idempotency / concurrency (Phase 2):**  
  - `test_hold_expired_payment_still_processed`  
  - `test_payment_success_calendar_retry_on_failure`  
  - `test_two_clients_same_slot_second_fails_or_gets_unavailable`

- **Timezone:**  
  - `test_expires_at_always_utc_compared_with_now_utc`

---

## 10) Five example before/after flows (more natural)

### Example 1: Welcome + first question

- **Before:** “👋 Hi! Thanks for reaching out. Let's get some details about your tattoo idea.\n\nWhat tattoo do you want? Please describe it in detail.”
- **After (short variant):** “Hi! What tattoo do you have in mind? Describe it in a few words and we’ll go from there.”

### Example 2: After budget answer, next question (with ACK)

- **Before:** “What's the approximate size? Please give dimensions in cm (e.g., 8×12cm)…”
- **After:** “Got it — 500. Next: size? e.g. 8×12cm or palm-sized.”

### Example 3: Repair budget (retry 2)

- **Before:** “Just to clarify — what's your budget amount? A number like 500, 1000, or 2000 works.”
- **After (retry 2):** “Could you send just a number? e.g. 500 or 1000.”

### Example 4: Slot selection

- **Before:** “📅 *Available Booking Slots*\n\nHere are some available times (Europe/London):\n1. Mon 25 Jan 10:00–13:00\n…\n\nPlease reply with the number (1-8) or describe which slot works for you.”
- **After:** “Here are some options — reply with the number that works for you (1–8):\n1. Mon 25 Jan 10:00–13:00\n…”

### Example 5: Opt-out + retry

- **Before:** Hardcoded “You've been unsubscribed… If you change your mind, just send us a message…”
- **After:** “You’re unsubscribed from automated messages. Send START anytime to resume.” (from `opt_out_confirmation` variant.)

---

**Summary:** The system is already well-structured (orchestrator, state machine, copy in YAML, variants, voice pack). The main gains are: (1) consistent use of copy via `compose_message(intent, ctx)` and fixing opt-out hardcode, (2) optional short ACK or “Got it — next” before questions, (3) retry-aware repair variants, (4) budget/currency parsing and safety keywords (human/refund/delete data), (5) attachment ack at wrong step, (6) slot/time edge cases and Phase 2 concurrency/calendar. All without LLMs and without changing acceptance criteria.
