"""
Tests for WhatsApp 24-hour window handling.
"""
import pytest
from datetime import datetime, timedelta, timezone
from app.db.models import Lead
from app.services.whatsapp_window import (
    is_within_24h_window,
    send_with_window_check,
)
from app.services.conversation import STATUS_QUALIFYING


def test_is_within_24h_window_within_window():
    """Test window check when within 24 hours."""
    lead = Lead(
        wa_from="1234567890",
        last_client_message_at=datetime.now(timezone.utc) - timedelta(hours=12),
    )
    
    is_within, expires_at = is_within_24h_window(lead)
    assert is_within is True
    assert expires_at is not None
    assert expires_at > datetime.now(timezone.utc)


def test_is_within_24h_window_expired():
    """Test window check when 24 hours have passed."""
    lead = Lead(
        wa_from="1234567890",
        last_client_message_at=datetime.now(timezone.utc) - timedelta(hours=25),
    )
    
    is_within, expires_at = is_within_24h_window(lead)
    assert is_within is False
    assert expires_at is not None
    assert expires_at < datetime.now(timezone.utc)


def test_is_within_24h_window_no_last_message():
    """Test window check when no previous message (window is open)."""
    lead = Lead(wa_from="1234567890", last_client_message_at=None)
    
    is_within, expires_at = is_within_24h_window(lead)
    assert is_within is True
    assert expires_at is None


@pytest.mark.asyncio
async def test_send_with_window_check_within_window(db):
    """Test sending message when window is open."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_QUALIFYING,
        last_client_message_at=datetime.now(timezone.utc) - timedelta(hours=12),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    result = await send_with_window_check(
        db=db,
        lead=lead,
        message="Test message",
        dry_run=True,
    )
    
    assert result["window_status"] == "open"
    assert result["status"] in ["dry_run", "sent"]


@pytest.mark.asyncio
async def test_send_with_window_check_expired_no_template(db):
    """Test sending message when window expired and no template."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_QUALIFYING,
        last_client_message_at=datetime.now(timezone.utc) - timedelta(hours=25),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    result = await send_with_window_check(
        db=db,
        lead=lead,
        message="Test message",
        dry_run=True,
    )
    
    assert result["window_status"] == "closed"
    assert result["status"] == "window_closed_no_template"
    assert "warning" in result


@pytest.mark.asyncio
async def test_send_with_window_check_expired_with_template(db):
    """Test sending message when window expired but template available."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_QUALIFYING,
        last_client_message_at=datetime.now(timezone.utc) - timedelta(hours=25),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    result = await send_with_window_check(
        db=db,
        lead=lead,
        message="Test message",
        template_name="test_template",
        template_params={"param1": "value1"},
        dry_run=True,
    )
    
    assert result["window_status"] == "closed_template_used"
    assert result["status"] in ["dry_run_template", "sent_template"]
    assert result.get("template_name") == "test_template"
