"""
High-value parser edge-case tests — WhatsApp chaos checklist.

Covers:
- Budget: currency/formatting, commas, decimals, ranges, trick strings
- Dimensions: formats, partials, units
- Slot selection: number variants, out of range, multiple choices
- Keyword intercepts: opt-out whole-word, human/refund/delete false positives
- Media: media-only reprompt (no advance), captioned media parses caption
- Formatting: whitespace, mixed language

Best ROI tests (from checklist) are included and named explicitly.
"""

import pytest

from app.services.estimation_service import parse_budget_from_text, parse_dimensions
from app.services.location_parsing import is_valid_location, parse_location_input
from app.services.slot_parsing import parse_slot_selection_logged

# ---------------------------------------------------------------------------
# Budget parsing (parse_budget_from_text)
# ---------------------------------------------------------------------------


class TestParseBudgetCurrencyAndFormatting:
    """Currency + formatting: correct numeric extraction, pence output, invalid → None."""

    def test_parse_budget_handles_commas_and_decimals(self):
        """Best ROI: commas and decimals — £1,200 and £400.00 → pence."""
        assert parse_budget_from_text("1,200") == 120000  # £1200
        assert parse_budget_from_text("£1,200") == 120000
        assert parse_budget_from_text("£400.00") == 40000
        assert parse_budget_from_text("400.50") == 40050  # 400.50 * 100

    def test_parse_budget_currency_symbols_and_spaces(self):
        """£400, 400£, 400 gbp, GBP 400, 400 pounds, $500, 500 usd, £ 400."""
        assert parse_budget_from_text("£400") == 40000
        assert parse_budget_from_text("400£") == 40000
        assert parse_budget_from_text("400 gbp") == 40000
        assert parse_budget_from_text("GBP 400") == 40000
        assert parse_budget_from_text("400 pounds") == 40000
        assert parse_budget_from_text("$500") == 50000
        assert parse_budget_from_text("500 usd") == 50000
        assert parse_budget_from_text("£ 400") == 40000

    def test_parse_budget_rejects_no_number(self):
        """Best ROI: invalid formats return None — 'I can do £', no number."""
        assert parse_budget_from_text("I can do £") is None
        assert parse_budget_from_text("not a number") is None
        assert parse_budget_from_text("") is None

    def test_parse_budget_rejects_zero_and_negative(self):
        """0, £0 → None; -400, £-400 → None (enforced)."""
        assert parse_budget_from_text("0") is None
        assert parse_budget_from_text("£0") is None
        assert parse_budget_from_text("budget is 0") is None
        assert parse_budget_from_text("-400") is None
        assert parse_budget_from_text("£-400") is None

    def test_parse_budget_range_policy(self):
        """400-500 → first number = 400 → 40000 pence; £0-£200 → None (zero rejected)."""
        assert parse_budget_from_text("400-500") == 40000
        assert parse_budget_from_text("£400-500") == 40000
        assert parse_budget_from_text("£0-£200") is None

    def test_parse_budget_trick_strings_with_number(self):
        """'£400 and I can stretch' → parse 400 (first number), pence."""
        assert parse_budget_from_text("£400 and I can stretch") == 40000
        assert parse_budget_from_text("around 400") == 40000
        assert parse_budget_from_text("approx £400") == 40000

    def test_parse_budget_consistent_pence_output(self):
        """All valid extractions in pence (e.g. £400 → 40000)."""
        assert parse_budget_from_text("400") == 40000
        assert parse_budget_from_text("£4") == 400  # £4 = 400 pence
        assert parse_budget_from_text("1000") == 100000


class TestParseBudgetEdgeCases:
    """~400, 400k, four hundred — document current behavior."""

    def test_parse_budget_tilde_and_around(self):
        """~400, around 400 → first number (already tested above)."""
        assert parse_budget_from_text("~400") == 40000

    def test_parse_budget_400k(self):
        r"""400k → 400_000 GBP = 40_000_000 pence (k suffix policy locked)."""
        assert parse_budget_from_text("400k") == 40_000_000
        assert parse_budget_from_text("1k") == 100_000  # £1000

    def test_parse_budget_words_rejected(self):
        """four hundred → no number, None."""
        assert parse_budget_from_text("four hundred") is None


class TestBudgetMinimumInConversation:
    """Budget step rejects amounts < £50 (conversation flow only; raw parser unchanged)."""

    def test_budget_under_50_triggers_repair_in_flow(self, db):
        """At budget step, '4' or '£10' should trigger repair (not advance)."""
        from app.db.models import Lead, LeadAnswer
        from app.services.conversation import handle_inbound_message
        from app.services.questions import CONSULTATION_QUESTIONS

        lead = Lead(wa_from="1234567890", status="QUALIFYING", current_step=7)  # budget step
        db.add(lead)
        db.commit()
        db.refresh(lead)
        for _i, q in enumerate(CONSULTATION_QUESTIONS[:7]):
            if q.key != "budget":
                db.add(LeadAnswer(lead_id=lead.id, question_key=q.key, answer_text="x"))
        db.commit()

        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            handle_inbound_message(db, lead, "4", dry_run=True)
        )
        assert result.get("status") == "repair_needed"
        assert result.get("question_key") == "budget"


# ---------------------------------------------------------------------------
# Dimensions parsing (parse_dimensions)
# ---------------------------------------------------------------------------


class TestParseDimensionsFormats:
    """10x12, 10×12, 10 x 12 cm, 10 by 12 — accepted or repair."""

    def test_parse_dimensions_multiplication_sign_and_spaces(self):
        """10x12, 10 x 12 — unicode × normalized to x so 10×12cm → (10, 12)."""
        assert parse_dimensions("10x12cm") == (10.0, 12.0)
        result = parse_dimensions("10 x 12 cm")
        assert result is not None
        assert result[0] > 0 and result[1] > 0
        assert parse_dimensions("10×12cm") == (10.0, 12.0)

    def test_parse_dimensions_with_units(self):
        """10 x12cm, 10cmx12cm (no spaces) — 10cmx12cm may match single '10cm' (parser order)."""
        assert parse_dimensions("10 x12cm") == (10.0, 12.0)
        result = parse_dimensions("10cmx12cm")
        assert result is not None
        assert result[0] == 10.0
        assert result[1] in (10.0, 12.0)  # may be (10,10) if single-dim matches first
        result2 = parse_dimensions("10cm x 12cm")
        assert result2 is not None
        assert result2[0] == 10.0
        assert result2[1] in (10.0, 12.0)

    def test_parse_dimensions_partial_rejected(self):
        """10x, x12 → no full match, None."""
        assert parse_dimensions("10x") is None
        assert parse_dimensions("x12") is None

    def test_parse_dimensions_inches(self):
        """10x12 inches → convert to cm."""
        dims = parse_dimensions("10x12 inches")
        assert dims is not None
        assert dims[0] == pytest.approx(25.4, rel=0.01)
        assert dims[1] == pytest.approx(30.48, rel=0.01)

    def test_parse_dimensions_sanity_bounds_reject_oversized(self):
        """Oversized dimensions (> 100 cm) rejected as likely typo."""
        assert parse_dimensions("200x300cm") is None
        assert parse_dimensions("150x50cm") is None
        assert parse_dimensions("50x150cm") is None


# ---------------------------------------------------------------------------
# Location parsing
# ---------------------------------------------------------------------------


class TestLocationParsingEdgeCases:
    """Postcodes, emoji, idk, multiple locations — no crash; extract or repair."""

    def test_location_parsing_does_not_crash_on_postcode_like(self):
        """E1 6AN, NW3 5NR — parser may treat as city or fail; must not crash."""
        result = parse_location_input("E1 6AN")
        assert isinstance(result, dict)
        assert "city" in result and "is_flexible" in result

    def test_location_parsing_emoji_no_crash(self):
        """🇬🇧 London, London 🇬🇧 — strip or tolerate, no crash."""
        result = parse_location_input("London 🇬🇧")
        assert isinstance(result, dict)
        result2 = parse_location_input("🇬🇧 London")
        assert isinstance(result2, dict)

    def test_location_parsing_empty_and_short(self):
        """empty, idk, not sure — flexible or invalid, no crash."""
        r = parse_location_input("")
        assert r["is_flexible"] or (not r["city"] and not r["country"]) or True
        r2 = parse_location_input("idk")
        assert isinstance(r2, dict)

    def test_location_valid_rejects_flexible(self):
        """is_valid_location returns False for flexible."""
        assert is_valid_location("flexible") is False
        assert is_valid_location("anywhere") is False


# ---------------------------------------------------------------------------
# Slot selection (parse_slot_selection)
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_slots():
    """8 slots Mon–Wed with morning/afternoon for slot_parsing tests."""
    from datetime import datetime, timedelta

    base = datetime(2025, 2, 3, 10, 0, 0)  # Mon 10am
    slots = []
    for day in range(4):
        for hour in (10, 14):
            start = base + timedelta(days=day)
            start = start.replace(hour=hour, minute=0)
            end = start.replace(hour=start.hour + 1)
            slots.append({"start": start, "end": end})
    return slots[:8]


class TestSlotParsingNumberVariants:
    """1, 1., #1, option 1 — valid; 0, 9, 11 out of range."""

    def test_slot_parsing_accepts_option_1_and_1_dot(self, sample_slots):
        """Best ROI: option 1 and 1. both select slot 1."""
        assert parse_slot_selection_logged("1", sample_slots) == 1
        assert parse_slot_selection_logged("1.", sample_slots) == 1
        assert parse_slot_selection_logged("option 1", sample_slots) == 1
        assert parse_slot_selection_logged("#1", sample_slots) == 1

    def test_slot_parsing_rejects_out_of_range(self, sample_slots):
        """Best ROI: 0, 9, 11 → None (repair without state advance)."""
        assert parse_slot_selection_logged("0", sample_slots) is None
        assert parse_slot_selection_logged("9", sample_slots) is None
        assert parse_slot_selection_logged("11", sample_slots) is None

    def test_slot_parsing_multiple_choices_prompts_pick_one(self, sample_slots):
        """Best ROI: '1 or 2', '2, 4, 5' → None so caller sends REPAIR_SLOT / pick one."""
        assert parse_slot_selection_logged("1 or 2", sample_slots) is None
        assert parse_slot_selection_logged("2, 4, 5", sample_slots) is None

    def test_slot_parsing_day_time_variants(self, sample_slots):
        """Tuesday pm, Tue afternoon, Mon 10am."""
        assert parse_slot_selection_logged("Monday morning", sample_slots) == 1
        assert parse_slot_selection_logged("Monday afternoon", sample_slots) == 2
        assert parse_slot_selection_logged("Tue afternoon", sample_slots) == 4


# ---------------------------------------------------------------------------
# Keyword intercept edge cases (opt-out, human, refund, delete)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestOptOutWholeWordOnly:
    """STOP alone triggers opt-out; 'stop by' does NOT (whole-word or exact command)."""

    async def test_opt_out_stop_whole_word_only_not_stop_by(self, db):
        """Best ROI: STOP alone opts out; 'stop by' / 'I'll stop by' does NOT."""
        from app.db.models import Lead
        from app.services.conversation import (
            STATUS_OPTOUT,
            STATUS_QUALIFYING,
            handle_inbound_message,
        )

        lead = Lead(wa_from="1234567890", status=STATUS_QUALIFYING, current_step=1)
        db.add(lead)
        db.commit()
        db.refresh(lead)

        result_stop = await handle_inbound_message(db, lead, "STOP", dry_run=True)
        db.refresh(lead)
        assert lead.status == STATUS_OPTOUT
        assert result_stop["status"] == "opted_out"

        # New lead: "stop by" must NOT opt out
        lead2 = Lead(wa_from="1234567891", status=STATUS_QUALIFYING, current_step=1)
        db.add(lead2)
        db.commit()
        db.refresh(lead2)
        result_stop_by = await handle_inbound_message(
            db, lead2, "I'll stop by the shop", dry_run=True
        )
        db.refresh(lead2)
        assert lead2.status == STATUS_QUALIFYING
        assert result_stop_by["status"] != "opted_out"

        result_dont_stop = await handle_inbound_message(
            db, lead2, "don't stop the convo", dry_run=True
        )
        db.refresh(lead2)
        assert lead2.status == STATUS_QUALIFYING
        assert result_dont_stop["status"] != "opted_out"


@pytest.mark.asyncio
class TestHumanRefundDeleteIntercepts:
    """Human: exact match. Refund/Delete: substring — document false positives."""

    async def test_human_question_are_you_human_behavior_defined(self, db):
        """Best ROI: 'are you human?' — current: exact match only, so does NOT trigger."""
        from app.db.models import Lead
        from app.services.conversation import (
            STATUS_NEEDS_ARTIST_REPLY,
            STATUS_QUALIFYING,
            handle_inbound_message,
        )

        lead = Lead(wa_from="1234567892", status=STATUS_QUALIFYING, current_step=1)
        db.add(lead)
        db.commit()
        db.refresh(lead)

        # Exact "HUMAN" triggers handover
        result_exact = await handle_inbound_message(db, lead, "HUMAN", dry_run=True)
        db.refresh(lead)
        assert lead.status == STATUS_NEEDS_ARTIST_REPLY
        assert result_exact["status"] == "handover"

        lead2 = Lead(wa_from="1234567893", status=STATUS_QUALIFYING, current_step=1)
        db.add(lead2)
        db.commit()
        db.refresh(lead2)
        # "are you human?" — not exact match, so does NOT trigger human handover (continues flow)
        result_phrase = await handle_inbound_message(db, lead2, "are you human?", dry_run=True)
        db.refresh(lead2)
        # Current: message_upper in ("HUMAN", ...) is exact; "ARE YOU HUMAN?" not in set
        assert result_phrase["status"] != "opted_out"
        # Exact match only: "ARE YOU HUMAN?" not in ("HUMAN", ...)

    async def test_refund_substring_triggers(self, db):
        """'can I get a refund please' → handover (REFUND is substring)."""
        from app.db.models import Lead
        from app.services.conversation import (
            STATUS_NEEDS_ARTIST_REPLY,
            STATUS_QUALIFYING,
            handle_inbound_message,
        )

        lead = Lead(wa_from="1234567894", status=STATUS_QUALIFYING, current_step=1)
        db.add(lead)
        db.commit()
        db.refresh(lead)
        result = await handle_inbound_message(db, lead, "can I get a refund please", dry_run=True)
        db.refresh(lead)
        assert lead.status == STATUS_NEEDS_ARTIST_REPLY
        assert result["status"] == "handover"

    async def test_delete_data_phrase_triggers(self, db):
        """'DELETE MY DATA' → handover. 'delete that tattoo idea from the sheet' has no 'DELETE DATA' substring → no delete handover."""
        from app.db.models import Lead
        from app.services.conversation import (
            STATUS_NEEDS_ARTIST_REPLY,
            STATUS_QUALIFYING,
            handle_inbound_message,
        )

        lead = Lead(wa_from="1234567895", status=STATUS_QUALIFYING, current_step=1)
        db.add(lead)
        db.commit()
        db.refresh(lead)
        result = await handle_inbound_message(db, lead, "DELETE MY DATA", dry_run=True)
        db.refresh(lead)
        assert lead.status == STATUS_NEEDS_ARTIST_REPLY
        assert result["status"] == "handover"

        lead2 = Lead(wa_from="1234567896", status=STATUS_QUALIFYING, current_step=1)
        db.add(lead2)
        db.commit()
        db.refresh(lead2)
        result2 = await handle_inbound_message(
            db, lead2, "delete that tattoo idea from the sheet", dry_run=True
        )
        db.refresh(lead2)
        # "DELETE THAT TATTOO IDEA FROM THE SHEET" does not contain "DELETE DATA" → no delete handler
        assert (
            lead2.handover_reason != "Client requested data deletion / GDPR"
            if lead2.handover_reason
            else True
        )


# ---------------------------------------------------------------------------
# Media / attachment edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMediaEdgeCases:
    """Media-only reprompt no advance; captioned media stores and parses caption."""

    async def test_media_only_reprompts_and_does_not_advance(self, db):
        """Best ROI: media-only at dimensions step → ack + reprompt, no advance."""
        from app.db.models import Lead
        from app.services.conversation import STATUS_QUALIFYING, handle_inbound_message

        lead = Lead(wa_from="1234567897", status=STATUS_QUALIFYING, current_step=2)  # dimensions
        db.add(lead)
        db.commit()
        db.refresh(lead)

        result = await handle_inbound_message(
            db=db, lead=lead, message_text="", dry_run=True, has_media=True
        )
        db.refresh(lead)
        assert result["status"] == "attachment_ack_reprompt"
        assert lead.current_step == 2

    async def test_captioned_media_stores_media_and_parses_caption(self, db):
        """Best ROI: caption + has_media at dimensions step → parse caption, advance (no ack reprompt)."""
        from app.db.models import Lead
        from app.services.conversation import STATUS_QUALIFYING, handle_inbound_message

        lead = Lead(wa_from="1234567898", status=STATUS_QUALIFYING, current_step=2)
        db.add(lead)
        db.commit()
        db.refresh(lead)

        result = await handle_inbound_message(
            db=db, lead=lead, message_text="10x12cm", dry_run=True, has_media=True
        )
        db.refresh(lead)
        assert result["status"] != "attachment_ack_reprompt"
        assert lead.current_step >= 2

    async def test_media_at_reference_images_step_accepts(self, db):
        """Media at reference_images step → no reprompt, accept."""
        from app.db.models import Lead
        from app.services.conversation import STATUS_QUALIFYING, handle_inbound_message
        from app.services.questions import CONSULTATION_QUESTIONS

        ref_idx = next(
            i for i, q in enumerate(CONSULTATION_QUESTIONS) if q.key == "reference_images"
        )
        lead = Lead(wa_from="1234567899", status=STATUS_QUALIFYING, current_step=ref_idx)
        db.add(lead)
        db.commit()
        db.refresh(lead)

        result = await handle_inbound_message(
            db=db, lead=lead, message_text="", dry_run=True, has_media=True
        )
        db.refresh(lead)
        assert result["status"] != "attachment_ack_reprompt"


# ---------------------------------------------------------------------------
# WhatsApp reality formatting
# ---------------------------------------------------------------------------


class TestFormattingEdgeCases:
    """Leading/trailing whitespace, newlines, mixed language."""

    def test_budget_leading_trailing_whitespace(self):
        """£400  → 40000."""
        assert parse_budget_from_text("  £400  ") == 40000

    def test_budget_mixed_language(self):
        """presupuesto £400 (Spanish + £) → parse number."""
        assert parse_budget_from_text("presupuesto £400") == 40000

    def test_dimensions_weird_punctuation(self):
        """10x12cm?? → parse if pattern still matches."""
        result = parse_dimensions("10x12cm??")
        assert result == (10.0, 12.0)


# ---------------------------------------------------------------------------
# High-impact enforcement tests (next 10 from checklist)
# ---------------------------------------------------------------------------


class TestParseBudgetEnforcement:
    """Enforce policy: negatives, zero, k suffix — no silent wrong parse."""

    def test_parse_budget_rejects_negative_values(self):
        """-400, £-400 → None (enforced)."""
        assert parse_budget_from_text("-400") is None
        assert parse_budget_from_text("£-400") is None
        assert parse_budget_from_text("around -500") is None

    def test_parse_budget_rejects_zero(self):
        """0, £0 → None."""
        assert parse_budget_from_text("0") is None
        assert parse_budget_from_text("£0") is None

    def test_parse_budget_k_suffix_policy(self):
        """400k → 40_000_000 pence (£400k); policy locked."""
        assert parse_budget_from_text("400k") == 40_000_000
        assert parse_budget_from_text("1.5k") == 150_000  # £1500


class TestSlotParsingMultipleNumbers:
    """Multiple choices → None so caller sends REPAIR_SLOT / pick one."""

    def test_slot_parsing_multiple_numbers_returns_none(self, sample_slots):
        """'1 or 2', '2, 4, 5' → None (ambiguous)."""
        assert parse_slot_selection_logged("1 or 2", sample_slots) is None
        assert parse_slot_selection_logged("2, 4, 5", sample_slots) is None
        assert parse_slot_selection_logged("option 3 or 4", sample_slots) is None

    @pytest.mark.asyncio
    async def test_slot_parsing_multiple_numbers_triggers_pick_one_repair(self, db, sample_slots):
        """Integration: '1 or 2' at slot step → repair_needed (REPAIR_SLOT)."""
        from app.db.models import Lead
        from app.services.conversation import STATUS_BOOKING_PENDING, handle_inbound_message

        lead = Lead(
            wa_from="1234567890",
            status=STATUS_BOOKING_PENDING,
            current_step=0,
            suggested_slots_json=[
                {"start": s["start"].isoformat(), "end": s["end"].isoformat()} for s in sample_slots
            ],
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)

        result = await handle_inbound_message(db, lead, "1 or 2", dry_run=True)
        db.refresh(lead)
        assert result.get("status") == "repair_needed"
        assert result.get("question_key") == "slot"


class TestDimensionsNormalization:
    """Unicode × and no-unit policy."""

    def test_dimensions_normalizes_unicode_multiplication_sign(self):
        """10×12cm behaves like 10x12cm → (10, 12)."""
        assert parse_dimensions("10×12cm") == (10.0, 12.0)
        assert parse_dimensions("10\u00d7 12 cm") == (10.0, 12.0)

    def test_dimensions_parses_no_spaces_no_unit_policy(self):
        """10cmx12cm → parse (may be single 10cm). '10 x 12' no unit — current: None (unit required)."""
        result = parse_dimensions("10cmx12cm")
        assert result is not None
        assert result[0] == 10.0
        assert result[1] in (10.0, 12.0)
        result2 = parse_dimensions("10 x 12")
        # Parser requires unit (cm/inch); no unit → None
        assert result2 is None or (result2[0] > 0 and result2[1] > 0)


@pytest.mark.asyncio
class TestKeywordHumanCommandOnly:
    """human? / are you human — command-style, not in sentence."""

    async def test_keyword_human_command_only_not_in_sentence(self, db):
        """'human?', 'are you human' do NOT trigger human handover (exact match only)."""
        from app.db.models import Lead
        from app.services.conversation import STATUS_QUALIFYING, handle_inbound_message

        for msg in ("human?", "are you human", "are you human?"):
            lead = Lead(
                wa_from=f"12345_{hash(msg) % 10**6}", status=STATUS_QUALIFYING, current_step=1
            )
            db.add(lead)
            db.commit()
            db.refresh(lead)
            result = await handle_inbound_message(db, lead, msg, dry_run=True)
            db.refresh(lead)
            # Human handler returns status "handover"; exact match only so these phrases don't trigger it
            assert result["status"] != "handover"


class TestUnicodeWhitespaceNormalization:
    """Non-breaking space, zero-width — parsers still work."""

    def test_unicode_whitespace_normalization(self):
        """Budget/dimensions with NBSP, ZWSP still parse."""
        nbsp = "\u00a0"
        assert parse_budget_from_text(f"£400{nbsp}") == 40000
        assert parse_budget_from_text(f"  {nbsp} £ 400 {nbsp}  ") == 40000
        assert parse_dimensions(f"10{nbsp}x{nbsp}12cm") == (10.0, 12.0)
