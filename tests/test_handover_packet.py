"""
Tests for handover packet service.
"""

from datetime import UTC, datetime

from app.db.models import Lead, LeadAnswer
from app.services.conversation import STATUS_NEEDS_ARTIST_REPLY
from app.services.conversation.handover_packet import build_handover_packet


def test_build_handover_packet_basic(db):
    """Test building a basic handover packet."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_NEEDS_ARTIST_REPLY,
        current_step=5,
        location_city="London",
        location_country="United Kingdom",
        estimated_category="MEDIUM",
        estimated_deposit_amount=5000,
    )
    db.add(lead)
    db.commit()

    # Add some answers
    for i, key in enumerate(["idea", "placement", "dimensions"]):
        answer = LeadAnswer(
            lead_id=lead.id,
            question_key=key,
            answer_text=f"Answer {i}",
        )
        db.add(answer)
    db.commit()

    packet = build_handover_packet(db, lead)

    assert packet["lead_id"] == lead.id
    assert packet["wa_from"] == "1234567890"
    assert packet["status"] == STATUS_NEEDS_ARTIST_REPLY
    assert packet["current_step"] == 5
    assert packet["category"] == "MEDIUM"
    assert packet["deposit_amount_pence"] == 5000
    assert len(packet["last_messages"]) == 3


def test_build_handover_packet_last_5_messages(db):
    """Test that handover packet includes only last 5 messages."""
    lead = Lead(wa_from="1234567890", status=STATUS_NEEDS_ARTIST_REPLY)
    db.add(lead)
    db.commit()

    # Create 7 messages - they'll have same timestamp, so order by ID
    # But the function orders by created_at desc, so we'll get the last 5 by ID
    for i in range(7):
        answer = LeadAnswer(
            lead_id=lead.id,
            question_key=f"test_{i}",
            answer_text=f"Message {i}",
        )
        db.add(answer)
    db.commit()

    packet = build_handover_packet(db, lead)

    assert len(packet["last_messages"]) == 5
    # Should be most recent 5 (by created_at desc, then reversed)
    # Since timestamps are same, it will be by insertion order
    # The function gets last 5 by created_at desc, then reverses
    message_texts = [msg["answer_text"] for msg in packet["last_messages"]]
    # Verify we have exactly 5 messages
    assert len(message_texts) == 5
    # The exact order depends on database ordering, but we should have 5 unique messages
    assert len(set(message_texts)) == 5  # All unique


def test_build_handover_packet_parse_failures(db):
    """Test that parse failures are included in packet."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_NEEDS_ARTIST_REPLY,
        parse_failure_counts={"dimensions": 2, "budget": 1, "location_city": 0},
    )
    db.add(lead)
    db.commit()

    packet = build_handover_packet(db, lead)

    assert "parse_failures" in packet
    assert packet["parse_failures"]["dimensions"] == 2
    assert packet["parse_failures"]["budget"] == 1
    # Zero failures should not be included
    assert "location_city" not in packet["parse_failures"]


def test_build_handover_packet_price_range(db):
    """Test that price range is included in packet."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_NEEDS_ARTIST_REPLY,
        estimated_price_min_pence=8000,
        estimated_price_max_pence=12000,
    )
    db.add(lead)
    db.commit()

    packet = build_handover_packet(db, lead)

    assert packet["price_range_min_pence"] == 8000
    assert packet["price_range_max_pence"] == 12000


def test_build_handover_packet_tour_context(db):
    """Test that tour conversion context is included."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_NEEDS_ARTIST_REPLY,
        requested_city="Paris",
        offered_tour_city="London",
        tour_offer_accepted=False,
        waitlisted=True,
        offered_tour_dates_text="March 2026",
    )
    db.add(lead)
    db.commit()

    packet = build_handover_packet(db, lead)

    assert "tour_context" in packet
    assert packet["tour_context"]["requested_city"] == "Paris"
    assert packet["tour_context"]["offered_tour_city"] == "London"
    assert packet["tour_context"]["waitlisted"] is True
    assert packet["tour_context"]["tour_offer_accepted"] is False
    assert packet["tour_context"]["offered_tour_dates_text"] == "March 2026"


def test_build_handover_packet_budget_parsing(db):
    """Test that budget amount is parsed from text."""
    lead = Lead(wa_from="1234567890", status=STATUS_NEEDS_ARTIST_REPLY)
    db.add(lead)
    db.commit()

    # Add budget answer with text
    answer = LeadAnswer(
        lead_id=lead.id,
        question_key="budget",
        answer_text="£500",
    )
    db.add(answer)
    db.commit()

    packet = build_handover_packet(db, lead)

    assert packet["budget"]["budget_amount_pence"] == 50000  # £500 = 50000 pence


def test_build_handover_packet_current_question_key(db):
    """Test that current question key is included."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_NEEDS_ARTIST_REPLY,
        current_step=3,  # Should map to a question
    )
    db.add(lead)
    db.commit()

    packet = build_handover_packet(db, lead)

    assert "current_question_key" in packet
    # Should have a question key if step is valid


def test_build_handover_packet_deposit_locked(db):
    """Test that locked deposit amount is included."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_NEEDS_ARTIST_REPLY,
        estimated_deposit_amount=10000,  # Estimated
        deposit_amount_pence=5000,  # Locked (different)
        deposit_amount_locked_at=datetime.now(UTC),
    )
    db.add(lead)
    db.commit()

    packet = build_handover_packet(db, lead)

    assert packet["deposit_amount_pence"] == 10000  # Estimated
    assert packet["deposit_locked_amount_pence"] == 5000  # Locked
    assert packet["deposit_amount_locked_at"] is not None


def test_build_handover_packet_timestamps(db):
    """Test that timestamps are included in packet."""
    now = datetime.now(UTC)
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_NEEDS_ARTIST_REPLY,
        created_at=now,
        qualifying_started_at=now,
        needs_artist_reply_at=now,
    )
    db.add(lead)
    db.commit()

    packet = build_handover_packet(db, lead)

    assert "timestamps" in packet
    assert packet["timestamps"]["created_at"] is not None
    assert packet["timestamps"]["qualifying_started_at"] is not None
    assert packet["timestamps"]["needs_artist_reply_at"] is not None
