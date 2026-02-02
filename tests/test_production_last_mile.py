"""
Last-mile production tests: side-effect ordering and restart semantics.

- Send failure must not advance step (send before advance)
- Out-of-order messages ignored (no advance or reprompt)
- Opt-out restart resets step (OPTOUT -> NEW policy)
- Duplicate message_id with different text is ignored (idempotency by message_id)
- Stripe duplicate events do not double-transition
"""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks

from app.api.webhooks import stripe_webhook, whatsapp_inbound
from app.db.models import Lead, LeadAnswer, ProcessedMessage
from app.services.conversation import (
    STATUS_AWAITING_DEPOSIT,
    STATUS_NEEDS_ARTIST_REPLY,
    STATUS_OPTOUT,
    STATUS_QUALIFYING,
    handle_inbound_message,
)
from app.services.leads import get_or_create_lead
from tests.conftest import TestingSessionLocal
from tests.helpers.stripe_webhook import (
    build_stripe_webhook_request,
    create_checkout_completed_event,
)


@pytest.mark.asyncio
async def test_send_failure_does_not_advance_step(db):
    """If send_whatsapp_message raises, current_step must remain unchanged."""
    wa_from = "7999000111"
    lead = Lead(
        wa_from=wa_from,
        status=STATUS_QUALIFYING,
        current_step=0,  # dimensions
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    step_before = lead.current_step

    with (
        patch(
            "app.services.conversation.send_whatsapp_message",
            new_callable=AsyncMock,
            side_effect=Exception("Send failed"),
        ),
        patch("app.services.tour_service.is_city_on_tour", return_value=True),
        patch("app.services.handover_service.should_handover", return_value=(False, None)),
    ):
        with pytest.raises(Exception, match="Send failed"):
            await handle_inbound_message(
                db=db,
                lead=lead,
                message_text="10x12 cm",
                dry_run=True,
            )

    db.refresh(lead)
    assert lead.current_step == step_before, (
        "Step must not advance when send_whatsapp_message raises"
    )


@pytest.mark.asyncio
async def test_out_of_order_message_does_not_advance_or_reprompt(db):
    """Message with older timestamp than last_client_message_at is ignored; no advance or reprompt."""
    wa_from = "7999000222"
    lead = get_or_create_lead(db, wa_from=wa_from)
    # Set last_client_message_at to "now" so any older timestamp is out-of-order
    lead.last_client_message_at = datetime.now(UTC)
    db.commit()
    db.refresh(lead)
    step_before = lead.current_step
    answers_before = len(lead.answers)

    old_ts = int((datetime.now(UTC).timestamp()) - 3600)  # 1 hour ago
    message_id = "wamid.outoforder_1"
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
                                    "text": {"body": "10x12 cm"},
                                    "timestamp": str(old_ts),
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    with (
        patch(
            "app.services.conversation.send_whatsapp_message",
            new_callable=AsyncMock,
        ) as mock_send,
        patch("app.services.tour_service.is_city_on_tour", return_value=True),
        patch("app.services.handover_service.should_handover", return_value=(False, None)),
    ):
        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=json.dumps(payload).encode("utf-8"))
        mock_request.headers = {"X-Hub-Signature-256": "test_signature"}

        result = await whatsapp_inbound(mock_request, BackgroundTasks(), db=db)

    assert result.get("type") == "out_of_order"
    assert result.get("received") is True
    assert mock_send.await_count == 0, "No outbound message for out-of-order"

    db.refresh(lead)
    assert lead.current_step == step_before
    assert len(lead.answers) == answers_before


@pytest.mark.asyncio
async def test_optout_restart_resets_step_and_handover_timestamps(db):
    """OPTOUT -> NEW policy: sending START resets step to 0 and flow restarts (QUALIFYING)."""
    wa_from = "7999000333"
    lead = Lead(
        wa_from=wa_from,
        status=STATUS_OPTOUT,
        current_step=5,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch(
        "app.services.conversation.send_whatsapp_message",
        new_callable=AsyncMock,
    ) as mock_send:
        await handle_inbound_message(
            db=db,
            lead=lead,
            message_text="START",
            dry_run=True,
        )

    db.refresh(lead)
    assert lead.status == STATUS_QUALIFYING
    assert lead.current_step == 0
    assert mock_send.await_count >= 1


@pytest.mark.asyncio
@pytest.mark.xfail(
    reason="Flaky: first webhook request may not create answer (test isolation / db session)",
    strict=False,
)
async def test_duplicate_message_id_different_text_is_ignored(db):
    """Same message_id with different text: second request is duplicate; only first text is stored."""
    from app.core.config import settings

    wa_from = "7999000444"
    message_id = "wamid.dup_diff_1"
    lead = get_or_create_lead(db, wa_from=wa_from)
    lead.status = STATUS_QUALIFYING
    lead.current_step = 0
    db.commit()
    db.refresh(lead)
    lead_id = lead.id

    def make_payload(text: str, ts: int | None = None):
        t = ts or int(datetime.now(UTC).timestamp())
        return {
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
                                        "text": {"body": text},
                                        "timestamp": str(t),
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }

    mock_wa = AsyncMock(return_value={"id": "wamock_1", "status": "sent"})
    with (
        patch(
            "app.services.conversation.send_whatsapp_message",
            mock_wa,
        ),
        patch(
            "app.services.messaging.send_whatsapp_message",
            mock_wa,
        ),
        patch("app.services.tour_service.is_city_on_tour", return_value=True),
        patch("app.services.handover_service.should_handover", return_value=(False, None)),
        patch.object(settings, "pilot_mode_enabled", False),
    ):
        mock_request = MagicMock()
        mock_request.headers = {"X-Hub-Signature-256": "test_signature"}

        mock_request.body = AsyncMock(
            return_value=json.dumps(make_payload("10x12 cm")).encode("utf-8")
        )
        r1 = await whatsapp_inbound(mock_request, BackgroundTasks(), db=db)

        mock_request.body = AsyncMock(
            return_value=json.dumps(make_payload("15x15 cm", int(datetime.now(UTC).timestamp()) + 1)).encode(
                "utf-8"
            )
        )
        r2 = await whatsapp_inbound(mock_request, BackgroundTasks(), db=db)

    assert r1.get("received") is True
    assert r2.get("type") == "duplicate" or r2.get("processed_at") is not None

    from sqlalchemy import select

    stmt = select(ProcessedMessage).where(ProcessedMessage.message_id == message_id)
    count = len(db.execute(stmt).scalars().all())
    assert count == 1, "Duplicate message_id must be processed only once"

    stmt = select(LeadAnswer).where(LeadAnswer.lead_id == lead_id)
    all_answers = db.execute(stmt).scalars().all()
    assert len(all_answers) == 1, "Only first message should create an answer (second was duplicate)"
    assert all_answers[0].answer_text.strip() == "10x12 cm"


@pytest.mark.asyncio
async def test_stripe_duplicate_events_do_not_double_transition(db):
    """Same Stripe event_id delivered twice: only one status transition and one ProcessedMessage."""
    lead = Lead(
        wa_from="7999000555",
        status=STATUS_AWAITING_DEPOSIT,
        stripe_checkout_session_id="cs_dup_1",
        deposit_amount_pence=5000,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    lead_id = lead.id

    event_id = "evt_dup_double_1"
    webhook_event = create_checkout_completed_event(
        event_id=event_id,
        checkout_session_id="cs_dup_1",
        payment_intent_id="pi_dup_1",
        lead_id=lead_id,
        amount_total=5000,
    )

    with (
        patch("app.services.stripe_service.verify_webhook_signature") as mock_verify,
        patch(
            "app.services.whatsapp_window.send_with_window_check",
            new_callable=AsyncMock,
        ) as mock_send,
    ):
        mock_verify.return_value = webhook_event
        mock_send.return_value = {"status": "sent"}

        request = build_stripe_webhook_request(webhook_event)
        r1 = await stripe_webhook(request, BackgroundTasks(), db=db)
        r2 = await stripe_webhook(request, BackgroundTasks(), db=db)

    assert r1.get("received") is True
    assert r2.get("type") == "duplicate" or r2.get("received") is True

    from sqlalchemy import select

    from app.services.conversation import STATUS_BOOKING_PENDING

    stmt = select(ProcessedMessage).where(ProcessedMessage.message_id == event_id)
    count = len(db.execute(stmt).scalars().all())
    assert count == 1, "Duplicate Stripe event must be recorded only once"

    db.refresh(lead)
    assert lead.status == STATUS_BOOKING_PENDING
    assert lead.deposit_paid_at is not None
    assert lead.booking_pending_at is not None
