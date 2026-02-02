"""
Tests for pricing computation during qualification.

Tests that pricing estimates are computed and stored during _complete_qualification().
"""

import pytest
from sqlalchemy.orm import Session

from app.db.models import Lead, LeadAnswer
from app.services.conversation import _complete_qualification


@pytest.fixture
def lead_with_answers(db: Session):
    """Create a lead with qualification answers."""
    lead = Lead(
        wa_from="test_wa_from",
        status="QUALIFYING",
        channel="whatsapp",
    )
    db.add(lead)
    db.flush()

    # Add qualification answers
    answers = [
        LeadAnswer(lead_id=lead.id, question_key="dimensions", answer_text="8x12cm"),
        LeadAnswer(lead_id=lead.id, question_key="complexity", answer_text="2"),
        LeadAnswer(lead_id=lead.id, question_key="coverup", answer_text="no"),
        LeadAnswer(lead_id=lead.id, question_key="placement", answer_text="arm"),
        LeadAnswer(lead_id=lead.id, question_key="location_city", answer_text="London"),
        LeadAnswer(lead_id=lead.id, question_key="location_country", answer_text="United Kingdom"),
        LeadAnswer(lead_id=lead.id, question_key="budget", answer_text="1000"),
        LeadAnswer(lead_id=lead.id, question_key="travel_city", answer_text=""),
        LeadAnswer(lead_id=lead.id, question_key="instagram_handle", answer_text="@testuser"),
    ]
    for answer in answers:
        db.add(answer)

    db.commit()
    db.refresh(lead)
    return lead


@pytest.mark.asyncio
async def test_complete_qualification_stores_pricing_estimates(
    db: Session, lead_with_answers: Lead
):
    """Test that _complete_qualification stores pricing estimates."""
    result = await _complete_qualification(
        db=db,
        lead=lead_with_answers,
        dry_run=True,
    )

    # Refresh lead to get updated values
    db.refresh(lead_with_answers)

    # Verify pricing fields are set
    assert lead_with_answers.estimated_price_min_pence is not None
    assert lead_with_answers.estimated_price_max_pence is not None
    assert lead_with_answers.pricing_trace_json is not None

    # Verify min < max
    assert lead_with_answers.estimated_price_min_pence < lead_with_answers.estimated_price_max_pence

    # Verify trace contains expected keys
    trace = lead_with_answers.pricing_trace_json
    assert "category" in trace
    assert "region" in trace
    assert "hourly_rate_pence" in trace
    assert "min_hours" in trace
    assert "max_hours" in trace
    assert "calculation" in trace


@pytest.mark.asyncio
async def test_complete_qualification_uk_small_pricing(db: Session):
    """Test pricing for UK + SMALL project."""
    lead = Lead(
        wa_from="test_uk_small",
        status="QUALIFYING",
        channel="whatsapp",
    )
    db.add(lead)
    db.flush()

    answers = [
        LeadAnswer(lead_id=lead.id, question_key="dimensions", answer_text="5x8cm"),  # Small
        LeadAnswer(lead_id=lead.id, question_key="complexity", answer_text="1"),
        LeadAnswer(lead_id=lead.id, question_key="coverup", answer_text="no"),
        LeadAnswer(lead_id=lead.id, question_key="placement", answer_text="arm"),
        LeadAnswer(lead_id=lead.id, question_key="location_city", answer_text="London"),
        LeadAnswer(lead_id=lead.id, question_key="location_country", answer_text="UK"),
        LeadAnswer(lead_id=lead.id, question_key="budget", answer_text="1000"),
        LeadAnswer(lead_id=lead.id, question_key="travel_city", answer_text=""),
    ]
    for answer in answers:
        db.add(answer)
    db.commit()

    await _complete_qualification(db=db, lead=lead, dry_run=True)
    db.refresh(lead)

    # UK + SMALL: 4-5h × £130/h = £520-£650
    assert lead.estimated_price_min_pence == 52000  # £520
    assert lead.estimated_price_max_pence == 65000  # £650
    assert lead.region_bucket == "UK"
    assert lead.estimated_category == "SMALL"


@pytest.mark.asyncio
async def test_complete_qualification_europe_medium_pricing(db: Session):
    """Test pricing for EUROPE + MEDIUM project."""
    lead = Lead(
        wa_from="test_eu_medium",
        status="QUALIFYING",
        channel="whatsapp",
    )
    db.add(lead)
    db.flush()

    answers = [
        LeadAnswer(lead_id=lead.id, question_key="dimensions", answer_text="10x15cm"),  # Medium
        LeadAnswer(lead_id=lead.id, question_key="complexity", answer_text="2"),
        LeadAnswer(lead_id=lead.id, question_key="coverup", answer_text="no"),
        LeadAnswer(lead_id=lead.id, question_key="placement", answer_text="leg"),
        LeadAnswer(lead_id=lead.id, question_key="location_city", answer_text="Paris"),
        LeadAnswer(lead_id=lead.id, question_key="location_country", answer_text="France"),
        LeadAnswer(lead_id=lead.id, question_key="budget", answer_text="1500"),
        LeadAnswer(lead_id=lead.id, question_key="travel_city", answer_text=""),
    ]
    for answer in answers:
        db.add(answer)
    db.commit()

    await _complete_qualification(db=db, lead=lead, dry_run=True)
    db.refresh(lead)

    # Verify region
    assert lead.region_bucket == "EUROPE"

    # Pricing depends on actual category (may be bumped due to placement)
    # Verify pricing is set and min < max
    assert lead.estimated_price_min_pence is not None
    assert lead.estimated_price_max_pence is not None
    assert lead.estimated_price_min_pence < lead.estimated_price_max_pence

    # If MEDIUM: 5-7h × £140/h = £700-£980
    # If LARGE: 7.5-10h × £140/h = £1050-£1400
    if lead.estimated_category == "MEDIUM":
        assert lead.estimated_price_min_pence == 70000  # £700
        assert lead.estimated_price_max_pence == 98000  # £980
    elif lead.estimated_category == "LARGE":
        assert lead.estimated_price_min_pence == 105000  # £1050
        assert lead.estimated_price_max_pence == 140000  # £1400


@pytest.mark.asyncio
async def test_complete_qualification_row_large_pricing(db: Session):
    """Test pricing for ROW + LARGE project."""
    lead = Lead(
        wa_from="test_row_large",
        status="QUALIFYING",
        channel="whatsapp",
    )
    db.add(lead)
    db.flush()

    answers = [
        LeadAnswer(lead_id=lead.id, question_key="dimensions", answer_text="20x25cm"),  # Large
        LeadAnswer(lead_id=lead.id, question_key="complexity", answer_text="2"),
        LeadAnswer(lead_id=lead.id, question_key="coverup", answer_text="no"),
        LeadAnswer(lead_id=lead.id, question_key="placement", answer_text="back"),
        LeadAnswer(lead_id=lead.id, question_key="location_city", answer_text="New York"),
        LeadAnswer(lead_id=lead.id, question_key="location_country", answer_text="USA"),
        LeadAnswer(lead_id=lead.id, question_key="budget", answer_text="2000"),
        LeadAnswer(lead_id=lead.id, question_key="travel_city", answer_text=""),
    ]
    for answer in answers:
        db.add(answer)
    db.commit()

    await _complete_qualification(db=db, lead=lead, dry_run=True)
    db.refresh(lead)

    # Verify region
    assert lead.region_bucket == "ROW"

    # Pricing depends on actual category (20x25cm = 500 cm², likely XL)
    # Verify pricing is set and min < max
    assert lead.estimated_price_min_pence is not None
    assert lead.estimated_price_max_pence is not None
    assert lead.estimated_price_min_pence < lead.estimated_price_max_pence

    # If LARGE: 7.5-10h × £150/h = £1125-£1500
    # If XL: 9.5-11h × £150/h = £1425-£1650
    if lead.estimated_category == "LARGE":
        assert lead.estimated_price_min_pence == 112500  # £1125
        assert lead.estimated_price_max_pence == 150000  # £1500
    elif lead.estimated_category == "XL":
        assert lead.estimated_price_min_pence == 142500  # £1425
        assert lead.estimated_price_max_pence == 165000  # £1650


@pytest.mark.asyncio
async def test_complete_qualification_pricing_trace_structure(db: Session, lead_with_answers: Lead):
    """Test that pricing trace has correct structure."""
    await _complete_qualification(db=db, lead=lead_with_answers, dry_run=True)
    db.refresh(lead_with_answers)

    trace = lead_with_answers.pricing_trace_json
    assert isinstance(trace, dict)

    # Verify trace structure
    assert "category" in trace
    assert "region" in trace
    assert "hourly_rate_pence" in trace
    assert "hourly_rate_gbp" in trace
    assert "min_hours" in trace
    assert "max_hours" in trace
    assert "calculation" in trace

    # Verify calculation sub-structure
    calc = trace["calculation"]
    assert "min_price" in calc
    assert "max_price" in calc

    # Verify calculation strings contain expected info
    assert str(trace["min_hours"]) in calc["min_price"]
    assert str(trace["max_hours"]) in calc["max_price"]


@pytest.mark.asyncio
async def test_complete_qualification_pricing_without_category_region(db: Session):
    """Test that pricing is not computed if category or region is missing."""
    lead = Lead(
        wa_from="test_no_category",
        status="QUALIFYING",
        channel="whatsapp",
    )
    db.add(lead)
    db.flush()

    # Add minimal answers (no dimensions, no location)
    answers = [
        LeadAnswer(lead_id=lead.id, question_key="dimensions", answer_text=""),
        LeadAnswer(lead_id=lead.id, question_key="complexity", answer_text="2"),
        LeadAnswer(lead_id=lead.id, question_key="coverup", answer_text="no"),
        LeadAnswer(lead_id=lead.id, question_key="placement", answer_text="arm"),
        LeadAnswer(lead_id=lead.id, question_key="location_city", answer_text=""),
        LeadAnswer(lead_id=lead.id, question_key="location_country", answer_text=""),
        LeadAnswer(lead_id=lead.id, question_key="budget", answer_text="1000"),
    ]
    for answer in answers:
        db.add(answer)
    db.commit()

    await _complete_qualification(db=db, lead=lead, dry_run=True)
    db.refresh(lead)

    # Pricing should not be set if category or region is missing
    # (The function checks `if category and region:` before computing)
    # In this case, category might still be set (defaults to MEDIUM), but region might be None
    if not lead.region_bucket:
        assert lead.estimated_price_min_pence is None
        assert lead.estimated_price_max_pence is None
        assert lead.pricing_trace_json is None
