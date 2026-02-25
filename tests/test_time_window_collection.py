"""
Tests for time window collection fallback when no calendar slots available.

Tests the flow: no slots → ask for time windows → collect 2-3 → notify artist → set NEEDS_ARTIST_REPLY.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.db.models import Lead, LeadAnswer
from app.services.conversation import (
    STATUS_COLLECTING_TIME_WINDOWS,
    STATUS_NEEDS_ARTIST_REPLY,
)
from app.services.conversation.time_window_collection import (
    PREFERRED_TIME_WINDOWS_KEY,
    collect_time_window,
    count_time_windows,
    format_time_windows_request,
)


@pytest.fixture
def lead_booking_pending(db):
    """Create a lead in BOOKING_PENDING status (deposit paid, waiting for slots)."""
    lead = Lead(
        wa_from="test_time_windows",
        status="BOOKING_PENDING",
        channel="whatsapp",
        deposit_paid_at=datetime.now(UTC),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


@pytest.mark.asyncio
async def test_format_time_windows_request():
    """Test the time windows request message format."""
    message = format_time_windows_request()
    assert "2-3 preferred day/time windows" in message
    assert "timezone" in message.lower()
    assert "Monday afternoon" in message or "example" in message.lower()


@pytest.mark.asyncio
async def test_count_time_windows_empty(db, lead_booking_pending):
    """Test counting time windows when none collected."""
    count = count_time_windows(lead_booking_pending, db)
    assert count == 0


@pytest.mark.asyncio
async def test_collect_first_time_window(db, lead_booking_pending):
    """Test collecting the first time window."""
    with patch("app.services.conversation.time_window_collection.send_whatsapp_message") as mock_send:
        mock_send.return_value = {"status": "sent"}

        result = await collect_time_window(
            db=db,
            lead=lead_booking_pending,
            message_text="Monday afternoon (GMT)",
            dry_run=True,
        )

        db.refresh(lead_booking_pending)

        # Should still be collecting
        assert lead_booking_pending.status == STATUS_COLLECTING_TIME_WINDOWS
        assert result["status"] == "collecting_time_windows"
        assert result["window_count"] == 1

        # Verify answer was stored
        stmt = select(LeadAnswer).where(
            LeadAnswer.lead_id == lead_booking_pending.id,
            LeadAnswer.question_key == PREFERRED_TIME_WINDOWS_KEY,
        )
        answers = db.execute(stmt).scalars().all()
        assert len(answers) == 1
        assert answers[0].answer_text == "Monday afternoon (GMT)"

        # Should ask for more
        assert "more" in result["message"].lower()
        mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_collect_second_time_window_transitions(db, lead_booking_pending):
    """Test that collecting second time window transitions to NEEDS_ARTIST_REPLY."""
    # Add first time window
    answer1 = LeadAnswer(
        lead_id=lead_booking_pending.id,
        question_key=PREFERRED_TIME_WINDOWS_KEY,
        answer_text="Monday afternoon (GMT)",
    )
    db.add(answer1)
    db.commit()

    with patch("app.services.conversation.time_window_collection.send_whatsapp_message") as mock_send:
        with patch("app.services.integrations.artist_notifications.notify_artist_needs_reply") as mock_notify:
            mock_send.return_value = {"status": "sent"}
            mock_notify.return_value = True

            result = await collect_time_window(
                db=db,
                lead=lead_booking_pending,
                message_text="Wednesday morning (GMT)",
                dry_run=True,
            )

            db.refresh(lead_booking_pending)

            # Should transition to NEEDS_ARTIST_REPLY
            assert lead_booking_pending.status == STATUS_NEEDS_ARTIST_REPLY
            assert lead_booking_pending.handover_reason is not None
            assert "preferred time windows" in lead_booking_pending.handover_reason.lower()
            assert lead_booking_pending.needs_artist_reply_at is not None

            # Verify result
            assert result["status"] == "time_windows_collected"
            assert result["window_count"] == 2

            # Verify both answers stored
            stmt = (
                select(LeadAnswer)
                .where(
                    LeadAnswer.lead_id == lead_booking_pending.id,
                    LeadAnswer.question_key == PREFERRED_TIME_WINDOWS_KEY,
                )
                .order_by(LeadAnswer.created_at)
            )
            answers = db.execute(stmt).scalars().all()
            assert len(answers) == 2
            assert answers[0].answer_text == "Monday afternoon (GMT)"
            assert answers[1].answer_text == "Wednesday morning (GMT)"

            # Should notify artist
            mock_notify.assert_called_once()
            call_args = mock_notify.call_args
            assert call_args.kwargs["reason"] is not None
            assert "preferred time windows" in call_args.kwargs["reason"].lower()

            # Should send confirmation to client
            mock_send.assert_called_once()
            assert "received" in mock_send.call_args.kwargs["message"].lower()


@pytest.mark.asyncio
async def test_collect_third_time_window(db, lead_booking_pending):
    """Test collecting third time window also transitions."""
    # Add first two time windows
    answer1 = LeadAnswer(
        lead_id=lead_booking_pending.id,
        question_key=PREFERRED_TIME_WINDOWS_KEY,
        answer_text="Monday afternoon (GMT)",
    )
    answer2 = LeadAnswer(
        lead_id=lead_booking_pending.id,
        question_key=PREFERRED_TIME_WINDOWS_KEY,
        answer_text="Wednesday morning (GMT)",
    )
    db.add(answer1)
    db.add(answer2)
    db.commit()

    with patch("app.services.conversation.time_window_collection.send_whatsapp_message") as mock_send:
        with patch("app.services.integrations.artist_notifications.notify_artist_needs_reply") as mock_notify:
            mock_send.return_value = {"status": "sent"}
            mock_notify.return_value = True

            result = await collect_time_window(
                db=db,
                lead=lead_booking_pending,
                message_text="Friday anytime (GMT)",
                dry_run=True,
            )

            db.refresh(lead_booking_pending)

            # Should transition to NEEDS_ARTIST_REPLY
            assert lead_booking_pending.status == STATUS_NEEDS_ARTIST_REPLY
            assert result["window_count"] == 3

            # Should notify artist
            mock_notify.assert_called_once()


@pytest.mark.asyncio
async def test_artist_notification_includes_time_windows(db, lead_booking_pending):
    """Test that artist notification includes collected time windows."""
    from app.services.integrations.artist_notifications import notify_artist_needs_reply

    # Add time windows
    answer1 = LeadAnswer(
        lead_id=lead_booking_pending.id,
        question_key=PREFERRED_TIME_WINDOWS_KEY,
        answer_text="Monday afternoon (GMT)",
    )
    answer2 = LeadAnswer(
        lead_id=lead_booking_pending.id,
        question_key=PREFERRED_TIME_WINDOWS_KEY,
        answer_text="Wednesday morning (GMT)",
    )
    db.add(answer1)
    db.add(answer2)
    db.commit()

    lead_booking_pending.status = STATUS_NEEDS_ARTIST_REPLY
    lead_booking_pending.handover_reason = "Collected 2 preferred time windows"
    lead_booking_pending.needs_artist_reply_notified_at = None  # Ensure not already notified
    db.commit()

    # Patch settings at module level: avoid import-time cached values affecting test order
    mock_settings = MagicMock()
    mock_settings.artist_whatsapp_number = "test_artist_number"
    mock_settings.feature_notifications_enabled = True
    mock_settings.whatsapp_dry_run = True

    with (
        patch("app.services.integrations.artist_notifications.settings", mock_settings),
        patch(
            "app.services.integrations.artist_notifications.send_whatsapp_message", new_callable=AsyncMock
        ) as mock_send,
    ):
        mock_send.return_value = {"status": "sent"}

        await notify_artist_needs_reply(
            db=db,
            lead=lead_booking_pending,
            reason="Collected 2 preferred time windows",
            dry_run=True,
        )

        # Verify notification was sent
        mock_send.assert_called_once()
        message = mock_send.call_args.kwargs["message"]

        # Should include time windows
        assert "Preferred Time Windows" in message
        assert "Monday afternoon (GMT)" in message
        assert "Wednesday morning (GMT)" in message


@pytest.mark.asyncio
async def test_no_slots_triggers_time_window_collection(db, lead_booking_pending):
    """Test that no slots triggers time window collection flow."""
    from app.services.integrations.calendar_service import send_slot_suggestions_to_client

    async def mock_send_async(*args, **kwargs):
        return {"status": "sent"}

    with (
        patch("app.services.integrations.calendar_service.get_available_slots") as mock_slots,
        patch(
            "app.services.messaging.whatsapp_window.send_with_window_check", side_effect=mock_send_async
        ) as mock_send,
    ):
        # Return empty slots
        mock_slots.return_value = []

        result = await send_slot_suggestions_to_client(
            db=db,
            lead=lead_booking_pending,
            dry_run=True,
        )

        db.refresh(lead_booking_pending)

        # Should set status to COLLECTING_TIME_WINDOWS
        assert lead_booking_pending.status == STATUS_COLLECTING_TIME_WINDOWS

        # Should send time windows request
        assert mock_send.called
        call_kwargs = mock_send.call_args.kwargs
        message = call_kwargs["message"]
        assert "2-3 preferred day/time windows" in message

        # Should return False (no slots sent)
        assert result is False


@pytest.mark.asyncio
async def test_time_window_collection_status_handled_in_conversation(db, lead_booking_pending):
    """Test that STATUS_COLLECTING_TIME_WINDOWS is handled in conversation flow."""
    from app.services.conversation import handle_inbound_message

    # Set status to collecting time windows
    lead_booking_pending.status = STATUS_COLLECTING_TIME_WINDOWS
    db.commit()

    with patch("app.services.conversation.time_window_collection.send_whatsapp_message") as mock_send:
        mock_send.return_value = {"status": "sent"}

        result = await handle_inbound_message(
            db=db,
            lead=lead_booking_pending,
            message_text="Monday afternoon (GMT)",
            dry_run=True,
        )

        # Should handle the message and collect time window
        assert result["status"] in ["collecting_time_windows", "time_windows_collected"]
        assert "window_count" in result or "status" in result
