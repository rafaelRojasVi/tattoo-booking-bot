# Parser and core functions review

Quick review of main parsers and critical logic: **reproducibility** and **structure** (not “vibe coded”).

---

## 1. Slot parsing (`app/services/slot_parsing.py`)

**Main API:** `parse_slot_selection(message, slots, max_slots=8) -> (index | None, metadata)`  
**Logged wrapper:** `parse_slot_selection_logged(...)` — same logic + system events.

**Design:** Tiered, explicit intent, no guessing.

- **Tier 1 (explicit):** Bare digit `"1"`–`"9"` (validated against `effective_max`), `option 3`, `#3`, `3)`, `3.`
- **Tier 2a:** Day + time words: `"Tuesday afternoon"`, `"Monday morning"` — fixed day names + time_keywords (morning/afternoon/evening/night) with hour ranges; matches first slot in range.
- **Tier 2b:** Time only: `5pm`, `2:00pm`, `14:00` / `14.00` — regex for 12h/24h; matches slot within 30 min; **no** match for ambiguous `"at 5"` (no am/pm).
- **Reject:** Multiple slot numbers in message → `(None, {"reason": "multiple_numbers"})`; out-of-range digit → `out_of_range`; else `no_intent` or `no_time_match`.

**Reproducibility:** High. Pure function (except the logged wrapper). Same `(message, slots, max_slots)` → same result. Uses `normalize_text` before parsing.

**Vibe check:** Not vibe coded. Docstring, tier order, explicit intent, and reject reasons are clear. One small fragility: `_parse_day_time` returns the **first** matching slot when only day matches (no time range); if several slots same day, always slot 1. Documented and consistent.

---

## 2. Location parsing (`app/services/location_parsing.py`)

**Main API:** `parse_location_input(location_text) -> {city, country, is_flexible, is_only_country, needs_follow_up}`

**Design:** Keyword + lookup.

- Flexible: `FLEXIBLE_KEYWORDS` (flexible, anywhere, any, wherever, etc.) → `is_flexible=True`, no city/country.
- “City Country”: split on spaces; last token (or last two) matched against `COUNTRIES`; remainder → city.
- Country-only: full string in `COUNTRIES` or multi-word country key in string → `is_only_country=True`, `needs_follow_up=True`.
- Else: treat as city; infer country from `CITY_TO_COUNTRY` if present.

**Reproducibility:** High. Pure function; same input → same output. No normalization beyond strip/lower (no unicode normalizer like slot/dimensions).

**Vibe check:** Mostly solid. Logic is step-by-step. Two caveats: (1) No shared text normalization (e.g. NFC) — could add for consistency with other parsers. (2) “City Country” assumes last token(s) are country; odd inputs like “London London” could misparse. Bounded by fixed dicts; not ad-hoc regex soup.

---

## 3. Dimensions & budget (`app/services/estimation_service.py`)

**parse_dimensions(text):**  
- Uses `normalize_for_dimensions` (× → x, spaces).  
- Two regexes: `W x H` with unit (cm/inch/inches/in), or single number + unit (assume square).  
- Converts to cm; rejects if either side > 100 cm.  
- Returns `(width_cm, height_cm)` or `None`.

**parse_budget_from_text(text):**  
- Uses `normalize_for_budget`, strip currency symbols and words (gbp, pounds, usd, …), strip commas.  
- `re.findall(r"\d+(?:\.\d+)?", cleaned)` → first number.  
- Rejects negative (prefix `-` or `-` before number) and zero.  
- `k` suffix → multiply by 1000.  
- Returns pence (value × 100). Assumes GBP for storage.

**Reproducibility:** High. Pure; normalization applied consistently. Currency assumption (GBP) is explicit.

**Vibe check:** Not vibe coded. Patterns and bounds documented. Single-number dimension “assume square” is a clear rule. Budget “first number only” avoids range ambiguity by design.

---

## 4. Text normalization (`app/services/text_normalization.py`)

**normalize_text(text):** Strip, NBSP/ZWSP/ZWNBSP → space/remove, NFC, collapse spaces.  
**normalize_for_dimensions:** normalize_text + × → x.  
**normalize_for_budget:** normalize_text (commas handled in parser).

**Reproducibility:** High. Pure, idempotent for same input.

**Vibe check:** Small, focused module. Used by slot, dimensions, budget. Good.

---

## 5. Parse repair (`app/services/parse_repair.py`)

**increment_parse_failure(db, lead, field)** / **reset_parse_failures** / **get_failure_count** / **should_handover_after_failure** (count >= 3).  
**trigger_handover_after_parse_failure:** transition to NEEDS_ARTIST_REPLY, notify, send message.

**Reproducibility:** Depends on DB state; behavior is deterministic for given `parse_failure_counts` and `field`. Constants (`ParseableField`, `MAX_FAILURES=3`) are explicit.

**Vibe check:** Clear. Typed field, single threshold, no magic numbers elsewhere.

---

## 6. State machine (`app/services/state_machine.py`)

**ALLOWED_TRANSITIONS:** Dict from_status → list of to_status. Single source of truth.  
**is_transition_allowed(from_status, to_status):** Lookup in that dict.  
**transition(db, lead, to_status, ...):**  
1. Check allowed.  
2. If `lock_row`: SELECT FOR UPDATE, re-check status (another request may have changed it).  
3. Update status and optional timestamps.  
4. Commit; side effects (WhatsApp, etc.) happen after.

**Reproducibility:** For a given DB state and `to_status`, outcome is deterministic. Concurrency handled by lock and re-check.

**Vibe check:** Not vibe coded. Explicit table, validation, locking, and “side effects after commit” are documented and consistent.

---

## 7. Conversation policy (`app/services/conversation_policy.py`)

**normalize_message(text):** strip, upper.  
**Opt-out:** exact match in `OPT_OUT_KEYWORDS` (STOP, UNSUBSCRIBE, OPT OUT, OPTOUT).  
**Opt-back-in:** exact match in `OPT_BACK_IN_KEYWORDS` (START, RESUME, CONTINUE, YES).  
**Human/refund/delete:** keyword sets and substring checks (e.g. "REFUND", DELETE_DATA phrases).  
**handover_hold_cooldown_elapsed(last_hold_at, now_utc, cooldown_hours):** timedelta comparison.

**Reproducibility:** High. Pure helpers; same input → same result.

**Vibe check:** Not vibe coded. Frozensets, named constants, simple rules. Easy to extend or test.

---

## Summary table

| Area              | Reproducible | Structured / not vibe coded | Notes |
|-------------------|-------------|-----------------------------|--------|
| Slot parsing      | Yes         | Yes                         | Tiered, explicit intent, clear reject reasons. |
| Location parsing  | Yes         | Mostly yes                  | Add NFC/normalization for consistency. |
| Dimensions/budget | Yes         | Yes                         | Clear patterns and bounds. |
| Text normalization| Yes         | Yes                         | Small, reused. |
| Parse repair      | Yes*        | Yes                         | *Given DB state. Constants explicit. |
| State machine     | Yes         | Yes                         | Table-driven, locking, side effects after commit. |
| Conversation policy | Yes      | Yes                         | Keyword sets, pure helpers. |

**Overall:** Parsers and core logic are **reproducible and not vibe coded**. They use explicit rules, constants, and normalization; state machine and repair have clear contracts. Only minor improvement: unify text normalization (e.g. NFC) for location input if you want full consistency with slot/dimensions/budget.
