"""
Tests for parse repair and two-strikes handover logic.
"""

import pytest
from sqlalchemy.orm import Session

from app.db.models import Lead, LeadAnswer
from app.services.conversation import STATUS_NEEDS_ARTIST_REPLY, STATUS_QUALIFYING
from app.services.parse_repair import (
    get_failure_count,
    increment_parse_failure,
    reset_parse_failures,
    should_handover_after_failure,
    trigger_handover_after_parse_failure,
)


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


@pytest.mark.asyncio
async def test_increment_parse_failure(db: Session, sample_lead: Lead):
    """Test incrementing parse failure count."""
    assert get_failure_count(sample_lead, "dimensions") == 0

    count1 = increment_parse_failure(db, sample_lead, "dimensions")
    db.refresh(sample_lead)
    assert count1 == 1
    assert get_failure_count(sample_lead, "dimensions") == 1

    count2 = increment_parse_failure(db, sample_lead, "dimensions")
    db.refresh(sample_lead)
    assert count2 == 2
    assert get_failure_count(sample_lead, "dimensions") == 2

    # Different field should be separate
    count_budget = increment_parse_failure(db, sample_lead, "budget")
    db.refresh(sample_lead)
    assert count_budget == 1
    assert get_failure_count(sample_lead, "budget") == 1
    assert get_failure_count(sample_lead, "dimensions") == 2  # Unchanged


@pytest.mark.asyncio
async def test_reset_parse_failures(db: Session, sample_lead: Lead):
    """Test resetting parse failure count."""
    increment_parse_failure(db, sample_lead, "dimensions")
    increment_parse_failure(db, sample_lead, "dimensions")
    assert get_failure_count(sample_lead, "dimensions") == 2

    reset_parse_failures(db, sample_lead, "dimensions")
    assert get_failure_count(sample_lead, "dimensions") == 0


@pytest.mark.asyncio
async def test_should_handover_after_failure(sample_lead: Lead):
    """Test three-strikes handover logic (retry 1 gentle, retry 2 short+boundary, retry 3 handover)."""
    assert not should_handover_after_failure(sample_lead, "dimensions")

    sample_lead.parse_failure_counts = {"dimensions": 1}
    assert not should_handover_after_failure(sample_lead, "dimensions")

    sample_lead.parse_failure_counts = {"dimensions": 2}
    assert not should_handover_after_failure(sample_lead, "dimensions")

    sample_lead.parse_failure_counts = {"dimensions": 3}
    assert should_handover_after_failure(sample_lead, "dimensions")


@pytest.mark.asyncio
async def test_trigger_handover_after_parse_failure(db: Session, sample_lead: Lead, monkeypatch):
    """Test triggering handover after three parse failures (retry 3 = handover)."""
    from unittest.mock import AsyncMock

    sample_lead.status = STATUS_QUALIFYING
    sample_lead.parse_failure_counts = {"dimensions": 3}
    db.commit()

    # Patch at source so parse_repair's function-level imports get the mocks
    mock_notify = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.services.artist_notifications.notify_artist_needs_reply",
        mock_notify,
    )
    mock_send = AsyncMock(return_value={"status": "sent"})
    monkeypatch.setattr("app.services.messaging.send_whatsapp_message", mock_send)
    from unittest.mock import MagicMock

    mock_render = MagicMock(return_value="I'm going to have Jonah jump in here — one sec.")
    monkeypatch.setattr("app.services.message_composer.render_message", mock_render)

    result = await trigger_handover_after_parse_failure(db, sample_lead, "dimensions", dry_run=True)

    assert result["status"] == "handover_parse_failure"
    assert result["field"] == "dimensions"
    assert sample_lead.status == STATUS_NEEDS_ARTIST_REPLY
    assert sample_lead.handover_reason is not None
    assert "dimensions" in sample_lead.handover_reason.lower()

    mock_notify.assert_called_once()
    mock_send.assert_called_once()
    mock_render.assert_called_once()


@pytest.mark.asyncio
async def test_soft_repair_dimensions(db: Session, sample_lead: Lead, monkeypatch):
    """Test soft repair message sent when dimensions can't be parsed (via compose_message)."""
    from unittest.mock import AsyncMock

    from app.services.conversation import _handle_qualifying_lead

    sample_lead.status = STATUS_QUALIFYING
    sample_lead.current_step = 2  # dimensions question
    db.commit()

    # Add dimensions question answer
    answer = LeadAnswer(lead_id=sample_lead.id, question_key="dimensions", answer_text="not a size")
    db.add(answer)
    db.commit()

    mock_send = AsyncMock(return_value={"status": "sent"})
    monkeypatch.setattr("app.services.conversation.send_whatsapp_message", mock_send)

    result = await _handle_qualifying_lead(db, sample_lead, "not a size", dry_run=True)

    assert result["status"] == "repair_needed"
    assert result["question_key"] == "dimensions"
    assert get_failure_count(sample_lead, "dimensions") == 1
    mock_send.assert_called_once()
    # Repair message comes from compose_message (REPAIR_SIZE), not render_message
    call_args = mock_send.call_args
    assert "message" in call_args.kwargs or len(call_args[0]) >= 2
    msg = call_args.kwargs.get("message") or (call_args[0][1] if len(call_args[0]) >= 2 else "")
    assert msg and ("size" in msg.lower() or "10" in msg or "cm" in msg.lower())


@pytest.mark.asyncio
async def test_three_strikes_handover_dimensions(db: Session, sample_lead: Lead, monkeypatch):
    """Test three-strikes handover for dimensions (retry 1 gentle, retry 2 short+boundary, retry 3 handover)."""
    from unittest.mock import AsyncMock, MagicMock

    from app.services.conversation import _handle_qualifying_lead

    sample_lead.status = STATUS_QUALIFYING
    sample_lead.current_step = 2  # dimensions question
    sample_lead.parse_failure_counts = {"dimensions": 2}  # Already failed twice
    db.commit()

    mock_notify = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.services.artist_notifications.notify_artist_needs_reply",
        mock_notify,
    )
    mock_send = AsyncMock(return_value={"status": "sent"})
    monkeypatch.setattr("app.services.conversation.send_whatsapp_message", mock_send)
    mock_render = MagicMock(return_value="I'm going to have Jonah jump in here — one sec.")
    monkeypatch.setattr("app.services.message_composer.render_message", mock_render)

    result = await _handle_qualifying_lead(db, sample_lead, "still not a size", dry_run=True)

    assert result["status"] == "handover_parse_failure"
    assert sample_lead.status == STATUS_NEEDS_ARTIST_REPLY
    assert get_failure_count(sample_lead, "dimensions") == 3
    mock_notify.assert_called_once()


@pytest.mark.asyncio
async def test_soft_repair_budget(db: Session, sample_lead: Lead, monkeypatch):
    """Test soft repair message sent when budget can't be parsed."""
    from unittest.mock import AsyncMock, MagicMock

    from app.services.conversation import _handle_qualifying_lead

    sample_lead.status = STATUS_QUALIFYING
    sample_lead.current_step = 7  # budget question
    db.commit()

    mock_send = AsyncMock(return_value={"status": "sent"})
    monkeypatch.setattr("app.services.conversation.send_whatsapp_message", mock_send)
    mock_render = MagicMock(return_value="Just to clarify — what's your budget amount?")
    monkeypatch.setattr("app.services.message_composer.render_message", mock_render)

    result = await _handle_qualifying_lead(db, sample_lead, "not a number", dry_run=True)

    assert result["status"] == "repair_needed"
    assert result["question_key"] == "budget"
    assert get_failure_count(sample_lead, "budget") == 1
    mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_soft_repair_location(db: Session, sample_lead: Lead, monkeypatch):
    """Test soft repair message sent when location is too short."""
    from unittest.mock import AsyncMock, MagicMock

    from app.services.conversation import _handle_qualifying_lead

    sample_lead.status = STATUS_QUALIFYING
    sample_lead.current_step = 8  # location_city question
    db.commit()

    mock_send = AsyncMock(return_value={"status": "sent"})
    monkeypatch.setattr("app.services.conversation.send_whatsapp_message", mock_send)
    mock_render = MagicMock(return_value="Just to make sure — what city are you currently in?")
    monkeypatch.setattr("app.services.message_composer.render_message", mock_render)

    result = await _handle_qualifying_lead(db, sample_lead, "a", dry_run=True)  # Too short

    assert result["status"] == "repair_needed"
    assert result["question_key"] == "location_city"
    assert get_failure_count(sample_lead, "location_city") == 1
    mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_micro_confirmation_after_all_fields(db: Session, sample_lead: Lead, monkeypatch):
    """Test micro-confirmation sent after dimensions, budget, and location are all captured."""
    from unittest.mock import AsyncMock, MagicMock

    from app.services.conversation import _handle_qualifying_lead

    sample_lead.status = STATUS_QUALIFYING
    sample_lead.current_step = 8  # location_city question (last of the three)
    db.commit()

    # Add previous answers
    db.add(LeadAnswer(lead_id=sample_lead.id, question_key="dimensions", answer_text="10×7cm"))
    db.add(LeadAnswer(lead_id=sample_lead.id, question_key="budget", answer_text="500"))
    db.commit()

    # _handle_qualifying_lead uses _get_send_whatsapp() which reads from conversation
    mock_send = AsyncMock(return_value={"status": "sent"})
    monkeypatch.setattr("app.services.conversation.send_whatsapp_message", mock_send)
    mock_render = MagicMock(
        return_value="Got it — 10×7cm, London, budget ~£500. Reply if you want to change anything."
    )
    monkeypatch.setattr("app.services.message_composer.render_message", mock_render)

    result = await _handle_qualifying_lead(db, sample_lead, "London", dry_run=True)

    # Should send confirmation and advance to next question (confirmation + next question = 2 sends)
    assert result["status"] == "confirmation_sent"
    assert mock_send.await_count >= 1, "At least confirmation must be sent"
    # Check that confirmation message was rendered
    assert any("confirmation_summary" in str(call) for call in mock_render.call_args_list)


@pytest.mark.asyncio
async def test_parse_success_resets_failures(db: Session, sample_lead: Lead):
    """Test that successful parsing resets failure count."""
    from app.services.conversation import _handle_qualifying_lead

    sample_lead.status = STATUS_QUALIFYING
    sample_lead.current_step = 2  # dimensions question
    sample_lead.parse_failure_counts = {"dimensions": 1}  # Previously failed
    db.commit()

    # Now send valid dimensions
    result = await _handle_qualifying_lead(db, sample_lead, "10×7cm", dry_run=True)

    # Should reset failure count
    assert get_failure_count(sample_lead, "dimensions") == 0
    # Should not be in repair_needed status
    assert result["status"] != "repair_needed"
