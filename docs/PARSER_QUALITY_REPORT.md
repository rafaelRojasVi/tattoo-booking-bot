# Parser Quality Report

Analysis of the WhatsApp consultation parser surface area, acceptance rules, test coverage, risk scoring, and recommended improvements.

---

## 1) Parser Surface Area

### Entry Points

| Module | Function | Purpose |
|--------|----------|---------|
| `app/services/estimation_service.py` | `parse_dimensions(text)` | Parse W×H cm/inches → `(float, float)` or None |
| `app/services/estimation_service.py` | `parse_budget_from_text(text)` | Parse £/€/$ amounts → pence (int) or None |
| `app/services/location_parsing.py` | `parse_location_input(text)` | Parse city/country → `{city, country, is_flexible, ...}` |
| `app/services/location_parsing.py` | `is_valid_location(text)` | Validates parsed location (not flexible, has city/country) |
| `app/services/slot_parsing.py` | `parse_slot_selection(message, slots, max_slots)` | Parse slot choice → 1-based index or None |
| `app/services/parse_repair.py` | `increment_parse_failure`, `reset_parse_failures`, `get_failure_count`, `should_handover_after_failure`, `trigger_handover_after_parse_failure` | Three-strikes repair → handover |
| `app/services/bundle_guard.py` | `looks_like_multi_answer_bundle(text, current_question_key)` | Detects 2+ signals (dimension, budget, style, @) → one-at-a-time reprompt |
| `app/services/bundle_guard.py` | `looks_like_wrong_field_single_answer(text, current_question_key)` | At idea/placement: budget-only or dimensions-only → wrong-field reprompt |
| `app/services/text_normalization.py` | `normalize_text`, `normalize_for_dimensions`, `normalize_for_budget` | Unicode, spaces, ×→x |
| `app/services/conversation.py` | `_handle_qualifying_lead` (lines ~700–1060) | Orchestrates parsing per step, repair, handover |

### Per-Step Parsing

| Step | Question Key | Parser | Returns | Validation |
|------|--------------|--------|---------|------------|
| 0 | idea | None | Accept any text | `looks_like_wrong_field_single_answer` (budget/dimensions-only → reprompt) |
| 1 | placement | None | Accept any text | Same wrong-field guard |
| 2 | dimensions | `parse_dimensions` | `(w, h)` cm or None | Repair → handover after 3 failures |
| 3 | style | None | Accept any text | — |
| 4 | complexity | None (parsed in `_complete_qualification`) | Accept any text | Post-hoc: first digit → 1–3, else default 2 |
| 5 | coverup | None | Accept any text | Post-hoc: YES/Y/TRUE/1 → coverup |
| 6 | reference_images | None | Accept any text or media | Media at wrong step → ack + reprompt |
| 7 | budget | `parse_budget_from_text` | pence or None | Repair → handover after 3 failures |
| 8 | location_city | `parse_location_input` + `is_valid_location` | city, country | Repair → handover after 3 failures |
| 9 | location_country | None | Accept any text | — |
| 10 | instagram_handle | None | Accept any text | — |
| 11 | travel_city | None | Accept any text | — |
| 12 | timing | None | Accept any text | — |
| — | slot (COLLECTING_TIME_WINDOWS) | `parse_slot_selection` | 1-based index or None | Repair → handover after 3 failures |

---

## 2) Acceptance Rules Per Step

### dimensions (step 2)

- **Accepted**: `10x12cm`, `10×12cm`, `10 x 12 cm`, `3x5 inches`, `10cm` (single → square)
- **Repair**: No match → REPAIR_SIZE (retry 1–2), handover at 3
- **Reprompt**: `looks_like_wrong_field_single_answer` at idea/placement
- **False positive risk**: Single-dimension `10cm` → (10, 10). "10" alone could match `(\d+)\s*(cm|inch)` if "cm" appears elsewhere. Pattern requires unit.

### budget (step 7)

- **Accepted**: `400`, `£400`, `400gbp`, `400k`, `400-500` (first number), `~400`, `around 400`
- **Rejected**: `0`, `-400`, no number, `four hundred`
- **Repair**: None → REPAIR_BUDGET → handover at 3
- **False positive risk**: "10" at dimensions step could parse as £10 (500 pence) if budget keywords present. Bundle guard uses `_MIN_BUDGET_PENCE = 5000` — numbers < £50 need currency keyword. "2" from "2 dragons" won't parse as budget without keyword.

### location_city (step 8)

- **Accepted**: "London UK", "Paris France", "London" (inferred country), "UK" (country only), flexible keywords → needs_follow_up
- **Rejected**: flexible ("anywhere", "flexible"), empty, too short (<2 chars)
- **Repair**: Invalid → REPAIR_LOCATION → handover at 3
- **False positive risk**: "RandomCity" with no country inference → `needs_follow_up=True` but still accepted. Postcodes (E1 6AN) may be treated as city. Unknown cities accepted as-is.

### slot (COLLECTING_TIME_WINDOWS)

- **Accepted**: "1", "option 3", "#5", "Monday morning", "Tuesday afternoon", "the 5pm one"
- **Rejected**: "1 or 2", "9" (out of range), "maybe", empty
- **Reprompt**: Multiple numbers → REPAIR_SLOT
- **False positive risk**: "I have 3 questions" → matches slot 3. "Call me at 5" → matches slot 5. Time pattern excludes "4:00pm" from number match, but "3" in "3 questions" still matches.

### idea, placement, style, complexity, coverup, reference_images, location_country, instagram_handle, travel_city, timing

- **Accepted**: Any non-empty text (no structured parser)
- **Guards**: `looks_like_wrong_field_single_answer` at idea/placement; `looks_like_multi_answer_bundle` before advancing
- **False positive risk**: Low for idea/placement (freeform). Complexity/coverup/timing: post-hoc parsing in `_complete_qualification`; invalid values default (complexity→2, coverup→false).

---

## 3) Test Coverage by Step

| Step | Tests | Negative / Bad-Input Coverage |
|------|-------|-------------------------------|
| dimensions | `test_parser_edge_cases`, `test_phase1_services`, `test_golden_transcript_dimensions_accepts_10x15cm`, `test_bundle_guard` | Partial ("10x", "x12" rejected); weak on "10" alone, "10cm" edge |
| budget | `test_parser_edge_cases`, `test_phase1_services`, `test_edge_cases_comprehensive` | Good: zero, negative, no number, words rejected |
| location_city | `test_location_parsing`, `test_parser_edge_cases` | Good: flexible, empty, too short; weak on postcodes, gibberish cities |
| slot | `test_slot_parsing`, `test_go_live_guardrails`, `test_parser_edge_cases` | Good: out of range, multiple numbers; **weak**: "I have 3 questions" → 3, "Call me at 5" → 5 (false positives) |
| idea/placement | `looks_like_wrong_field_single_answer` in `test_bundle_guard` | Good: budget-only, dimensions-only at wrong step |
| complexity | E2E only; no unit tests for "1"/"2"/"3" vs "not sure" | Weak: no explicit negative tests |
| coverup | E2E only | Weak: no explicit YES/NO validation tests |
| timing | E2E only | Weak: no validation |

**Steps with weak negative coverage**: slot (contextual false positives), dimensions (single "10" without unit), location (postcodes, gibberish), complexity, coverup, timing.

---

## 4) Risk Scoring

| Step | Risk | Rationale |
|------|------|------------|
| **dimensions** | **MED** | Ambiguous: "10" could be width-only; single "10cm" → (10,10) may be wrong. Area affects deposit. |
| **budget** | **MED** | Good guards; "2" from "2 dragons" avoided by bundle guard. Small numbers <£50 need keyword. |
| **location_city** | **MED** | Postcodes, unknown cities accepted. Wrong city → wrong tour/region. |
| **slot** | **HIGH** | "I have 3 questions" → slot 3; "Call me at 5" → slot 5. Wrong slot = wrong booking time. |
| **idea** | LOW | Freeform; wrong-field guard. |
| **placement** | LOW | Same. |
| **style** | LOW | Freeform. |
| **complexity** | LOW | Defaults to 2; affects category but not critical. |
| **coverup** | LOW | Defaults to false. |
| **reference_images** | LOW | Media ack at wrong step. |
| **location_country** | LOW | Freeform. |
| **instagram_handle** | LOW | Optional. |
| **travel_city** | LOW | Freeform. |
| **timing** | LOW | Freeform. |

---

## 5) Two Safety Improvements (Minimal Churn)

### 5.1 Stricter dimension parsing: require explicit unit for single dimension

**Current**: `10cm` → (10, 10). `10` alone → None (no unit).

**Risk**: "10" with "cm" elsewhere in message could match. Pattern `(\d+)\s*(cm|inch|inches|in)` requires unit adjacent.

**Improvement**: For single-dimension match, require the unit to be within 3 characters of the number (no intervening words). Reduces "10 something cm" false positives.

```python
# In parse_dimensions, for single-dim pattern:
# Require: number immediately followed by optional space + unit
# Current: r"(\d+(?:\.\d+)?)\s*(cm|inch|inches|in)"
# Already tight; add: reject if "10" appears but "cm" is many tokens away
```

**Simpler improvement**: Add explicit rejection of dimension-like strings without units when they could be slot numbers: e.g. if message is just "1" or "2" at dimensions step, and it could parse as slot, don't treat as dimensions. (Context-dependent; dimensions step has no slots.) **Alternative**: Add max dimension sanity check — reject (w,h) if either > 200 cm (e.g. "200x300" typo).

**Recommended**: Add sanity bounds: reject dimensions if w or h > 100 cm (likely typo or wrong units).  
**Implemented**: Done in `estimation_service.parse_dimensions`.

### 5.2 Budget minimum threshold

**Current**: `parse_budget_from_text("4")` → 400 pence (£4). Realistic minimum is ~£50.

**Improvement**: Add optional `min_pence` parameter; when used in conversation flow, reject if `budget_pence < 5000` (£50). Prevents "4" or "10" from advancing as budget.

```python
# In conversation.py, when parsing budget:
budget_pence = parse_budget_from_text(message_text)
if budget_pence is not None and budget_pence < 5000:
    budget_pence = None  # Treat as unparseable, trigger repair
```
**Implemented**: Done in `conversation._handle_qualifying_lead` (budget step).

---

## 6) Fuzz / Property-Based Test Plan

### Hypothesis test for highest-risk step: slot

**Goal**: Never advance on ambiguous input.

```python
# tests/test_slot_parsing_fuzz.py
from hypothesis import given, strategies as st

@given(st.text(min_size=1, max_size=100))
def test_slot_never_advances_on_purely_ambiguous(sample_slots, message):
    """Messages with no clear slot intent should return None."""
    # Exclude messages that are valid slot selections
    if re.match(r"^(option|number|slot|choice|#)\s*[1-8]\b", message.lower()):
        return
    if re.match(r"^[1-8]$", message.strip()):
        return
    # "I have X questions", "Call me at X" etc. should ideally be None
    # Current behavior: may match. Document or fix.
    result = parse_slot_selection(message, sample_slots)
    # If message has multiple slot numbers, must be None
    if _has_multiple_slot_numbers(message.lower(), 8):
        assert result is None
```

### Small fuzz corpus for dimensions

```python
# Bad inputs that MUST NOT advance (return None or trigger repair)
BAD_DIMENSIONS = [
    "", "x", "10x", "x12", "ten by twelve", "10 12",  # no unit
    "0x0", "0x12", "10x0",  # zero
    "1", "2", "3",  # slot-like numbers
    "10x12 feet",  # unsupported unit
]
```

### Small fuzz corpus for budget

```python
# Already well-tested; add:
BAD_BUDGET = [
    "four hundred", "ten", "a lot", "whatever",
    "£", "$", "€",  # no number
]
```

---

## Key Findings Summary

| Finding | Detail |
|---------|--------|
| **Parser surface** | 4 main parsers (dimensions, budget, location, slot) + bundle guard + parse_repair |
| **Strict steps** | dimensions, budget, location_city, slot — all have repair → handover |
| **Permissive steps** | idea, placement, style, complexity, coverup, reference_images, timing, etc. — accept any text |
| **Highest risk** | **slot**: "I have 3 questions" → 3, "Call me at 5" → 5 (false positives) |
| **Medium risk** | dimensions (single "10cm" → square), budget (very small amounts), location (postcodes, unknown cities) |
| **Top 2 improvements** | 1) Budget min threshold (£50) in conversation flow; 2) Dimension sanity bounds (reject w,h > 100 cm) |
| **Fuzz focus** | Slot selection: multiple numbers, contextual phrases; dimensions: bad unit/zero/ambiguous |
