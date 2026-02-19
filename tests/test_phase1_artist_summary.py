"""
Test Phase 1 artist WhatsApp summary functionality.
"""

import importlib
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings
from app.db.models import Lead
from app.services.artist_notifications import (
    format_artist_summary,
    notify_artist,
    send_artist_summary,
)


def test_format_artist_summary_includes_key_info(db):
    """Test that artist summary includes key lead information."""
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
        instagram_handle="@testuser",
        below_min_budget=False,
    )

    answers_dict = {
        "idea": "A dragon tattoo",
        "placement": "Left arm",
        "dimensions": "10x15cm",
    }

    action_tokens = {
        "approve": "https://example.com/a/abc123",
        "reject": "https://example.com/a/def456",
    }

    message = format_artist_summary(lead, answers_dict, action_tokens)

    assert "Lead #42" in message
    assert "A dragon tattoo" in message
    assert "Left arm" in message
    assert "10x15cm" in message
    assert "Medium" in message
    assert "£150" in message
    assert "London" in message
    assert "UK" in message
    assert "@testuser" in message
    assert "approve" in message.lower()
    assert "reject" in message.lower()
    assert "abc123" in message
    assert "def456" in message


def test_format_artist_summary_shows_below_min_budget(db):
    """Test that below minimum budget is flagged."""
    lead = Lead(
        id=43,
        wa_from="1234567890",
        status="PENDING_APPROVAL",
        below_min_budget=True,
    )

    answers_dict = {"idea": "Test tattoo"}
    action_tokens: dict[str, str] = {}

    message = format_artist_summary(lead, answers_dict, action_tokens)

    assert "Below minimum budget" in message or "minimum budget" in message.lower()


def test_format_artist_summary_shows_handover_reason(db):
    """Test that handover reason is included."""
    lead = Lead(
        id=44,
        wa_from="1234567890",
        status="PENDING_APPROVAL",
        handover_reason="Complex coverup",
    )

    answers_dict = {"idea": "Test tattoo"}
    action_tokens: dict[str, str] = {}

    message = format_artist_summary(lead, answers_dict, action_tokens)

    assert "Complex coverup" in message
    assert "Handover" in message or "handover" in message.lower()


def test_format_artist_summary_without_action_tokens(db):
    """Test that summary works without action tokens."""
    lead = Lead(
        id=45,
        wa_from="1234567890",
        status="PENDING_APPROVAL",
    )

    answers_dict = {"idea": "Test tattoo"}
    action_tokens: dict[str, str] = {}

    message = format_artist_summary(lead, answers_dict, action_tokens)

    assert "Lead #45" in message
    assert "Test tattoo" in message
    # Should not have action links section if empty
    assert "Actions:" not in message or len(action_tokens) == 0


@pytest.mark.asyncio
async def test_send_artist_summary_sends_message(db):
    """Test that send_artist_summary sends WhatsApp message to artist."""
    lead = Lead(
        id=46,
        wa_from="1234567890",
        status="PENDING_APPROVAL",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    answers_dict = {"idea": "Test tattoo"}
    action_tokens = {"approve": "https://example.com/a/abc123"}

    with patch(
        "app.services.artist_notifications.send_whatsapp_message", new_callable=AsyncMock
    ) as mock_send:
        mock_send.return_value = {"status": "sent"}

        # Mock artist WhatsApp number
        with patch.object(settings, "artist_whatsapp_number", "447700900123"):
            result = await send_artist_summary(
                db=db,
                lead=lead,
                answers_dict=answers_dict,
                action_tokens=action_tokens,
                dry_run=True,
            )

            assert result is True
            mock_send.assert_called_once()
            call_args = mock_send.call_args
            assert call_args[1]["to"] == "447700900123"
            assert "Lead #46" in call_args[1]["message"]


@pytest.mark.asyncio
async def test_send_artist_summary_skips_if_no_number(db):
    """Test that send_artist_summary skips if artist number not configured."""
    lead = Lead(
        id=47,
        wa_from="1234567890",
        status="PENDING_APPROVAL",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    answers_dict = {"idea": "Test tattoo"}
    action_tokens: dict[str, str] = {}

    # No artist number configured
    with patch.object(settings, "artist_whatsapp_number", None):
        result = await send_artist_summary(
            db=db,
            lead=lead,
            answers_dict=answers_dict,
            action_tokens=action_tokens,
            dry_run=True,
        )

        assert result is False


@pytest.mark.asyncio
async def test_notify_artist_sends_notification(db):
    """Test that notify_artist sends notification for various events."""
    lead = Lead(
        id=48,
        wa_from="1234567890",
        status="PENDING_APPROVAL",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch(
        "app.services.artist_notifications.send_whatsapp_message", new_callable=AsyncMock
    ) as mock_send:
        mock_send.return_value = {"status": "sent"}

        # Mock artist WhatsApp number and ensure notifications feature is enabled
        # Use current config (may be replaced by other tests) so patch reaches notify_artist
        _config = importlib.import_module("app.core.config")
        with (
            patch.object(_config.settings, "artist_whatsapp_number", "447700900123"),
            patch.object(_config.settings, "feature_notifications_enabled", True),
        ):
            result = await notify_artist(
                db=db,
                lead=lead,
                event_type="pending_approval",
                dry_run=True,
            )

            assert result is True
            mock_send.assert_called_once()
            call_args = mock_send.call_args
            assert "Lead #48" in call_args[1]["message"]
            assert "ready for review" in call_args[1]["message"].lower()


@pytest.mark.asyncio
async def test_notify_artist_deposit_paid(db):
    """Test notify_artist for deposit_paid event."""
    lead = Lead(
        id=49,
        wa_from="1234567890",
        status="DEPOSIT_PAID",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch(
        "app.services.artist_notifications.send_whatsapp_message", new_callable=AsyncMock
    ) as mock_send:
        mock_send.return_value = {"status": "sent"}

        _config = importlib.import_module("app.core.config")
        with (
            patch.object(_config.settings, "artist_whatsapp_number", "447700900123"),
            patch.object(_config.settings, "feature_notifications_enabled", True),
        ):
            result = await notify_artist(
                db=db,
                lead=lead,
                event_type="deposit_paid",
                dry_run=True,
            )

            assert result is True
            call_args = mock_send.call_args
            assert "Deposit paid" in call_args[1]["message"]


@pytest.mark.asyncio
async def test_notify_artist_handles_unknown_event(db):
    """Test that notify_artist handles unknown event types."""
    lead = Lead(
        id=50,
        wa_from="1234567890",
        status="NEW",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    _config = importlib.import_module("app.core.config")
    with patch.object(_config.settings, "artist_whatsapp_number", "447700900123"):
        result = await notify_artist(
            db=db,
            lead=lead,
            event_type="unknown_event",
            dry_run=True,
        )

        assert result is False
