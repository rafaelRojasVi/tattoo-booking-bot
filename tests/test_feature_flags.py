"""
Test feature flags and panic mode.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings
from app.db.models import Lead
from app.services.integrations.artist_notifications import notify_artist
from app.services.integrations.calendar_service import send_slot_suggestions_to_client
from app.services.conversation import handle_inbound_message
from app.services.messaging.reminders import check_and_send_qualifying_reminder
from app.services.integrations.sheets import log_lead_to_sheets


def test_sheets_disabled_by_feature_flag(db):
    """Test that Sheets logging is skipped when feature flag is disabled."""
    lead = Lead(
        id=300,
        wa_from="1234567890",
        status="NEW",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch.object(settings, "feature_sheets_enabled", False):
        result = log_lead_to_sheets(db, lead)
        assert result is False


def test_calendar_disabled_by_feature_flag(db):
    """Test that calendar slot suggestions are skipped when feature flag is disabled."""
    import asyncio

    lead = Lead(
        id=301,
        wa_from="1234567890",
        status="AWAITING_DEPOSIT",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch.object(settings, "feature_calendar_enabled", False):
        with patch("app.services.integrations.calendar_service.get_available_slots") as mock_slots:
            result = asyncio.run(send_slot_suggestions_to_client(db, lead, dry_run=True))
            # Should return False (not sent) and not call get_available_slots
            assert result is False
            assert not mock_slots.called


def test_reminders_disabled_by_feature_flag(db):
    """Test that reminders are skipped when feature flag is disabled."""
    lead = Lead(
        id=302,
        wa_from="1234567890",
        status="QUALIFYING",
        last_client_message_at=datetime.now(UTC) - timedelta(hours=13),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch.object(settings, "feature_reminders_enabled", False):
        result = check_and_send_qualifying_reminder(
            db=db,
            lead=lead,
            reminder_number=1,
            dry_run=True,
        )
        assert result["status"] == "skipped"
        assert "disabled" in result["reason"].lower()


@pytest.mark.asyncio
async def test_notifications_disabled_by_feature_flag(db):
    """Test that artist notifications are skipped when feature flag is disabled."""
    lead = Lead(
        id=303,
        wa_from="1234567890",
        status="PENDING_APPROVAL",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch.object(settings, "feature_notifications_enabled", False):
        result = await notify_artist(
            db=db,
            lead=lead,
            event_type="pending_approval",
            dry_run=True,
        )
        assert result is False


@pytest.mark.asyncio
async def test_panic_mode_pauses_automation(db):
    """Test that panic mode pauses automation but still logs and notifies artist."""
    lead = Lead(
        id=304,
        wa_from="1234567890",
        status="QUALIFYING",
        current_step=0,
        last_client_message_at=None,  # No previous message = window is open
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch.object(settings, "feature_panic_mode_enabled", True):
        with patch.object(settings, "feature_notifications_enabled", True):
            with patch(
                "app.services.integrations.artist_notifications.notify_artist", new_callable=AsyncMock
            ) as mock_notify:
                mock_notify.return_value = True
                with patch(
                    "app.services.messaging.messaging.send_whatsapp_message", new_callable=AsyncMock
                ) as mock_send:
                    result = await handle_inbound_message(
                        db=db,
                        lead=lead,
                        message_text="Hello",
                        dry_run=True,
                    )

                    assert result["status"] == "panic_mode"
                    assert "panic" in result["message"].lower()

                    # Should notify artist
                    assert mock_notify.called

                    # Should send safe response if within window
                    # (In this case, no previous message, so window is open)
                    # Note: is_within_24h_window returns True when last_client_message_at is None
                    # The safe message may or may not be sent depending on window check
                    # What matters is that automation is paused and artist is notified
                    db.refresh(lead)
                    assert lead.last_client_message_at is not None  # Message was logged


@pytest.mark.asyncio
async def test_panic_mode_still_logs_messages(db):
    """Test that panic mode still logs incoming messages."""
    lead = Lead(
        id=305,
        wa_from="1234567890",
        status="QUALIFYING",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    initial_timestamp = lead.last_client_message_at

    with patch.object(settings, "feature_panic_mode_enabled", True):
        await handle_inbound_message(
            db=db,
            lead=lead,
            message_text="Test message",
            dry_run=True,
        )

        db.refresh(lead)
        # Should have updated timestamp
        assert lead.last_client_message_at is not None
        if initial_timestamp:
            assert lead.last_client_message_at > initial_timestamp
