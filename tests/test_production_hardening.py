"""
Production-hardening tests: concurrency, idempotency races, latest-wins, state machine.

P0 (ship-blockers):
- Concurrent inbound must not double-advance step
- Duplicate message_id race: only one side-effect
- Confirmation summary / complete qualification / handover packet use latest per key

P1 (high-value):
- Illegal status transition raises or no-ops
- Restart-after-optout policy
- Webhook returns 200 on duplicate (no retry storm)
"""

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import select

from app.api.webhooks import whatsapp_inbound
from app.db.models import Lead, LeadAnswer, ProcessedMessage
from app.services.conversation import (
    STATUS_NEEDS_ARTIST_REPLY,
    STATUS_NEW,
    STATUS_OPTOUT,
    STATUS_PENDING_APPROVAL,
    STATUS_QUALIFYING,
    _complete_qualification,
    _maybe_send_confirmation_summary,
    handle_inbound_message,
)
from app.services.handover_packet import build_handover_packet
from app.services.leads import get_or_create_lead
from app.services.state_machine import (
    ALLOWED_TRANSITIONS,
    transition,
)
from tests.conftest import TestingSessionLocal, is_sqlite

# ---- P0: Concurrency and races ----


@pytest.mark.asyncio
@pytest.mark.skipif(
    is_sqlite(),
    reason="SQLite lacks proper concurrency; run with Postgres for conditional-UPDATE concurrency tests",
)
async def test_concurrent_inbound_does_not_double_advance_step(db):
    """
    Two handle_inbound_message calls for the same lead (same step) must not double-advance.
    Without row locking, both can read step 0 and both advance to 1 (or 2). We assert step advances once.
    """
    wa_from = "7999111222"
    lead = Lead(
        wa_from=wa_from,
        status=STATUS_QUALIFYING,
        current_step=2,  # dimensions step (0=idea, 1=placement, 2=dimensions)
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    lead_id = lead.id

    with (
        patch(
            "app.services.conversation.send_whatsapp_message", new_callable=AsyncMock
        ) as mock_send,
        patch("app.services.tour_service.is_city_on_tour", return_value=True),
        patch("app.services.handover_service.should_handover", return_value=(False, None)),
    ):
        mock_send.return_value = {"id": "wamock_1", "status": "sent"}

        db2 = TestingSessionLocal()
        try:
            lead2 = db2.get(Lead, lead_id)
            assert lead2 is not None

            async def run1():
                return await handle_inbound_message(
                    db=db,
                    lead=lead,
                    message_text="10x12 cm",
                    dry_run=True,
                )

            async def run2():
                return await handle_inbound_message(
                    db=db2,
                    lead=lead2,
                    message_text="15x15 cm",
                    dry_run=True,
                )

            await asyncio.gather(run1(), run2())
        finally:
            db2.close()

    db.refresh(lead)
    # Desired: step advanced once (2 -> 3), not twice (2 -> 4)
    assert lead.current_step == 3, (
        "Concurrent inbounds must not double-advance step; "
        f"expected current_step=3 (one advance from 2), got {lead.current_step}"
    )


@pytest.mark.asyncio
async def test_duplicate_message_id_race_only_one_processes(db):
    """
    Two concurrent webhook calls with the same message_id must result in one processing.
    ProcessedMessage uniqueness + insert-after-processing prevents double side-effects.
    """
    wa_from = "7999333444"
    message_id = "wamid.race_dup_999"
    message_text = "Hello"

    lead = get_or_create_lead(db, wa_from)
    db.commit()

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

    with (
        patch(
            "app.services.conversation.send_whatsapp_message", new_callable=AsyncMock
        ) as mock_send,
        patch("app.services.tour_service.is_city_on_tour", return_value=True),
        patch("app.services.handover_service.should_handover", return_value=(False, None)),
    ):
        mock_send.return_value = {"id": "wamock_1", "status": "sent"}

        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=json.dumps(payload).encode("utf-8"))
        mock_request.headers = {"X-Hub-Signature-256": "test_signature"}

        db2 = TestingSessionLocal()
        try:
            req1 = (mock_request, BackgroundTasks(), db)
            req2 = (MagicMock(), BackgroundTasks(), db2)
            req2[0].body = AsyncMock(return_value=json.dumps(payload).encode("utf-8"))
            req2[0].headers = {"X-Hub-Signature-256": "test_signature"}

            await asyncio.gather(
                whatsapp_inbound(req1[0], req1[1], db=req1[2]),
                whatsapp_inbound(req2[0], req2[1], db=db2),
            )
        finally:
            db2.close()

    # Only one ProcessedMessage for this message_id
    stmt = select(ProcessedMessage).where(
        ProcessedMessage.provider == "whatsapp",
        ProcessedMessage.message_id == message_id,
    )
    count = len(db.execute(stmt).scalars().all())
    assert count == 1, (
        "Duplicate message_id must be processed only once; "
        f"expected 1 ProcessedMessage, got {count}"
    )


# ---- P0: Latest-wins determinism ----


@pytest.mark.asyncio
async def test_confirmation_summary_uses_latest_per_key(db):
    """_maybe_send_confirmation_summary must use latest answer per question_key (order_by created_at, id)."""
    lead = Lead(wa_from="1234567890", status=STATUS_QUALIFYING, current_step=3)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Two dimensions answers: older then newer. Latest should win.
    a1 = LeadAnswer(lead_id=lead.id, question_key="dimensions", answer_text="10x12 cm")
    a2 = LeadAnswer(lead_id=lead.id, question_key="budget", answer_text="£500")
    a3 = LeadAnswer(lead_id=lead.id, question_key="location_city", answer_text="London")
    db.add_all([a1, a2, a3])
    db.commit()
    a4 = LeadAnswer(lead_id=lead.id, question_key="dimensions", answer_text="15x15 cm")
    db.add(a4)
    db.commit()

    # _maybe_send_confirmation_summary lives in conversation_qualifying and uses _get_send_whatsapp()
    mock_send = AsyncMock()
    with patch(
        "app.services.conversation_qualifying._get_send_whatsapp", return_value=mock_send
    ):
        sent = await _maybe_send_confirmation_summary(db, lead, "dimensions", dry_run=True)

    assert sent is True
    assert mock_send.await_count == 1
    assert mock_send.await_args is not None
    call_msg = mock_send.await_args.kwargs.get("message", "")
    assert "15" in call_msg, "Confirmation summary must use latest dimensions (15x15), not 10x12"


@pytest.mark.asyncio
async def test_complete_qualification_uses_latest_per_key(db):
    """_complete_qualification must use latest answer per key for budget (and thus below_min_budget)."""

    lead = Lead(
        wa_from="1234567890",
        status=STATUS_QUALIFYING,
        current_step=10,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Two budget answers: 400 then 600. Min for UK is 500. Latest (600) is above min.
    for qk, text in [
        ("idea", "sleeve"),
        ("placement", "arm"),
        ("dimensions", "20x25 cm"),
        ("style", "minimal"),
        ("complexity", "2"),
        ("coverup", "no"),
        ("location_city", "London"),
        ("location_country", "UK"),
        ("budget", "400"),
    ]:
        db.add(LeadAnswer(lead_id=lead.id, question_key=qk, answer_text=text))
    db.commit()
    db.add(LeadAnswer(lead_id=lead.id, question_key="budget", answer_text="600"))
    db.commit()

    with (
        patch("app.services.conversation.send_whatsapp_message", new_callable=AsyncMock),
        patch("app.services.sheets.log_lead_to_sheets"),
        patch("app.services.tour_service.is_city_on_tour", return_value=True),
    ):
        await _complete_qualification(db, lead, dry_run=True)

    db.refresh(lead)
    # Latest budget is 600; if min is 500, we should be above min
    assert lead.below_min_budget is False, (
        "Complete qualification must use latest budget (600); "
        "with min 500, below_min_budget should be False"
    )
    assert lead.status == STATUS_PENDING_APPROVAL


def test_handover_packet_answers_use_latest_per_key(db):
    """build_handover_packet must use latest answer per key for budget/size/location."""
    _assert_handover_packet_latest_per_key(db)


def test_handover_packet_uses_latest_per_key(db):
    """Alias: handover packet must use latest answer per key (same as test_handover_packet_answers_use_latest_per_key)."""
    _assert_handover_packet_latest_per_key(db)


def _assert_handover_packet_latest_per_key(db):
    lead = Lead(wa_from="1234567890", status=STATUS_NEEDS_ARTIST_REPLY)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    db.add(LeadAnswer(lead_id=lead.id, question_key="budget", answer_text="400"))
    db.add(LeadAnswer(lead_id=lead.id, question_key="dimensions", answer_text="10x12"))
    db.commit()
    db.add(LeadAnswer(lead_id=lead.id, question_key="budget", answer_text="600"))
    db.commit()

    packet = build_handover_packet(db, lead)
    assert packet["budget"]["budget_text"] == "600", (
        "Handover packet must use latest budget per key (600, not 400)"
    )


# ---- P1: State machine and restart policy ----


def test_illegal_status_transition_raises(db):
    """state_machine.transition must raise for illegal transitions (e.g. BOOKED -> QUALIFYING)."""
    from app.services.conversation import STATUS_BOOKED, STATUS_QUALIFYING

    lead = Lead(wa_from="1234567890", status=STATUS_BOOKED)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with pytest.raises(ValueError, match="Invalid status transition|not allowed"):
        transition(db, lead, STATUS_QUALIFYING)


def test_optout_cannot_transition_without_restart_rule(db):
    """State machine: OPTOUT is terminal unless we explicitly allow OPTOUT -> NEW."""
    from app.services.conversation import STATUS_NEW, STATUS_OPTOUT

    allowed = ALLOWED_TRANSITIONS.get(STATUS_OPTOUT, [])
    # If we want "opt back in", OPTOUT -> NEW must be in allowed; otherwise transition should fail
    can_restart = STATUS_NEW in allowed
    if not can_restart:
        lead = Lead(wa_from="1234567890", status=STATUS_OPTOUT)
        db.add(lead)
        db.commit()
        db.refresh(lead)
        with pytest.raises(ValueError, match="Invalid status transition|not allowed"):
            transition(db, lead, STATUS_NEW)


@pytest.mark.asyncio
async def test_restart_after_optout_policy(db):
    """Product policy: user in OPTOUT who sends START/RESUME/CONTINUE/YES gets restarted (flow restarts)."""
    lead = Lead(wa_from="1234567890", status=STATUS_OPTOUT, current_step=5)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch(
        "app.services.conversation.send_whatsapp_message", new_callable=AsyncMock
    ) as mock_send:
        result = await handle_inbound_message(
            db=db,
            lead=lead,
            message_text="START",
            dry_run=True,
        )

    db.refresh(lead)
    # Restart: status goes NEW then _handle_new_lead sets QUALIFYING and sends welcome
    assert lead.status in (STATUS_NEW, STATUS_QUALIFYING)
    assert result.get("status") != "opted_out"
    assert mock_send.await_count >= 1


# ---- P1: Webhook duplicate returns 200 ----


@pytest.mark.asyncio
async def test_webhook_returns_200_on_duplicate_message_id(db):
    """Duplicate message_id must return 200 so provider does not retry (idempotent)."""
    wa_from = "7999555666"
    message_id = "wamid.dup_200"
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
                                    "text": {"body": "Hi"},
                                    "timestamp": str(int(datetime.now(UTC).timestamp())),
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    with (
        patch("app.services.conversation.send_whatsapp_message", new_callable=AsyncMock),
        patch("app.services.tour_service.is_city_on_tour", return_value=True),
        patch("app.services.handover_service.should_handover", return_value=(False, None)),
    ):
        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=json.dumps(payload).encode("utf-8"))
        mock_request.headers = {"X-Hub-Signature-256": "test_signature"}

        r1 = await whatsapp_inbound(mock_request, BackgroundTasks(), db=db)
        r2 = await whatsapp_inbound(mock_request, BackgroundTasks(), db=db)

    assert r1.get("received") is True
    assert r2.get("received") is True
    assert r2.get("type") == "duplicate" or "processed_at" in str(r2)
