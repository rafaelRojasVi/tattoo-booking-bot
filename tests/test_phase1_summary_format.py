"""
Test Phase 1 summary formatting.
"""

from app.db.models import Lead, LeadAnswer
from app.services.summary import (
    extract_phase1_summary_context,
    format_summary_message,
)


def test_extract_phase1_summary_context_basic(db):
    """Test extracting summary context from a basic lead."""
    lead = Lead(
        id=42,
        wa_from="1234567890",
        status="PENDING_APPROVAL",
        complexity_level=2,
        estimated_category="MEDIUM",
        estimated_deposit_amount=15000,
        location_city="London",
        location_country="UK",
        region_bucket="UK",
        min_budget_amount=40000,
        below_min_budget=False,
        instagram_handle="@testuser",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Add answers
    for key, value in [
        ("idea", "A dragon tattoo"),
        ("placement", "Left arm"),
        ("dimensions", "10x15cm"),
        ("budget", "£500"),
    ]:
        answer = LeadAnswer(lead_id=lead.id, question_key=key, answer_text=value)
        db.add(answer)
    db.commit()
    db.refresh(lead)

    ctx = extract_phase1_summary_context(lead)

    assert ctx["lead_id"] == 42
    assert ctx["idea"] == "A dragon tattoo"
    assert ctx["placement"] == "Left arm"
    assert ctx["dimensions"] == "10x15cm"
    assert ctx["complexity"] == "Medium"
    assert ctx["estimated_category"] == "MEDIUM"
    assert ctx["deposit_gbp"] == 150.0
    assert ctx["budget_amount"] == 50000  # £500 = 50000 pence
    assert ctx["budget_display"] == "£500 (Min: £400)"
    assert ctx["below_min_budget"] is False
    assert ctx["instagram_handle"] == "@testuser"


def test_extract_phase1_summary_context_below_min_budget(db):
    """Test context extraction when budget is below minimum."""
    lead = Lead(
        id=43,
        wa_from="1234567890",
        status="PENDING_APPROVAL",
        location_country="UK",
        region_bucket="UK",
        min_budget_amount=40000,
        below_min_budget=True,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    answer = LeadAnswer(lead_id=lead.id, question_key="budget", answer_text="£300")
    db.add(answer)
    db.commit()
    db.refresh(lead)

    ctx = extract_phase1_summary_context(lead)

    assert ctx["below_min_budget"] is True
    assert "BELOW MIN" in ctx["budget_display"] or "⚠️" in ctx["budget_display"]


def test_extract_phase1_summary_context_tour_waitlisted(db):
    """Test context extraction for waitlisted lead."""
    lead = Lead(
        id=44,
        wa_from="1234567890",
        status="WAITLISTED",
        requested_city="Manchester",
        waitlisted=True,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    ctx = extract_phase1_summary_context(lead)

    assert "Waitlisted" in ctx["tour_status"]
    assert "Manchester" in ctx["tour_status"]


def test_extract_phase1_summary_context_tour_conversion_offered(db):
    """Test context extraction for tour conversion offered."""
    lead = Lead(
        id=45,
        wa_from="1234567890",
        status="TOUR_CONVERSION_OFFERED",
        requested_city="Manchester",
        offered_tour_city="London",
        offered_tour_dates_text="March 15-20, 2026",
        tour_offer_accepted=False,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    ctx = extract_phase1_summary_context(lead)

    assert "Tour conversion offered" in ctx["tour_status"]
    assert "London" in ctx["tour_status"]


def test_format_summary_message_includes_all_key_fields(db):
    """Test that formatted summary includes all key Phase 1 fields."""
    lead = Lead(
        id=46,
        wa_from="1234567890",
        status="PENDING_APPROVAL",
        complexity_level=2,
        estimated_category="MEDIUM",
        estimated_deposit_amount=15000,
        location_city="London",
        location_country="UK",
        region_bucket="UK",
        min_budget_amount=40000,
        below_min_budget=False,
        instagram_handle="@testuser",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Add answers
    for key, value in [
        ("idea", "A dragon tattoo"),
        ("placement", "Left arm"),
        ("dimensions", "10x15cm"),
        ("budget", "£500"),
    ]:
        answer = LeadAnswer(lead_id=lead.id, question_key=key, answer_text=value)
        db.add(answer)
    db.commit()
    db.refresh(lead)

    ctx = extract_phase1_summary_context(lead)
    message = format_summary_message(ctx)

    assert "Lead #46" in message
    assert "A dragon tattoo" in message
    assert "Left arm" in message
    assert "10x15cm" in message
    assert "London" in message
    assert "UK" in message
    assert "£500" in message
    assert "@testuser" in message
    assert "MEDIUM" in message or "Medium" in message
    assert "£150" in message  # Deposit


def test_format_summary_message_handles_missing_fields(db):
    """Test that summary formatting handles missing fields gracefully."""
    lead = Lead(
        id=47,
        wa_from="1234567890",
        status="PENDING_APPROVAL",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # No answers added

    ctx = extract_phase1_summary_context(lead)
    message = format_summary_message(ctx)

    # Should not crash, should still show lead ID
    assert "Lead #47" in message
    # Should not have KeyErrors or "None None" strings
    assert "None None" not in message


def test_format_summary_message_shows_below_min_budget_flag(db):
    """Test that below minimum budget is clearly flagged."""
    lead = Lead(
        id=48,
        wa_from="1234567890",
        status="PENDING_APPROVAL",
        min_budget_amount=40000,
        below_min_budget=True,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    answer = LeadAnswer(lead_id=lead.id, question_key="budget", answer_text="£300")
    db.add(answer)
    db.commit()
    db.refresh(lead)

    ctx = extract_phase1_summary_context(lead)
    message = format_summary_message(ctx)

    assert "BELOW MIN" in message or "⚠️" in message or "Below minimum" in message.lower()


def test_format_summary_message_shows_handover_reason(db):
    """Test that handover reason is included in notes."""
    lead = Lead(
        id=49,
        wa_from="1234567890",
        status="PENDING_APPROVAL",
        handover_reason="Complex coverup",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    ctx = extract_phase1_summary_context(lead)
    message = format_summary_message(ctx)

    assert "Complex coverup" in message
    assert "Handover" in message or "Notes" in message


def test_format_summary_message_shows_coverup_flag(db):
    """Test that coverup flag is shown in notes."""
    lead = Lead(
        id=50,
        wa_from="1234567890",
        status="PENDING_APPROVAL",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    answer = LeadAnswer(lead_id=lead.id, question_key="coverup", answer_text="Yes")
    db.add(answer)
    db.commit()
    db.refresh(lead)

    ctx = extract_phase1_summary_context(lead)
    message = format_summary_message(ctx)

    assert "Cover-up" in message or "coverup" in message.lower()
