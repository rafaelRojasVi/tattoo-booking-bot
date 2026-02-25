"""
Tests for slot selection integration in conversation flow.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.db.models import Lead
from app.services.conversation import STATUS_BOOKING_PENDING, handle_inbound_message


@pytest.fixture
def sample_lead(db: Session):
    """Create a sample lead for testing."""
    lead = Lead(
        wa_from="test_wa_from",
        status="QUALIFYING",
        channel="whatsapp",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


@pytest.fixture
def lead_with_suggested_slots(db: Session):
    """Create a lead with suggested slots stored."""
    lead = Lead(
        wa_from="test_wa_from",
        status=STATUS_BOOKING_PENDING,
        channel="whatsapp",
    )
    db.add(lead)
    db.flush()

    # Create suggested slots (mock slots)
    now = datetime.now(UTC)
    slots = []
    for i in range(8):
        slot_start = now + timedelta(days=i + 1, hours=10 + i % 3)
        slot_end = slot_start + timedelta(hours=2)
        slots.append(
            {
                "start": slot_start.isoformat(),
                "end": slot_end.isoformat(),
            }
        )

    lead.suggested_slots_json = slots  # type: ignore[assignment]
    db.commit()
    db.refresh(lead)
    return lead


@pytest.mark.asyncio
async def test_slot_selection_by_number(db: Session, lead_with_suggested_slots: Lead, monkeypatch):
    """Test slot selection using direct number."""
    from app.core.config import settings

    mock_send_calls = []
    mock_render_calls = []
    mock_notify_calls = []

    # Disable calendar re-check so we trust stored slots (slot_available = True)
    monkeypatch.setattr(settings, "feature_calendar_enabled", False)

    async def mock_send(*args, **kwargs):
        mock_send_calls.append((args, kwargs))
        return {"status": "sent"}

    def mock_render(*args, **kwargs):
        mock_render_calls.append((args, kwargs))
        return "Got it — slot 1 selected. I'll confirm the details shortly."

    async def mock_notify(*args, **kwargs):
        mock_notify_calls.append((args, kwargs))
        return True

    monkeypatch.setattr("app.services.messaging.messaging.send_whatsapp_message", mock_send)
    monkeypatch.setattr("app.services.messaging.messaging.send_whatsapp_message", mock_send)
    monkeypatch.setattr("app.services.messaging.message_composer.render_message", mock_render)
    monkeypatch.setattr(
        "app.services.integrations.artist_notifications.notify_artist_slot_selected", mock_notify
    )

    result = await handle_inbound_message(
        db=db,
        lead=lead_with_suggested_slots,
        message_text="1",
        dry_run=True,
    )

    assert result["status"] == "slot_selected"
    assert result["slot_number"] == 1
    assert lead_with_suggested_slots.selected_slot_start_at is not None
    assert lead_with_suggested_slots.selected_slot_end_at is not None

    # Verify confirmation sent to client
    assert len(mock_send_calls) == 1
    assert len(mock_render_calls) >= 1
    # Verify artist notified
    assert len(mock_notify_calls) == 1


@pytest.mark.asyncio
async def test_slot_selection_by_option_number(
    db: Session, lead_with_suggested_slots: Lead, monkeypatch
):
    """Test slot selection using 'option 3' format."""
    from app.core.config import settings

    mock_notify_calls = []
    monkeypatch.setattr(settings, "feature_calendar_enabled", False)

    async def mock_send(*args, **kwargs):
        return {"status": "sent"}

    def mock_render(*args, **kwargs):
        return "Got it — slot 3 selected. I'll confirm the details shortly."

    async def mock_notify(*args, **kwargs):
        mock_notify_calls.append((args, kwargs))
        return True

    monkeypatch.setattr("app.services.messaging.messaging.send_whatsapp_message", mock_send)
    monkeypatch.setattr("app.services.messaging.messaging.send_whatsapp_message", mock_send)
    monkeypatch.setattr("app.services.messaging.message_composer.render_message", mock_render)
    monkeypatch.setattr(
        "app.services.integrations.artist_notifications.notify_artist_slot_selected", mock_notify
    )

    result = await handle_inbound_message(
        db=db,
        lead=lead_with_suggested_slots,
        message_text="option 3",
        dry_run=True,
    )

    assert result["status"] == "slot_selected"
    assert result["slot_number"] == 3
    assert lead_with_suggested_slots.selected_slot_start_at is not None


@pytest.mark.asyncio
async def test_slot_selection_repair_on_invalid(
    db: Session, lead_with_suggested_slots: Lead, monkeypatch
):
    """Test soft repair message when slot selection is invalid (via compose_message REPAIR_SLOT)."""
    mock_send_calls = []

    async def mock_send(*args, **kwargs):
        mock_send_calls.append((args, kwargs))
        return {"status": "sent"}

    monkeypatch.setattr("app.services.messaging.messaging.send_whatsapp_message", mock_send)

    result = await handle_inbound_message(
        db=db,
        lead=lead_with_suggested_slots,
        message_text="not a valid selection",
        dry_run=True,
    )

    assert result["status"] == "repair_needed"
    assert result["question_key"] == "slot"
    # Should increment parse failure count
    assert lead_with_suggested_slots.parse_failure_counts is not None
    assert lead_with_suggested_slots.parse_failure_counts.get("slot", 0) == 1

    assert len(mock_send_calls) == 1
    # Repair message comes from compose_message (REPAIR_SLOT)
    sent_msg = mock_send_calls[0][1].get("message") or (
        mock_send_calls[0][0][1] if len(mock_send_calls[0][0]) >= 2 else ""
    )
    assert sent_msg and ("slot" in sent_msg.lower() or "1" in sent_msg or "8" in sent_msg)


@pytest.mark.asyncio
async def test_slot_selection_three_strikes_handover(
    db: Session, lead_with_suggested_slots: Lead, monkeypatch
):
    """Test three-strikes handover for slot selection (retry 3 = handover)."""
    # Set up: already failed twice
    lead_with_suggested_slots.parse_failure_counts = {"slot": 2}
    db.commit()
    db.refresh(lead_with_suggested_slots)

    mock_notify_calls = []

    async def mock_notify(*args, **kwargs):
        mock_notify_calls.append((args, kwargs))
        return True

    async def mock_send(*args, **kwargs):
        return {"status": "sent"}

    def mock_render(*args, **kwargs):
        return "I'm going to have Jonah jump in here — one sec."

    monkeypatch.setattr("app.services.integrations.artist_notifications.notify_artist_needs_reply", mock_notify)
    monkeypatch.setattr("app.services.messaging.messaging.send_whatsapp_message", mock_send)
    monkeypatch.setattr("app.services.messaging.message_composer.render_message", mock_render)

    result = await handle_inbound_message(
        db=db,
        lead=lead_with_suggested_slots,
        message_text="still not clear",
        dry_run=True,
    )

    db.refresh(lead_with_suggested_slots)
    assert result["status"] == "handover_parse_failure"
    assert lead_with_suggested_slots.status == "NEEDS_ARTIST_REPLY"
    assert lead_with_suggested_slots.parse_failure_counts.get("slot", 0) == 3

    assert len(mock_notify_calls) == 1


@pytest.mark.asyncio
async def test_slot_selection_without_suggested_slots(db: Session, sample_lead: Lead, monkeypatch):
    """Test that booking_pending status works even if no slots were suggested yet."""
    sample_lead.status = STATUS_BOOKING_PENDING
    sample_lead.suggested_slots_json = None
    db.commit()

    def mock_render(*args, **kwargs):
        return (
            "Thanks for your deposit! Jonah will confirm your date in the calendar and message you."
        )

    monkeypatch.setattr("app.services.messaging.message_composer.render_message", mock_render)

    result = await handle_inbound_message(
        db=db,
        lead=sample_lead,
        message_text="any message",
        dry_run=True,
    )

    assert result["status"] == "booking_pending"
    # Should just acknowledge, not try to parse slots


@pytest.mark.asyncio
async def test_suggested_slots_stored_when_sent(db: Session, sample_lead: Lead, monkeypatch):
    """Test that suggested slots are stored when sent to client."""
    from app.services.integrations.calendar_service import send_slot_suggestions_to_client

    sample_lead.status = STATUS_BOOKING_PENDING
    db.commit()

    # Mock get_available_slots to return test slots
    test_slots = [
        {
            "start": datetime.now(UTC) + timedelta(days=1, hours=10),
            "end": datetime.now(UTC) + timedelta(days=1, hours=12),
        },
        {
            "start": datetime.now(UTC) + timedelta(days=2, hours=14),
            "end": datetime.now(UTC) + timedelta(days=2, hours=16),
        },
    ]

    async def mock_send_window(*args, **kwargs):
        return {"status": "sent", "window_status": "open"}

    monkeypatch.setattr("app.services.messaging.whatsapp_window.send_with_window_check", mock_send_window)
    monkeypatch.setattr(
        "app.services.integrations.calendar_service.get_available_slots", lambda *args, **kwargs: test_slots
    )

    result = await send_slot_suggestions_to_client(db=db, lead=sample_lead, dry_run=True)

    assert result is True
    assert sample_lead.suggested_slots_json is not None
    assert len(sample_lead.suggested_slots_json) == 2
    # Verify slots are stored as ISO strings
    assert "start" in sample_lead.suggested_slots_json[0]
    assert "end" in sample_lead.suggested_slots_json[0]


@pytest.mark.asyncio
async def test_artist_notification_includes_slot_details(
    db: Session, lead_with_suggested_slots: Lead, monkeypatch
):
    """Test that artist notification includes selected slot details."""
    from app.core.config import settings

    mock_notify_calls = []
    monkeypatch.setattr(settings, "feature_calendar_enabled", False)

    async def mock_send(*args, **kwargs):
        return {"status": "sent"}

    def mock_render(*args, **kwargs):
        return "Got it — slot 2 selected."

    async def mock_notify(*args, **kwargs):
        mock_notify_calls.append((args, kwargs))
        return True

    monkeypatch.setattr("app.services.messaging.messaging.send_whatsapp_message", mock_send)
    monkeypatch.setattr("app.services.messaging.messaging.send_whatsapp_message", mock_send)
    monkeypatch.setattr("app.services.messaging.message_composer.render_message", mock_render)
    monkeypatch.setattr(
        "app.services.integrations.artist_notifications.notify_artist_slot_selected", mock_notify
    )

    # Select slot 2
    result = await handle_inbound_message(
        db=db,
        lead=lead_with_suggested_slots,
        message_text="2",
        dry_run=True,
    )

    # Verify slot was stored correctly
    assert lead_with_suggested_slots.selected_slot_start_at is not None
    assert lead_with_suggested_slots.selected_slot_end_at is not None
    # Verify artist was notified
    assert len(mock_notify_calls) == 1
    # Verify the slot number passed to notification
    call_kwargs = mock_notify_calls[0][1]
    assert call_kwargs["slot_number"] == 2
