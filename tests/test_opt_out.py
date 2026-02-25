"""
Tests for STOP/UNSUBSCRIBE opt-out mechanism.
"""

from datetime import UTC

import pytest

from app.db.models import Lead
from app.services.conversation import (
    STATUS_OPTOUT,
    STATUS_QUALIFYING,
    handle_inbound_message,
)


def _reset_message_composer_cache():
    """Reset global composer so real app/copy is loaded (other tests may have cached temp copy)."""
    import app.services.messaging.message_composer as mc

    mc._composer = None


@pytest.mark.asyncio
async def test_stop_keyword_opts_out(db):
    """Test that STOP keyword opts out lead."""
    _reset_message_composer_cache()
    lead = Lead(wa_from="1234567890", status=STATUS_QUALIFYING, current_step=1)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    result = await handle_inbound_message(
        db=db,
        lead=lead,
        message_text="STOP",
        dry_run=True,
    )

    db.refresh(lead)
    assert lead.status == STATUS_OPTOUT
    assert result["status"] == "opted_out"
    assert "unsubscribed" in result["message"].lower()


@pytest.mark.asyncio
async def test_unsubscribe_keyword_opts_out(db):
    """Test that UNSUBSCRIBE keyword opts out lead."""
    lead = Lead(wa_from="1234567890", status=STATUS_QUALIFYING, current_step=1)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    result = await handle_inbound_message(
        db=db,
        lead=lead,
        message_text="UNSUBSCRIBE",
        dry_run=True,
    )

    db.refresh(lead)
    assert lead.status == STATUS_OPTOUT


@pytest.mark.asyncio
async def test_opt_out_variations(db):
    """Test various opt-out keyword variations."""
    variations = ["STOP", "UNSUBSCRIBE", "OPT OUT", "OPTOUT"]

    for keyword in variations:
        lead = Lead(wa_from=f"1234567890_{keyword}", status=STATUS_QUALIFYING, current_step=1)
        db.add(lead)
        db.commit()
        db.refresh(lead)

        result = await handle_inbound_message(
            db=db,
            lead=lead,
            message_text=keyword,
            dry_run=True,
        )

        db.refresh(lead)
        assert lead.status == STATUS_OPTOUT, f"Failed for keyword: {keyword}"


@pytest.mark.asyncio
async def test_opted_out_lead_blocks_messages(db):
    """Test that opted-out leads don't receive automated messages."""
    from app.services.messaging.whatsapp_window import send_with_window_check

    lead = Lead(wa_from="1234567890", status=STATUS_OPTOUT)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    result = await send_with_window_check(
        db=db,
        lead=lead,
        message="This should be blocked",
        dry_run=True,
    )

    assert result["status"] == "opted_out"
    assert "blocked" in result.get("warning", "").lower()


@pytest.mark.asyncio
async def test_opted_out_can_opt_back_in(db):
    """Test that opted-out leads can opt back in with START."""
    lead = Lead(wa_from="1234567890", status=STATUS_OPTOUT)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    result = await handle_inbound_message(
        db=db,
        lead=lead,
        message_text="START",
        dry_run=True,
    )

    db.refresh(lead)
    # After START, status transitions to NEW then immediately to QUALIFYING (correct behavior)
    assert lead.status == STATUS_QUALIFYING
    assert result["status"] == "question_sent"


@pytest.mark.asyncio
async def test_opted_out_other_messages_acknowledge(db):
    """Test that opted-out leads get acknowledgment for other messages."""
    _reset_message_composer_cache()
    lead = Lead(wa_from="1234567890", status=STATUS_OPTOUT)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    result = await handle_inbound_message(
        db=db,
        lead=lead,
        message_text="Hello?",
        dry_run=True,
    )

    assert result["status"] == "opted_out"
    assert "unsubscribed" in result["message"].lower()
    assert "START" in result["message"]


@pytest.mark.asyncio
async def test_reminder_skips_opted_out(db):
    """Test that reminders skip opted-out leads."""
    from datetime import datetime, timedelta

    from app.services.messaging.reminders import check_and_send_qualifying_reminder

    lead = Lead(
        wa_from="1234567890",
        status=STATUS_OPTOUT,  # Opted out
        last_client_message_at=datetime.now(UTC) - timedelta(hours=25),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    result = check_and_send_qualifying_reminder(
        db=db,
        lead=lead,
        reminder_number=1,
        dry_run=True,
    )

    assert result["status"] == "skipped"
    assert "opted out" in result["reason"].lower()
