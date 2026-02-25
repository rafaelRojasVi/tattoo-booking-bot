"""
Test Phase 1 artist notifications for NEEDS_ARTIST_REPLY and NEEDS_FOLLOW_UP.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings
from app.db.models import Lead, LeadAnswer
from app.services.integrations.artist_notifications import (
    notify_artist_needs_follow_up,
    notify_artist_needs_reply,
)


@pytest.mark.asyncio
async def test_notify_artist_needs_reply_sends_notification(db):
    """Test that notify_artist_needs_reply sends notification on first call."""
    lead = Lead(
        id=100,
        wa_from="1234567890",
        status="NEEDS_ARTIST_REPLY",
        handover_reason="High complexity design",
        needs_artist_reply_at=datetime.now(UTC),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Add some answers for summary
    for key, value in [("idea", "Complex dragon"), ("placement", "Full back")]:
        answer = LeadAnswer(lead_id=lead.id, question_key=key, answer_text=value)
        db.add(answer)
    db.commit()
    db.refresh(lead)

    with (
        patch(
            "app.services.integrations.artist_notifications.send_whatsapp_message",
            new_callable=AsyncMock,
        ) as mock_send,
        patch.object(settings, "artist_whatsapp_number", "+1234567890"),
    ):
        result = await notify_artist_needs_reply(
            db=db,
            lead=lead,
            reason="High complexity design",
            dry_run=False,
        )

        assert result is True
        assert mock_send.called
        call_args = mock_send.call_args
        assert call_args[1]["to"] == "+1234567890"
        message = call_args[1]["message"]
        assert "Lead #100" in message
        assert "needs you" in message
        assert "High complexity design" in message
        assert "Complex dragon" in message  # From summary

        # Check that notification timestamp was set
        db.refresh(lead)
        assert lead.needs_artist_reply_notified_at is not None


@pytest.mark.asyncio
async def test_notify_artist_needs_reply_idempotent(db):
    """Test that notify_artist_needs_reply only sends once (idempotent)."""
    lead = Lead(
        id=101,
        wa_from="1234567890",
        status="NEEDS_ARTIST_REPLY",
        needs_artist_reply_at=datetime.now(UTC),
        needs_artist_reply_notified_at=datetime.now(UTC),  # Already notified
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with (
        patch(
            "app.services.integrations.artist_notifications.send_whatsapp_message",
            new_callable=AsyncMock,
        ) as mock_send,
        patch.object(settings, "artist_whatsapp_number", "+1234567890"),
    ):
        result = await notify_artist_needs_reply(
            db=db,
            lead=lead,
            reason="Test reason",
            dry_run=False,
        )

        assert result is False  # Should skip (already notified)
        assert not mock_send.called


@pytest.mark.asyncio
async def test_notify_artist_needs_follow_up_sends_notification(db):
    """Test that notify_artist_needs_follow_up sends notification on first call."""
    lead = Lead(
        id=102,
        wa_from="1234567890",
        status="NEEDS_FOLLOW_UP",
        below_min_budget=True,
        min_budget_amount=40000,
        needs_follow_up_at=datetime.now(UTC),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Add budget answer
    answer = LeadAnswer(lead_id=lead.id, question_key="budget", answer_text="£300")
    db.add(answer)
    db.commit()
    db.refresh(lead)

    with (
        patch(
            "app.services.integrations.artist_notifications.send_whatsapp_message",
            new_callable=AsyncMock,
        ) as mock_send,
        patch.object(settings, "artist_whatsapp_number", "+1234567890"),
    ):
        result = await notify_artist_needs_follow_up(
            db=db,
            lead=lead,
            reason="Budget below minimum (Min £400, Budget £300)",
            dry_run=False,
        )

        assert result is True
        assert mock_send.called
        call_args = mock_send.call_args
        assert call_args[1]["to"] == "+1234567890"
        message = call_args[1]["message"]
        assert "Lead #102" in message
        assert "needs follow-up" in message
        assert "Budget below minimum" in message

        # Check that notification timestamp was set
        db.refresh(lead)
        assert lead.needs_follow_up_notified_at is not None


@pytest.mark.asyncio
async def test_notify_artist_needs_follow_up_idempotent(db):
    """Test that notify_artist_needs_follow_up only sends once (idempotent)."""
    lead = Lead(
        id=103,
        wa_from="1234567890",
        status="NEEDS_FOLLOW_UP",
        needs_follow_up_at=datetime.now(UTC),
        needs_follow_up_notified_at=datetime.now(UTC),  # Already notified
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with (
        patch(
            "app.services.integrations.artist_notifications.send_whatsapp_message",
            new_callable=AsyncMock,
        ) as mock_send,
        patch.object(settings, "artist_whatsapp_number", "+1234567890"),
    ):
        result = await notify_artist_needs_follow_up(
            db=db,
            lead=lead,
            reason="Test reason",
            dry_run=False,
        )

        assert result is False  # Should skip (already notified)
        assert not mock_send.called


@pytest.mark.asyncio
async def test_notify_artist_needs_reply_includes_summary(db):
    """Test that notification includes Phase 1 summary block."""
    lead = Lead(
        id=104,
        wa_from="1234567890",
        status="NEEDS_ARTIST_REPLY",
        handover_reason="Cover-up",
        complexity_level=3,
        estimated_category="LARGE",
        location_city="London",
        location_country="UK",
        needs_artist_reply_at=datetime.now(UTC),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Add answers
    for key, value in [
        ("idea", "Cover-up of old tattoo"),
        ("placement", "Left arm"),
        ("dimensions", "15x20cm"),
    ]:
        answer = LeadAnswer(lead_id=lead.id, question_key=key, answer_text=value)
        db.add(answer)
    db.commit()
    db.refresh(lead)

    with (
        patch(
            "app.services.integrations.artist_notifications.send_whatsapp_message",
            new_callable=AsyncMock,
        ) as mock_send,
        patch.object(settings, "artist_whatsapp_number", "+1234567890"),
    ):
        await notify_artist_needs_reply(
            db=db,
            lead=lead,
            reason="Cover-up",
            dry_run=False,
        )

        message = mock_send.call_args[1]["message"]
        # Should include summary fields
        assert "Lead #104" in message
        assert "Cover-up of old tattoo" in message or "Cover-up" in message
        assert "London" in message
        assert "UK" in message


@pytest.mark.asyncio
async def test_notify_artist_needs_follow_up_includes_summary(db):
    """Test that notification includes Phase 1 summary block."""
    lead = Lead(
        id=105,
        wa_from="1234567890",
        status="NEEDS_FOLLOW_UP",
        below_min_budget=True,
        min_budget_amount=40000,
        needs_follow_up_at=datetime.now(UTC),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Add answers
    answer = LeadAnswer(lead_id=lead.id, question_key="budget", answer_text="£350")
    db.add(answer)
    db.commit()
    db.refresh(lead)

    with (
        patch(
            "app.services.integrations.artist_notifications.send_whatsapp_message",
            new_callable=AsyncMock,
        ) as mock_send,
        patch.object(settings, "artist_whatsapp_number", "+1234567890"),
    ):
        await notify_artist_needs_follow_up(
            db=db,
            lead=lead,
            reason="Budget below minimum (Min £400, Budget £350)",
            dry_run=False,
        )

        message = mock_send.call_args[1]["message"]
        # Should include summary
        assert "Lead #105" in message
        assert "needs follow-up" in message
        assert "Budget below minimum" in message
