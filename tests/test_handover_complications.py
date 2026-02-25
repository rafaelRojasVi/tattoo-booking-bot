"""
Handover complications: opt-out during handover, no advance, idempotency, Stripe during handover.

Tests that:
- Opt-out (STOP) works even when lead is in NEEDS_ARTIST_REPLY
- Inbound messages during handover do not advance step or send next question
- Duplicate message ID results in one artist notification
- Resume (CONTINUE) returns to correct question
- Stripe payment updates status even if lead is in NEEDS_ARTIST_REPLY
- Handover packet and notification include name and contact
"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks

from app.api.webhooks import stripe_webhook, whatsapp_inbound
from app.db.models import Lead, LeadAnswer
from app.services.conversation import (
    HANDOVER_HOLD_REPLY_COOLDOWN_HOURS,
    STATUS_NEEDS_ARTIST_REPLY,
    STATUS_OPTOUT,
    STATUS_QUALIFYING,
    handle_inbound_message,
)
from app.services.conversation.handover_packet import build_handover_packet
from tests.helpers.stripe_webhook import (
    build_stripe_webhook_request,
    create_checkout_completed_event,
)


@pytest.mark.asyncio
async def test_opt_out_works_even_during_handover(db):
    """STOP/UNSUBSCRIBE must be honored even when lead is in NEEDS_ARTIST_REPLY."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_NEEDS_ARTIST_REPLY,
        current_step=3,
        handover_reason="Client asked for human",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch(
        "app.services.messaging.messaging.send_whatsapp_message", new_callable=AsyncMock
    ) as mock_send:
        result = await handle_inbound_message(
            db=db,
            lead=lead,
            message_text="STOP",
            dry_run=True,
        )

    db.refresh(lead)
    assert lead.status == STATUS_OPTOUT
    assert result["status"] == "opted_out"
    assert "lead_status" in result
    assert result["lead_status"] == STATUS_OPTOUT


@pytest.mark.asyncio
async def test_handover_stop_does_not_send_holding_reply(db):
    """STOP during handover: opt-out only, no holding reply sent."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_NEEDS_ARTIST_REPLY,
        current_step=3,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch(
        "app.services.messaging.messaging.send_whatsapp_message", new_callable=AsyncMock
    ) as mock_send:
        result = await handle_inbound_message(
            db=db,
            lead=lead,
            message_text="STOP",
            dry_run=True,
        )

    db.refresh(lead)
    assert lead.status == STATUS_OPTOUT
    assert result["status"] == "opted_out"
    # Exactly one send: the opt-out ack, not the holding "I've paused..." message
    assert mock_send.await_count == 1
    call_args = mock_send.await_args
    assert call_args is not None
    msg = call_args.kwargs.get("message", call_args[0][1] if call_args[0] else "")
    assert "paused" not in msg.lower(), "Holding reply must not be sent when client sends STOP"


@pytest.mark.asyncio
async def test_handover_state_does_not_advance_on_inbound_message(db):
    """Client message while NEEDS_ARTIST_REPLY must not change step index."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_NEEDS_ARTIST_REPLY,
        current_step=4,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    step_before = lead.current_step

    with patch(
        "app.services.messaging.messaging.send_whatsapp_message", new_callable=AsyncMock
    ) as mock_send:
        result = await handle_inbound_message(
            db=db,
            lead=lead,
            message_text="When can I get an appointment?",
            dry_run=True,
        )

    db.refresh(lead)
    assert lead.status == STATUS_NEEDS_ARTIST_REPLY
    assert lead.current_step == step_before
    assert result["status"] == "artist_reply"


@pytest.mark.asyncio
async def test_handover_state_does_not_send_questions(db):
    """While in handover, bot must not send 'next question' - only holding message."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_NEEDS_ARTIST_REPLY,
        current_step=2,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch(
        "app.services.messaging.messaging.send_whatsapp_message", new_callable=AsyncMock
    ) as mock_send:
        await handle_inbound_message(
            db=db,
            lead=lead,
            message_text="hello",
            dry_run=True,
        )

    # With rate-limit: first message sends holding reply (1 call)
    assert mock_send.await_count == 1
    call_args = mock_send.await_args
    assert call_args is not None
    msg = call_args.kwargs.get("message", call_args[0][1] if call_args[0] else "")
    assert "paused" in msg.lower() or "artist" in msg.lower()


@pytest.mark.asyncio
async def test_handover_holding_reply_rate_limited(db):
    """Second message within cooldown must not send another holding reply."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_NEEDS_ARTIST_REPLY,
        current_step=1,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch(
        "app.services.messaging.messaging.send_whatsapp_message", new_callable=AsyncMock
    ) as mock_send:
        await handle_inbound_message(
            db=db,
            lead=lead,
            message_text="hello",
            dry_run=True,
        )
        assert mock_send.await_count == 1

        # Second message within cooldown: no additional send
        await handle_inbound_message(
            db=db,
            lead=lead,
            message_text="are you there?",
            dry_run=True,
        )

    assert mock_send.await_count == 1


@pytest.mark.asyncio
async def test_handover_holding_reply_sent_again_after_cooldown(db):
    """After cooldown window, next message gets holding reply again."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_NEEDS_ARTIST_REPLY,
        current_step=1,
        handover_last_hold_reply_at=datetime.now(UTC)
        - timedelta(hours=HANDOVER_HOLD_REPLY_COOLDOWN_HOURS + 1),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch(
        "app.services.messaging.messaging.send_whatsapp_message", new_callable=AsyncMock
    ) as mock_send:
        await handle_inbound_message(
            db=db,
            lead=lead,
            message_text="hello again",
            dry_run=True,
        )

    assert mock_send.await_count == 1
    db.refresh(lead)
    assert lead.handover_last_hold_reply_at is not None


@pytest.mark.asyncio
async def test_handover_holding_reply_cooldown_boundary(db):
    """Exactly 6h since last hold: should send again (>= 6h policy)."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_NEEDS_ARTIST_REPLY,
        current_step=1,
        handover_last_hold_reply_at=datetime.now(UTC)
        - timedelta(hours=HANDOVER_HOLD_REPLY_COOLDOWN_HOURS),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch(
        "app.services.messaging.messaging.send_whatsapp_message", new_callable=AsyncMock
    ) as mock_send:
        await handle_inbound_message(
            db=db,
            lead=lead,
            message_text="hello",
            dry_run=True,
        )

    assert mock_send.await_count == 1
    db.refresh(lead)
    assert lead.handover_last_hold_reply_at is not None


@pytest.mark.asyncio
async def test_handover_notification_idempotent_duplicate_message_id(db):
    """Same message_id delivered twice: artist gets one notification, status stable."""
    wa_from = "1111222233"
    message_id = "wamid.handover_dup_456"
    message_text = "ARTIST"

    # Lead must be QUALIFYING so "ARTIST" goes through to should_handover (not NEW -> _handle_new_lead)
    lead = Lead(
        wa_from=wa_from,
        status=STATUS_QUALIFYING,
        current_step=1,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with (
        patch(
            "app.services.messaging.messaging.send_whatsapp_message", new_callable=AsyncMock
        ) as mock_whatsapp,
        patch("app.services.conversation.tour_service.is_city_on_tour", return_value=True),
        patch(
            "app.services.conversation.handover_service.should_handover",
            return_value=(True, "Client requested artist handover"),
        ),
        patch(
            "app.services.integrations.artist_notifications.notify_artist_needs_reply",
            new_callable=AsyncMock,
        ) as mock_notify,
    ):
        mock_whatsapp.return_value = {"id": "wamock_1", "status": "sent"}
        mock_notify.return_value = True

        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "id": message_id,
                                        "from": wa_from,
                                        "type": "text",
                                        "text": {"body": message_text},
                                        "timestamp": str(int(datetime.now(UTC).timestamp())),
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=json.dumps(payload).encode("utf-8"))
        mock_request.headers = {"X-Hub-Signature-256": "test_signature"}

        await whatsapp_inbound(mock_request, BackgroundTasks(), db=db)
        db.refresh(lead)
        assert lead.status == STATUS_NEEDS_ARTIST_REPLY
        first_notify_count = mock_notify.await_count

        # Duplicate: same message_id
        await whatsapp_inbound(mock_request, BackgroundTasks(), db=db)
        db.refresh(lead)

        # Artist notified once; second delivery skipped by ProcessedMessage
        assert mock_notify.await_count == first_notify_count
        assert lead.status == STATUS_NEEDS_ARTIST_REPLY


@pytest.mark.asyncio
async def test_handover_resume_returns_to_correct_question(db):
    """After CONTINUE from NEEDS_ARTIST_REPLY, bot asks the question at current_step."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_NEEDS_ARTIST_REPLY,
        current_step=2,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch(
        "app.services.messaging.messaging.send_whatsapp_message", new_callable=AsyncMock
    ) as mock_send:
        result = await handle_inbound_message(
            db=db,
            lead=lead,
            message_text="CONTINUE",
            dry_run=True,
        )

    db.refresh(lead)
    assert lead.status == STATUS_QUALIFYING
    assert result["status"] == "resumed"
    assert result.get("current_step") == 2
    assert mock_send.await_count == 1
    # Message should be the next question (step 2), not step 0
    call_args = mock_send.await_args
    assert call_args is not None
    msg = call_args.kwargs.get("message", "")
    assert msg  # resumed with question text


@pytest.mark.asyncio
async def test_stripe_webhook_updates_status_even_if_handover_active(db):
    """Lead in NEEDS_ARTIST_REPLY + checkout session: payment event must update to DEPOSIT_PAID/BOOKING_PENDING."""
    lead = Lead(
        id=1,
        wa_from="1234567890",
        status=STATUS_NEEDS_ARTIST_REPLY,
        deposit_amount_pence=5000,
        stripe_checkout_session_id="cs_test_handover_123",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    event_id = "evt_handover_payment_1"
    webhook_event = create_checkout_completed_event(
        event_id=event_id,
        checkout_session_id="cs_test_handover_123",
        payment_intent_id="pi_test_handover_1",
        lead_id=1,
        amount_total=5000,
    )

    with (
        patch("app.services.integrations.stripe_service.verify_webhook_signature") as mock_verify,
        patch(
            "app.services.messaging.whatsapp_window.send_with_window_check", new_callable=AsyncMock
        ) as mock_send,
        patch(
            "app.services.integrations.artist_notifications.notify_artist", new_callable=AsyncMock
        ) as mock_notify,
    ):
        mock_verify.return_value = webhook_event
        mock_send.return_value = {"status": "sent"}
        mock_notify.return_value = {"status": "sent"}

        request = build_stripe_webhook_request(webhook_event)
        result = await stripe_webhook(request, BackgroundTasks(), db=db)

    db.refresh(lead)
    assert result.get("received") is True
    # Webhook updates NEEDS_ARTIST_REPLY -> DEPOSIT_PAID then sets BOOKING_PENDING
    from app.services.conversation import STATUS_BOOKING_PENDING

    assert lead.status == STATUS_BOOKING_PENDING


def test_handover_packet_includes_name_and_contact(db):
    """Handover packet must include wa_from (contact) and client_name when available."""
    lead = Lead(
        wa_from="447700900123",
        status=STATUS_NEEDS_ARTIST_REPLY,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    ans = LeadAnswer(lead_id=lead.id, question_key="name", answer_text="Alex")
    db.add(ans)
    db.commit()
    db.refresh(lead)

    packet = build_handover_packet(db, lead)

    assert packet["wa_from"] == "447700900123"
    assert "client_name" in packet
    assert packet["client_name"] == "Alex"


@pytest.mark.asyncio
async def test_notify_artist_needs_reply_includes_name_and_contact(db):
    """Artist notification message includes Contact (wa_from) and Name (from answers or —)."""
    from app.core.config import settings
    from app.services.integrations.artist_notifications import notify_artist_needs_reply

    lead = Lead(
        id=1,
        wa_from="447700900999",
        status=STATUS_NEEDS_ARTIST_REPLY,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    ans = LeadAnswer(lead_id=lead.id, question_key="client_name", answer_text="Jordan")
    db.add(ans)
    db.commit()
    db.refresh(lead)

    with (
        patch(
            "app.services.integrations.artist_notifications.send_whatsapp_message", new_callable=AsyncMock
        ) as mock_send,
        patch.object(settings, "artist_whatsapp_number", "+449999999999"),
    ):
        await notify_artist_needs_reply(
            db=db,
            lead=lead,
            reason="Parse failure: dimensions",
            dry_run=False,
        )

    assert mock_send.await_count == 1
    call_args = mock_send.await_args
    assert call_args is not None
    msg = call_args.kwargs.get("message", "")
    assert "447700900999" in msg
    assert "Jordan" in msg
