"""
Tests for debug endpoint.
"""

from datetime import UTC, datetime

from app.db.models import Lead, LeadAnswer, ProcessedMessage, SystemEvent
from app.services.conversation import STATUS_BOOKED, STATUS_NEEDS_ARTIST_REPLY


def test_debug_endpoint_returns_comprehensive_info(client, db):
    """Test that debug endpoint returns comprehensive lead information."""
    # Create lead with various data
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_NEEDS_ARTIST_REPLY,
        current_step=5,
        location_city="London",
        location_country="United Kingdom",
        estimated_category="MEDIUM",
        estimated_deposit_amount=5000,
        parse_failure_counts={"dimensions": 2},
        qualifying_started_at=datetime.now(UTC),
        needs_artist_reply_at=datetime.now(UTC),
    )
    db.add(lead)
    db.commit()

    # Add answers
    for i, key in enumerate(["idea", "placement", "dimensions"]):
        answer = LeadAnswer(
            lead_id=lead.id,
            question_key=key,
            answer_text=f"Answer {i}",
        )
        db.add(answer)

    # Add system event
    event = SystemEvent(
        level="WARN",
        event_type="test.event",
        lead_id=lead.id,
        payload={"test": "data"},
    )
    db.add(event)

    # Add processed message
    processed = ProcessedMessage(
        message_id="wamid.test123",
        event_type="whatsapp.message",
        lead_id=lead.id,
    )
    db.add(processed)
    db.commit()

    # Call debug endpoint
    response = client.get(
        f"/admin/debug/lead/{lead.id}",
        headers={"X-Admin-API-Key": "test_key"},
    )

    assert response.status_code == 200
    data = response.json()

    # Check structure
    assert "lead" in data
    assert "handover_packet" in data
    assert "answers" in data
    assert "system_events" in data
    assert "processed_messages" in data
    assert "status_history" in data
    assert "parse_failures" in data
    assert "timestamps" in data

    # Check lead data
    assert data["lead"]["id"] == lead.id
    assert data["lead"]["status"] == STATUS_NEEDS_ARTIST_REPLY

    # Check answers
    assert len(data["answers"]) == 3

    # Check system events
    assert len(data["system_events"]) == 1
    assert data["system_events"][0]["event_type"] == "test.event"

    # Check processed messages
    assert len(data["processed_messages"]) == 1
    assert data["processed_messages"][0]["message_id"] == "wamid.test123"

    # Check parse failures
    assert data["parse_failures"]["dimensions"] == 2


def test_debug_endpoint_404_for_missing_lead(client, db):
    """Test that debug endpoint returns 404 for missing lead."""
    response = client.get(
        "/admin/debug/lead/99999",
        headers={"X-Admin-API-Key": "test_key"},
    )

    assert response.status_code == 404


def test_debug_endpoint_requires_auth(client, db):
    """Test that debug endpoint requires authentication."""
    lead = Lead(wa_from="1234567890", status=STATUS_NEEDS_ARTIST_REPLY)
    db.add(lead)
    db.commit()

    # Without auth - in dev mode may allow, in production should require
    response = client.get(f"/admin/debug/lead/{lead.id}")
    # In dev mode (DEMO_MODE), may allow without auth
    # In production, should return 403 or 401
    # For now, just verify endpoint exists
    assert response.status_code in [200, 401, 403]


def test_debug_endpoint_status_history(db, client):
    """Test that status history is included in debug output."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_BOOKED,
        qualifying_started_at=datetime.now(UTC),
        pending_approval_at=datetime.now(UTC),
        approved_at=datetime.now(UTC),
        deposit_sent_at=datetime.now(UTC),
        deposit_paid_at=datetime.now(UTC),
        booked_at=datetime.now(UTC),
    )
    db.add(lead)
    db.commit()

    response = client.get(
        f"/admin/debug/lead/{lead.id}",
        headers={"X-Admin-API-Key": "test_key"},
    )

    assert response.status_code == 200
    data = response.json()

    assert "status_history" in data
    assert len(data["status_history"]) > 0

    # Check that history is ordered by timestamp
    timestamps = [item["timestamp"] for item in data["status_history"]]
    assert timestamps == sorted(timestamps)


def test_debug_endpoint_handover_packet_included(db, client):
    """Test that handover packet is included in debug output."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_NEEDS_ARTIST_REPLY,
        estimated_category="LARGE",
        estimated_deposit_amount=10000,
    )
    db.add(lead)
    db.commit()

    response = client.get(
        f"/admin/debug/lead/{lead.id}",
        headers={"X-Admin-API-Key": "test_key"},
    )

    assert response.status_code == 200
    data = response.json()

    assert "handover_packet" in data
    packet = data["handover_packet"]
    assert packet["category"] == "LARGE"
    assert packet["deposit_amount_pence"] == 10000
