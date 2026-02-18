"""
Tests for new database fields added in v1.4 proposal alignment.
"""

import pytest

from app.db.models import Lead, LeadAnswer, ProcessedMessage


def test_lead_new_fields_are_nullable(db):
    """Test that new Lead fields are nullable (backward compatibility)."""
    lead = Lead(wa_from="1234567890", status="NEW")
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # All new fields should be None by default
    assert lead.location_city is None
    assert lead.location_country is None
    assert lead.region_bucket is None
    assert lead.size_category is None
    assert lead.size_measurement is None
    assert lead.budget_range_text is None
    assert lead.summary_text is None
    assert lead.deposit_amount_pence is None
    assert lead.stripe_checkout_session_id is None
    assert lead.booking_link is None
    assert lead.last_client_message_at is None
    assert lead.last_bot_message_at is None
    assert lead.approved_at is None
    assert lead.rejected_at is None


def test_lead_can_set_new_fields(db):
    """Test that new Lead fields can be set."""
    lead = Lead(
        wa_from="1234567890",
        status="PENDING_APPROVAL",
        location_city="London",
        location_country="United Kingdom",
        region_bucket="UK",
        size_category="MEDIUM",
        size_measurement="15cm x 10cm",
        budget_range_text="£200-400",
        summary_text="Test summary",
        deposit_amount_pence=5000,
        stripe_checkout_session_id="cs_test_123",
        booking_link="https://fresha.com/book/123",
        booking_tool="FRESHA",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    assert lead.location_city == "London"
    assert lead.location_country == "United Kingdom"
    assert lead.region_bucket == "UK"
    assert lead.size_category == "MEDIUM"
    assert lead.deposit_amount_pence == 5000
    assert lead.booking_tool == "FRESHA"


def test_lead_answer_media_fields(db):
    """Test that LeadAnswer can store media information."""
    lead = Lead(wa_from="1234567890", status="QUALIFYING")
    db.add(lead)
    db.commit()
    db.refresh(lead)

    answer = LeadAnswer(
        lead_id=lead.id,
        question_key="reference_images",
        answer_text="See attached image",
        message_id="wamid.img123",
        media_id="media123",
        media_url="https://example.com/media.jpg",
    )
    db.add(answer)
    db.commit()
    db.refresh(answer)

    assert answer.message_id == "wamid.img123"
    assert answer.media_id == "media123"
    assert answer.media_url == "https://example.com/media.jpg"


def test_processed_message_model(db):
    """Test ProcessedMessage model for idempotency."""
    lead = Lead(wa_from="1234567890", status="NEW")
    db.add(lead)
    db.commit()
    db.refresh(lead)

    processed = ProcessedMessage(
        provider="whatsapp",
        message_id="wamid.test123",
        lead_id=lead.id,
    )
    db.add(processed)
    db.commit()
    db.refresh(processed)

    assert processed.id is not None
    assert processed.message_id == "wamid.test123"
    assert processed.lead_id == lead.id
    assert processed.processed_at is not None


def test_processed_message_unique_constraint(db):
    """Test that ProcessedMessage message_id is unique."""
    processed1 = ProcessedMessage(
        provider="whatsapp",
        message_id="wamid.unique123",
        lead_id=None,
    )
    db.add(processed1)
    db.commit()

    # Try to add duplicate (same provider + message_id)
    processed2 = ProcessedMessage(
        provider="whatsapp",
        message_id="wamid.unique123",  # Same ID
        lead_id=None,
    )
    db.add(processed2)

    # Should raise integrity error
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        db.commit()

    db.rollback()
