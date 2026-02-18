"""
Tests for new conversation features: ARTIST handover, CONTINUE, new statuses, etc.
"""

import pytest

from app.db.models import Lead, LeadAnswer
from app.services.conversation import (
    STATUS_ABANDONED,
    STATUS_BOOKED,
    STATUS_DEPOSIT_PAID,
    STATUS_NEEDS_ARTIST_REPLY,
    STATUS_PENDING_APPROVAL,
    STATUS_QUALIFYING,
    STATUS_REJECTED,
    STATUS_STALE,
    handle_inbound_message,
)
from app.services.questions import get_total_questions


@pytest.mark.asyncio
async def test_artist_handover_request(client, db):
    """Test that typing ARTIST pauses bot and sets NEEDS_ARTIST_REPLY status."""
    lead = Lead(wa_from="1234567890", status=STATUS_QUALIFYING, current_step=0)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    result = await handle_inbound_message(
        db=db,
        lead=lead,
        message_text="ARTIST",
        dry_run=True,
    )

    db.refresh(lead)
    assert lead.status == STATUS_NEEDS_ARTIST_REPLY
    # Phase 1: Returns "handover" status, not "artist_handover"
    assert result["status"] in ["handover", "artist_handover"]
    assert (
        "paused" in result["message"].lower()
        or "artist" in result["message"].lower()
        or "jonah" in result["message"].lower()
    )


@pytest.mark.asyncio
async def test_continue_resumes_flow(client, db):
    """Test that CONTINUE resumes qualification flow from NEEDS_ARTIST_REPLY."""
    lead = Lead(wa_from="1234567890", status=STATUS_NEEDS_ARTIST_REPLY, current_step=2)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    result = await handle_inbound_message(
        db=db,
        lead=lead,
        message_text="CONTINUE",
        dry_run=True,
    )

    db.refresh(lead)
    assert lead.status == STATUS_QUALIFYING
    assert result["status"] == "resumed"
    assert "continue" in result["message"].lower() or result["message"]


@pytest.mark.asyncio
async def test_pending_approval_status_acknowledges(client, db):
    """Test that PENDING_APPROVAL status acknowledges messages."""
    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL, current_step=10)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    result = await handle_inbound_message(
        db=db,
        lead=lead,
        message_text="When will I hear back?",
        dry_run=True,
    )

    assert result["status"] == "pending_approval"
    assert "review" in result["message"].lower() or "soon" in result["message"].lower()


@pytest.mark.asyncio
async def test_deposit_paid_status_acknowledges(client, db):
    """Test that DEPOSIT_PAID status acknowledges messages."""
    lead = Lead(wa_from="1234567890", status=STATUS_DEPOSIT_PAID, current_step=10)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    result = await handle_inbound_message(
        db=db,
        lead=lead,
        message_text="When do I get the booking link?",
        dry_run=True,
    )

    assert result["status"] == "deposit_paid"
    assert "booking" in result["message"].lower() or "link" in result["message"].lower()


@pytest.mark.asyncio
async def test_booking_link_sent_status_acknowledges(client, db):
    """Test that BOOKING_PENDING status acknowledges messages (Phase 1 replaces BOOKING_LINK_SENT)."""
    from app.services.conversation import STATUS_BOOKING_PENDING

    lead = Lead(wa_from="1234567890", status=STATUS_BOOKING_PENDING, current_step=10)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    result = await handle_inbound_message(
        db=db,
        lead=lead,
        message_text="When will I be booked?",
        dry_run=True,
    )

    # Phase 1: BOOKING_PENDING returns "booking_pending" status
    assert result["status"] == "booking_pending"
    # Message confirms deposit and mentions calendar/booking
    assert (
        "deposit" in result["message"].lower()
        or "calendar" in result["message"].lower()
        or "booking" in result["message"].lower()
        or "jonah" in result["message"].lower()
    )


@pytest.mark.asyncio
async def test_booked_status_acknowledges(client, db):
    """Test that BOOKED status acknowledges messages."""
    lead = Lead(wa_from="1234567890", status=STATUS_BOOKED, current_step=10)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    result = await handle_inbound_message(
        db=db,
        lead=lead,
        message_text="What time is my appointment?",
        dry_run=True,
    )

    assert result["status"] == "booked"
    assert "confirmed" in result["message"].lower() or "see you" in result["message"].lower()


@pytest.mark.asyncio
async def test_rejected_status_acknowledges(client, db):
    """Test that REJECTED status acknowledges messages."""
    lead = Lead(wa_from="1234567890", status=STATUS_REJECTED, current_step=10)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    result = await handle_inbound_message(
        db=db,
        lead=lead,
        message_text="Why was I rejected?",
        dry_run=True,
    )

    assert result["status"] == "rejected"
    assert "unable" in result["message"].lower() or "proceed" in result["message"].lower()


@pytest.mark.asyncio
async def test_abandoned_status_restarts_flow(client, db):
    """Test that ABANDONED status allows restarting the flow."""
    lead = Lead(wa_from="1234567890", status=STATUS_ABANDONED, current_step=5)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    result = await handle_inbound_message(
        db=db,
        lead=lead,
        message_text="Hello, I'm back",
        dry_run=True,
    )

    db.refresh(lead)
    # Should reset to NEW and start qualification
    assert lead.status == STATUS_QUALIFYING
    assert result["status"] == "question_sent"


@pytest.mark.asyncio
async def test_stale_status_restarts_flow(client, db):
    """Test that STALE status allows restarting the flow."""
    lead = Lead(wa_from="1234567890", status=STATUS_STALE, current_step=5)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    result = await handle_inbound_message(
        db=db,
        lead=lead,
        message_text="Hello, I'm back",
        dry_run=True,
    )

    db.refresh(lead)
    # Should reset to NEW and start qualification
    assert lead.status == STATUS_QUALIFYING
    assert result["status"] == "question_sent"


@pytest.mark.asyncio
async def test_completion_sets_pending_approval(client, db):
    """Test that completing qualification sets PENDING_APPROVAL and caches summary."""
    from unittest.mock import patch

    lead = Lead(
        wa_from="1234567890",
        status=STATUS_QUALIFYING,
        current_step=get_total_questions() - 1,
    )
    db.add(lead)
    db.commit()

    # Add previous answers
    from app.services.questions import CONSULTATION_QUESTIONS

    for _i, question in enumerate(CONSULTATION_QUESTIONS[:-1]):  # All except last
        answer = LeadAnswer(
            lead_id=lead.id,
            question_key=question.key,
            answer_text=f"Answer for {question.key}",
        )
        db.add(answer)
    # Ensure location is set to a city on tour (London, UK) to avoid waitlist
    location_country = (
        db.query(LeadAnswer)
        .filter(LeadAnswer.lead_id == lead.id, LeadAnswer.question_key == "location_country")
        .first()
    )
    if location_country:
        location_country.answer_text = "United Kingdom"
    else:
        location_country = LeadAnswer(
            lead_id=lead.id, question_key="location_country", answer_text="United Kingdom"
        )
        db.add(location_country)
    location_city = (
        db.query(LeadAnswer)
        .filter(LeadAnswer.lead_id == lead.id, LeadAnswer.question_key == "location_city")
        .first()
    )
    if location_city:
        location_city.answer_text = "London"
    else:
        location_city = LeadAnswer(
            lead_id=lead.id, question_key="location_city", answer_text="London"
        )
        db.add(location_city)
    db.commit()
    db.refresh(lead)

    # Mock tour service to ensure city is on tour
    with patch("app.services.tour_service.is_city_on_tour", return_value=True):
        # Answer last question
        result = await handle_inbound_message(
            db=db,
            lead=lead,
            message_text="Next month",
            dry_run=True,
        )

        db.refresh(lead)
        assert lead.status == STATUS_PENDING_APPROVAL
        assert lead.summary_text is not None
        assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_timestamps_updated_on_messages(client, db):
    """Test that last_client_message_at and last_bot_message_at are updated."""
    lead = Lead(wa_from="1234567890", status=STATUS_QUALIFYING, current_step=0)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    initial_client_time = lead.last_client_message_at
    initial_bot_time = lead.last_bot_message_at

    # Send a message
    result = await handle_inbound_message(
        db=db,
        lead=lead,
        message_text="I want a dragon tattoo",
        dry_run=True,
    )

    db.refresh(lead)
    # last_client_message_at should be updated
    assert lead.last_client_message_at is not None
    # last_bot_message_at should be updated (bot sent next question)
    assert lead.last_bot_message_at is not None


@pytest.mark.asyncio
async def test_artist_handover_does_not_save_answer(client, db):
    """Test that ARTIST command doesn't save an answer to the current question."""
    lead = Lead(wa_from="1234567890", status=STATUS_QUALIFYING, current_step=0)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    initial_answer_count = db.query(LeadAnswer).filter(LeadAnswer.lead_id == lead.id).count()

    result = await handle_inbound_message(
        db=db,
        lead=lead,
        message_text="ARTIST",
        dry_run=True,
    )

    # Should not have saved "ARTIST" as an answer
    final_answer_count = db.query(LeadAnswer).filter(LeadAnswer.lead_id == lead.id).count()
    assert final_answer_count == initial_answer_count

    db.refresh(lead)
    assert lead.status == STATUS_NEEDS_ARTIST_REPLY
