"""
Split-regression tests: lock invariants introduced by the conversation split.

- Late-binding: qualifying and booking resolve send_whatsapp from conversation_deps at call time,
  so tests that patch messaging.send_whatsapp_message keep working.
- Dispatch: orchestrator routes by lead.status to the correct handler module
  (qualifying vs booking).
"""

from unittest.mock import patch

import pytest

from app.constants.statuses import STATUS_BOOKING_PENDING, STATUS_QUALIFYING
from app.db.models import Lead


def test_split_late_binding_respects_conversation_send_whatsapp_patch(monkeypatch):
    """Split invariant: _get_send_whatsapp() in qualifying and booking resolve at call time from conversation_deps."""
    from app.services.conversation import conversation_booking, conversation_qualifying
    from app.services.messaging import messaging

    def fake_send(*args, **kwargs):
        return None

    monkeypatch.setattr(messaging, "send_whatsapp_message", fake_send, raising=True)

    assert conversation_qualifying._get_send_whatsapp() is fake_send
    assert conversation_booking._get_send_whatsapp() is fake_send


@pytest.mark.asyncio
async def test_handle_inbound_message_dispatches_by_status_to_qualifying_and_booking(
    db, monkeypatch
):
    """Split invariant: QUALIFYING routes to _handle_qualifying_lead, BOOKING_PENDING to _handle_booking_pending."""
    from app.core.config import settings
    from app.services.conversation import handle_inbound_message

    monkeypatch.setattr(settings, "feature_panic_mode_enabled", False)

    lead_q = Lead(wa_from="447700900001", status=STATUS_QUALIFYING, current_step=0)
    lead_b = Lead(wa_from="447700900002", status=STATUS_BOOKING_PENDING, current_step=10)
    db.add(lead_q)
    db.add(lead_b)
    db.commit()
    db.refresh(lead_q)
    db.refresh(lead_b)

    calls = {"qualifying": 0, "booking_pending": 0}

    async def mock_qualifying(*args, **kwargs):
        calls["qualifying"] += 1
        lead = args[1]
        return {"status": "ok", "lead_status": lead.status}

    async def mock_booking_pending(*args, **kwargs):
        calls["booking_pending"] += 1
        lead = args[1]
        return {"status": "ok", "lead_status": lead.status}

    with (
        patch(
            "app.services.conversation.conversation._handle_qualifying_lead",
            new=mock_qualifying,
        ),
        patch(
            "app.services.conversation.conversation._handle_booking_pending",
            new=mock_booking_pending,
        ),
    ):
        await handle_inbound_message(db=db, lead=lead_q, message_text="hi", dry_run=True)
        await handle_inbound_message(db=db, lead=lead_b, message_text="hi", dry_run=True)

    assert calls["qualifying"] == 1
    assert calls["booking_pending"] == 1
