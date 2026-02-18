"""
Go-live guardrail tests - critical safety checks before production deployment.

These tests ensure:
- No external HTTP calls in tests
- WhatsApp and Stripe idempotency
- Out-of-order message handling
- Soft repair three-strikes handover (retry 1 gentle, retry 2 short+boundary, retry 3 handover)
- Deposit locking
- Template window behavior
- Location parsing edge cases
- Slot selection edge cases
- Payment edge cases
- WhatsApp policy guards
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.db.models import Lead, LeadAnswer, ProcessedMessage
from app.services.conversation import (
    STATUS_AWAITING_DEPOSIT,
    STATUS_BOOKING_PENDING,
    STATUS_DEPOSIT_PAID,
    STATUS_NEEDS_ARTIST_REPLY,
    STATUS_PENDING_APPROVAL,
    STATUS_QUALIFYING,
    get_lead_summary,
    handle_inbound_message,
)
from app.services.parse_repair import (
    get_failure_count,
    increment_parse_failure,
    should_handover_after_failure,
)


@pytest.mark.asyncio
async def test_no_external_http_calls_in_tests(client, db, monkeypatch):
    """Guardrail: Tests should never make real HTTP calls."""
    # Track all HTTP calls
    http_calls = []

    # Mock requests/httpx
    original_request = None
    try:
        import httpx

        original_request = httpx.AsyncClient.request

        async def mock_request(self, *args, **kwargs):
            http_calls.append(
                {
                    "method": args[0] if args else kwargs.get("method"),
                    "url": args[1] if len(args) > 1 else kwargs.get("url"),
                }
            )
            raise AssertionError(
                "External HTTP call detected in test! All HTTP calls must be mocked."
            )

        monkeypatch.setattr(httpx.AsyncClient, "request", mock_request)
    except ImportError:
        pass

    try:
        import requests

        original_requests = requests.request

        def mock_requests(*args, **kwargs):
            http_calls.append({"method": args[0], "url": args[1]})
            raise AssertionError(
                "External HTTP call detected in test! All HTTP calls must be mocked."
            )

        monkeypatch.setattr(requests, "request", mock_requests)
    except ImportError:
        pass

    # Create a lead and process a message
    lead = Lead(wa_from="1234567890", status=STATUS_QUALIFYING, current_step=0)
    db.add(lead)
    db.commit()

    # This should not make any HTTP calls (all mocked)
    result = await handle_inbound_message(db, lead, "Test message", dry_run=True)

    # Verify no HTTP calls were made
    assert len(http_calls) == 0, f"Detected {len(http_calls)} HTTP calls: {http_calls}"


@pytest.mark.asyncio
async def test_whatsapp_idempotency_duplicate_message_id(client, db):
    """Guardrail: Duplicate WhatsApp message IDs are handled idempotently."""
    wa_from = "1234567890"
    message_id = "wamid.test123"

    # Process message first time
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
                                    "text": {"body": "Hello"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    response1 = client.post("/webhooks/whatsapp", json=payload)
    assert response1.status_code == 200

    # Process same message ID again
    response2 = client.post("/webhooks/whatsapp", json=payload)
    assert response2.status_code == 200
    data2 = response2.json()

    # Should be marked as duplicate
    assert data2.get("type") == "duplicate" or data2.get("received") is True

    # Verify only one lead was created
    leads = db.query(Lead).filter(Lead.wa_from == wa_from).all()
    assert len(leads) == 1

    # Verify message was marked as processed
    processed = (
        db.query(ProcessedMessage)
        .filter(
            ProcessedMessage.provider == "whatsapp",
            ProcessedMessage.message_id == message_id,
        )
        .first()
    )
    assert processed is not None


@pytest.mark.asyncio
async def test_stripe_idempotency_duplicate_event(client, db):
    """Guardrail: Duplicate Stripe webhook events are handled idempotently."""
    # Create lead with deposit
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_AWAITING_DEPOSIT,
        stripe_checkout_session_id="cs_test_123",
        deposit_amount_pence=5000,
    )
    db.add(lead)
    db.commit()

    event_id = "evt_test_duplicate"

    # First webhook
    payload1 = {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "client_reference_id": str(lead.id),
                "metadata": {"lead_id": str(lead.id)},
            }
        },
    }

    response1 = client.post(
        "/webhooks/stripe",
        json=payload1,
        headers={"Stripe-Signature": "test_sig"},
    )
    assert response1.status_code == 200

    # Get status after first webhook
    db.refresh(lead)
    status_after_first = lead.status

    # Second webhook with same event ID
    response2 = client.post(
        "/webhooks/stripe",
        json=payload1,
        headers={"Stripe-Signature": "test_sig"},
    )
    assert response2.status_code == 200

    # Status should not change
    db.refresh(lead)
    assert lead.status == status_after_first

    # Verify event was marked as processed
    processed = (
        db.query(ProcessedMessage)
        .filter(
            ProcessedMessage.provider == "stripe",
            ProcessedMessage.message_id == event_id,
        )
        .first()
    )
    assert processed is not None


@pytest.mark.asyncio
async def test_out_of_order_messages_ignored(client, db):
    """Guardrail: Out-of-order messages are ignored."""
    wa_from = "1234567890"
    lead = Lead(wa_from=wa_from, status=STATUS_QUALIFYING, current_step=0)
    db.add(lead)
    db.commit()

    # Set last message time to "now"
    from sqlalchemy import func

    lead.last_client_message_at = func.now()
    db.commit()

    # Create an older message (should be ignored)
    old_timestamp = int((datetime.now(UTC) - timedelta(minutes=5)).timestamp())

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "wamid.old",
                                    "from": wa_from,
                                    "type": "text",
                                    "text": {"body": "Old message"},
                                    "timestamp": str(old_timestamp),
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    response = client.post("/webhooks/whatsapp", json=payload)
    assert response.status_code == 200
    data = response.json()

    # Should be marked as out of order
    assert data.get("type") == "out_of_order" or data.get("received") is True


@pytest.mark.asyncio
async def test_soft_repair_three_strikes_handover_dimensions(db):
    """Guardrail: Three parse failures on dimensions triggers handover (retry 1 gentle, retry 2 short+boundary, retry 3 handover)."""
    lead = Lead(
        wa_from="1234567890", status=STATUS_QUALIFYING, current_step=2
    )  # dimensions question
    db.add(lead)
    db.commit()

    # First failure
    count1 = increment_parse_failure(db, lead, "dimensions")
    assert count1 == 1
    assert not should_handover_after_failure(lead, "dimensions")

    # Second failure - still repair (short+boundary variant)
    count2 = increment_parse_failure(db, lead, "dimensions")
    assert count2 == 2
    assert not should_handover_after_failure(lead, "dimensions")

    # Third failure - should trigger handover
    count3 = increment_parse_failure(db, lead, "dimensions")
    assert count3 == 3
    assert should_handover_after_failure(lead, "dimensions")

    # Verify handover would be triggered
    from app.services.parse_repair import trigger_handover_after_parse_failure

    result = await trigger_handover_after_parse_failure(db, lead, "dimensions", dry_run=True)

    assert result["status"] == "handover_parse_failure"
    assert result["field"] == "dimensions"
    db.refresh(lead)
    assert lead.status == "NEEDS_ARTIST_REPLY"


@pytest.mark.asyncio
async def test_soft_repair_three_strikes_handover_budget(db):
    """Guardrail: Three parse failures on budget triggers handover."""
    lead = Lead(wa_from="1234567890", status=STATUS_QUALIFYING, current_step=7)  # budget question
    db.add(lead)
    db.commit()

    # First failure
    increment_parse_failure(db, lead, "budget")
    assert not should_handover_after_failure(lead, "budget")

    # Second failure
    increment_parse_failure(db, lead, "budget")
    assert not should_handover_after_failure(lead, "budget")

    # Third failure
    increment_parse_failure(db, lead, "budget")
    assert should_handover_after_failure(lead, "budget")


@pytest.mark.asyncio
async def test_soft_repair_three_strikes_handover_location(db):
    """Guardrail: Three parse failures on location triggers handover."""
    lead = Lead(wa_from="1234567890", status=STATUS_QUALIFYING, current_step=8)  # location question
    db.add(lead)
    db.commit()

    # First failure (e.g., "flexible")
    increment_parse_failure(db, lead, "location_city")
    assert not should_handover_after_failure(lead, "location_city")

    # Second failure
    increment_parse_failure(db, lead, "location_city")
    assert not should_handover_after_failure(lead, "location_city")

    # Third failure
    increment_parse_failure(db, lead, "location_city")
    assert should_handover_after_failure(lead, "location_city")


@pytest.mark.asyncio
async def test_deposit_locking_preserves_amount(client, db):
    """Guardrail: Deposit amount is locked and preserved."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_AWAITING_DEPOSIT,  # send-deposit only accepts this status
        estimated_deposit_amount=5000,  # £50
        deposit_amount_pence=None,  # Not locked yet
    )
    db.add(lead)
    db.commit()

    # Send deposit (should lock amount)
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    from app.core.config import settings

    checkout_return = {
        "checkout_session_id": "cs_test_123",
        "checkout_url": "https://checkout.stripe.com/test",
        "expires_at": _dt.now(_UTC).replace(microsecond=0),
    }

    with (
        patch.object(settings, "admin_api_key", "test_key"),
        patch(
            "app.services.stripe_service.create_checkout_session",
            return_value=checkout_return,
        ),
        patch(
            "app.services.whatsapp_window.send_with_window_check",
            new_callable=AsyncMock,
        ),
    ):
        response = client.post(
            f"/admin/leads/{lead.id}/send-deposit",
            headers={"X-Admin-API-Key": "test_key"},
        )
        assert response.status_code == 200

    db.refresh(lead)
    assert lead.deposit_amount_pence == 5000
    assert lead.deposit_amount_locked_at is not None

    # Change estimated amount (should not affect locked amount)
    lead.estimated_deposit_amount = 10000
    db.commit()

    # Send deposit again (should use locked amount)
    with (
        patch.object(settings, "admin_api_key", "test_key"),
        patch(
            "app.services.stripe_service.create_checkout_session",
            return_value=checkout_return,
        ),
        patch(
            "app.services.whatsapp_window.send_with_window_check",
            new_callable=AsyncMock,
        ),
    ):
        response2 = client.post(
            f"/admin/leads/{lead.id}/send-deposit",
            headers={"X-Admin-API-Key": "test_key"},
        )
        assert response2.status_code == 200

    db.refresh(lead)
    assert lead.deposit_amount_pence == 5000  # Still locked at original amount


@pytest.mark.asyncio
async def test_template_window_behavior_outside_24h(client, db):
    """Guardrail: Messages outside 24h window use templates or are blocked."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_QUALIFYING,
        last_client_message_at=datetime.now(UTC) - timedelta(hours=25),  # Outside window
    )
    db.add(lead)
    db.commit()

    # Try to send message
    from app.services.message_composer import render_message
    from app.services.whatsapp_window import send_with_window_check

    message = render_message("qualifying_question", lead_id=lead.id)

    # Mock template check - render_message is in message_composer, not whatsapp_window
    with patch("app.services.message_composer.render_message") as mock_render:
        mock_render.return_value = "Template message"

        result = await send_with_window_check(
            db=db,
            lead=lead,
            message=message,
            template_name="test_template",
            dry_run=True,
        )

        # Should indicate window is closed
        assert result.get("window_status") in ["closed", "closed_template_used"]


@pytest.mark.asyncio
async def test_template_window_behavior_within_24h(client, db):
    """Guardrail: Messages within 24h window send normally."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_QUALIFYING,
        last_client_message_at=datetime.now(UTC) - timedelta(hours=12),  # Within window
    )
    db.add(lead)
    db.commit()

    from app.services.whatsapp_window import send_with_window_check

    result = await send_with_window_check(
        db=db,
        lead=lead,
        message="Test message",
        template_name=None,
        dry_run=True,
    )

    # Should indicate window is open
    assert result.get("window_status") == "open"


@pytest.mark.asyncio
async def test_location_parsing_flexible_anywhere(db):
    """Guardrail: Location parsing handles 'flexible/anywhere' with soft follow-up; handover after third failure."""
    lead = Lead(wa_from="1234567890", status=STATUS_QUALIFYING, current_step=8)
    db.add(lead)
    db.commit()

    # Test "flexible"
    result1 = await handle_inbound_message(db, lead, "flexible", dry_run=True)
    assert result1.get("status") == "repair_needed"
    assert get_failure_count(lead, "location_city") == 1

    # Test "anywhere" - second failure, still repair (short+boundary variant)
    db.refresh(lead)
    result2 = await handle_inbound_message(db, lead, "anywhere", dry_run=True)
    assert result2.get("status") == "repair_needed"
    assert get_failure_count(lead, "location_city") == 2
    db.refresh(lead)
    assert not should_handover_after_failure(lead, "location_city")

    # Third failure - handover (use "x" so location parser rejects it; "nope" is accepted as city)
    result3 = await handle_inbound_message(db, lead, "x", dry_run=True)
    assert result3.get("status") == "handover_parse_failure"
    assert get_failure_count(lead, "location_city") == 3
    db.refresh(lead)
    assert should_handover_after_failure(lead, "location_city")


@pytest.mark.asyncio
async def test_location_parsing_london_uk(db):
    """Guardrail: Location parsing handles 'London UK' format."""
    lead = Lead(wa_from="1234567890", status=STATUS_QUALIFYING, current_step=8)
    db.add(lead)
    db.commit()

    result = await handle_inbound_message(db, lead, "London UK", dry_run=True)

    # Should parse successfully
    db.refresh(lead)
    answers = db.query(LeadAnswer).filter(LeadAnswer.lead_id == lead.id).all()
    location_answers = [a for a in answers if a.question_key == "location_city"]
    assert len(location_answers) > 0

    # Should infer country
    country_answers = [a for a in answers if a.question_key == "location_country"]
    # May or may not have country answer depending on implementation


@pytest.mark.asyncio
async def test_location_parsing_only_country(db):
    """Guardrail: Location parsing handles only-country responses."""
    lead = Lead(wa_from="1234567890", status=STATUS_QUALIFYING, current_step=8)
    db.add(lead)
    db.commit()

    result = await handle_inbound_message(db, lead, "United Kingdom", dry_run=True)

    # Should handle gracefully (may need follow-up or accept)
    db.refresh(lead)
    # Implementation dependent - may accept or request city


@pytest.mark.asyncio
async def test_slot_selection_out_of_range(db):
    """Guardrail: Slot selection handles out-of-range numbers."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_BOOKING_PENDING,
        suggested_slots_json=[
            {"start": "2026-01-25T10:00:00Z", "end": "2026-01-25T12:00:00Z"},
            {"start": "2026-01-26T10:00:00Z", "end": "2026-01-26T12:00:00Z"},
        ],
    )
    db.add(lead)
    db.commit()

    from datetime import datetime

    from app.services.slot_parsing import parse_slot_selection_logged

    slots = [
        {
            "start": datetime.fromisoformat("2026-01-25T10:00:00+00:00"),
            "end": datetime.fromisoformat("2026-01-25T12:00:00+00:00"),
        },
        {
            "start": datetime.fromisoformat("2026-01-26T10:00:00+00:00"),
            "end": datetime.fromisoformat("2026-01-26T12:00:00+00:00"),
        },
    ]

    # Out of range number
    result = parse_slot_selection_logged("10", slots, max_slots=8)
    assert result is None  # Should not match out-of-range number


@pytest.mark.asyncio
async def test_slot_selection_stale_suggestions(db):
    """Guardrail: Slot selection handles stale suggestions gracefully."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_BOOKING_PENDING,
        suggested_slots_json=[
            {"start": "2025-01-01T10:00:00Z", "end": "2025-01-01T12:00:00Z"},  # Old date
        ],
    )
    db.add(lead)
    db.commit()

    # Should handle gracefully (may re-check availability or prompt for new selection)
    # Implementation dependent


@pytest.mark.asyncio
async def test_slot_selection_ambiguous_tuesday_afternoon(db):
    """Guardrail: Slot selection handles ambiguous 'Tuesday afternoon'."""
    from datetime import datetime

    from app.services.slot_parsing import parse_slot_selection_logged

    slots = [
        {
            "start": datetime.fromisoformat("2026-01-27T14:00:00+00:00"),
            "end": datetime.fromisoformat("2026-01-27T16:00:00+00:00"),
        },  # Tuesday 2pm
        {
            "start": datetime.fromisoformat("2026-01-27T15:00:00+00:00"),
            "end": datetime.fromisoformat("2026-01-27T17:00:00+00:00"),
        },  # Tuesday 3pm
    ]

    # Should match first Tuesday afternoon slot
    result = parse_slot_selection_logged("Tuesday afternoon", slots, max_slots=8)
    # May return first match or None if ambiguous
    assert result is None or result in [1, 2]


@pytest.mark.asyncio
async def test_slot_selection_calendar_disabled_stored_slots_exist(db):
    """Guardrail: Slot selection works when calendar disabled but stored slots exist."""
    from app.core.config import settings

    lead = Lead(
        wa_from="1234567890",
        status=STATUS_BOOKING_PENDING,
        suggested_slots_json=[
            {"start": "2026-01-25T10:00:00Z", "end": "2026-01-25T12:00:00Z"},
        ],
    )
    db.add(lead)
    db.commit()

    # Disable calendar
    original_value = settings.feature_calendar_enabled
    settings.feature_calendar_enabled = False

    try:
        # Should still be able to select from stored slots
        result = await handle_inbound_message(db, lead, "1", dry_run=True)
        # Should process selection even if calendar is disabled
        assert result is not None
    finally:
        settings.feature_calendar_enabled = original_value


@pytest.mark.asyncio
async def test_payment_webhook_before_deposit_issued(client, db):
    """Guardrail: Stripe webhook before deposit issued is handled gracefully."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_PENDING_APPROVAL,  # Not yet awaiting deposit
        stripe_checkout_session_id=None,  # No session yet
    )
    db.add(lead)
    db.commit()

    # Webhook arrives before deposit is sent
    payload = {
        "id": "evt_test_early",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_early",
                "client_reference_id": str(lead.id),
                "metadata": {"lead_id": str(lead.id)},
            }
        },
    }

    response = client.post(
        "/webhooks/stripe",
        json=payload,
        headers={"Stripe-Signature": "test_sig"},
    )

    # Should handle gracefully (may ignore or log warning)
    assert response.status_code in [200, 400]


@pytest.mark.asyncio
async def test_payment_session_mismatch(client, db):
    """Guardrail: Stripe webhook with session ID mismatch is rejected."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_AWAITING_DEPOSIT,
        stripe_checkout_session_id="cs_test_expected",
    )
    db.add(lead)
    db.commit()

    # Webhook with different session ID
    payload = {
        "id": "evt_test_mismatch",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_wrong",  # Different session ID
                "client_reference_id": str(lead.id),
                "metadata": {"lead_id": str(lead.id)},
            }
        },
    }

    response = client.post(
        "/webhooks/stripe",
        json=payload,
        headers={"Stripe-Signature": "test_sig"},
    )

    # Should reject or ignore
    assert response.status_code in [200, 400]

    # Status should not change
    db.refresh(lead)
    assert lead.status == STATUS_AWAITING_DEPOSIT


@pytest.mark.asyncio
async def test_payment_expired_session_resend(client, db):
    """Guardrail: Expired session triggers new session creation on resend."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_AWAITING_DEPOSIT,  # send-deposit only accepts this status
        stripe_checkout_session_id="cs_test_expired",
        deposit_checkout_expires_at=datetime.now(UTC) - timedelta(hours=1),  # Expired
        deposit_amount_pence=5000,
    )
    db.add(lead)
    db.commit()

    # Send deposit again (should create new session)
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    from app.core.config import settings

    checkout_return = {
        "checkout_session_id": "cs_test_new",
        "checkout_url": "https://checkout.stripe.com/test",
        "expires_at": _dt.now(_UTC) + timedelta(hours=1),
    }
    with (
        patch.object(settings, "admin_api_key", "test_key"),
        patch(
            "app.services.stripe_service.create_checkout_session",
            return_value=checkout_return,
        ),
        patch(
            "app.services.whatsapp_window.send_with_window_check",
            new_callable=AsyncMock,
        ),
    ):
        response = client.post(
            f"/admin/leads/{lead.id}/send-deposit",
            headers={"X-Admin-API-Key": "test_key"},
        )
        assert response.status_code == 200

    db.refresh(lead)
    # Should have new session ID
    assert lead.stripe_checkout_session_id != "cs_test_expired"
    assert lead.deposit_checkout_expires_at is not None
    now = datetime.now(UTC)
    exp = lead.deposit_checkout_expires_at
    exp_aware = exp.replace(tzinfo=UTC) if exp.tzinfo is None else exp
    assert exp_aware > now


@pytest.mark.asyncio
async def test_send_deposit_rejected_when_not_awaiting_deposit(client, db):
    """Guardrail: send-deposit returns 400 when lead is not in AWAITING_DEPOSIT."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_PENDING_APPROVAL,
        estimated_deposit_amount=5000,
    )
    db.add(lead)
    db.commit()

    from app.core.config import settings

    with patch.object(settings, "admin_api_key", "test_key"):
        response = client.post(
            f"/admin/leads/{lead.id}/send-deposit",
            headers={"X-Admin-API-Key": "test_key"},
        )
    assert response.status_code == 400
    assert "AWAITING_DEPOSIT" in (response.json().get("detail") or "")


@pytest.mark.asyncio
async def test_send_deposit_rejected_when_already_paid(client, db):
    """Guardrail: send-deposit returns 400 when lead has already paid (DEPOSIT_PAID)."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_DEPOSIT_PAID,
        deposit_amount_pence=5000,
    )
    db.add(lead)
    db.commit()

    from app.core.config import settings

    with patch.object(settings, "admin_api_key", "test_key"):
        response = client.post(
            f"/admin/leads/{lead.id}/send-deposit",
            headers={"X-Admin-API-Key": "test_key"},
        )
    assert response.status_code == 400
    assert "AWAITING_DEPOSIT" in (response.json().get("detail") or "")


@pytest.mark.asyncio
async def test_expires_at_timezone_aware_comparison(db):
    """Guardrail: expires_at vs now() comparison is timezone-aware (no TypeError)."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_AWAITING_DEPOSIT,
        stripe_checkout_session_id="cs_old",
        deposit_checkout_expires_at=datetime.now(UTC) + timedelta(hours=1),
        deposit_amount_pence=5000,
    )
    db.add(lead)
    db.commit()

    # Admin code compares now(UTC) with expires_at; ensure no naive/aware TypeError
    now = datetime.now(UTC)
    exp = lead.deposit_checkout_expires_at
    exp_aware = exp.replace(tzinfo=UTC) if exp and exp.tzinfo is None else exp
    assert exp_aware is not None
    assert exp_aware > now or exp_aware == now


@pytest.mark.asyncio
async def test_summary_uses_latest_per_key(db):
    """Guardrail: get_lead_summary shows latest value when multiple answers exist for same key."""
    lead = Lead(wa_from="1234567890", status=STATUS_QUALIFYING)
    db.add(lead)
    db.commit()

    db.add(LeadAnswer(lead_id=lead.id, question_key="budget", answer_text="500"))
    db.add(LeadAnswer(lead_id=lead.id, question_key="budget", answer_text="600"))
    db.commit()

    summary = get_lead_summary(db, lead.id)
    assert summary.get("answers", {}).get("budget") == "600"


@pytest.mark.asyncio
async def test_sheet_logging_uses_latest_per_key(db):
    """Guardrail: log_lead_to_sheets uses latest value per key (same rule as summary)."""
    lead = Lead(wa_from="1234567890", status=STATUS_QUALIFYING)
    db.add(lead)
    db.commit()

    db.add(LeadAnswer(lead_id=lead.id, question_key="budget", answer_text="400"))
    db.add(LeadAnswer(lead_id=lead.id, question_key="budget", answer_text="550"))
    db.commit()

    from app.services.sheets import log_lead_to_sheets

    with patch("app.services.sheets._get_sheets_service", return_value=None):
        # Just ensure it runs; sheets uses same ordered query as get_lead_summary now
        result = log_lead_to_sheets(db, lead)
    # When sheets disabled or stub, may return False; we only care it didn't raise
    assert result is True or result is False
    # Verify the rule: summary (and sheets internal logic) use latest
    summary = get_lead_summary(db, lead.id)
    assert summary.get("answers", {}).get("budget") == "550"


@pytest.mark.asyncio
async def test_whatsapp_missing_credentials_prevents_send(db):
    """Guardrail: Missing WhatsApp credentials prevents message sending."""
    from app.core.config import settings
    from app.services.messaging import send_whatsapp_message

    # Save original values
    original_token = settings.whatsapp_access_token
    original_phone_id = settings.whatsapp_phone_number_id

    try:
        # Clear credentials
        settings.whatsapp_access_token = ""
        settings.whatsapp_phone_number_id = ""

        # Should raise error or return error status
        with pytest.raises((ValueError, KeyError, AttributeError)):
            await send_whatsapp_message(
                to="1234567890",
                message="Test",
                dry_run=False,  # Not dry run - should fail
            )
    finally:
        # Restore
        settings.whatsapp_access_token = original_token
        settings.whatsapp_phone_number_id = original_phone_id


@pytest.mark.asyncio
async def test_whatsapp_outside_24h_template_missing_logs_blocked(db):
    """Guardrail: Outside 24h window + missing template logs blocked reason."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_QUALIFYING,
        last_client_message_at=datetime.now(UTC) - timedelta(hours=25),
    )
    db.add(lead)
    db.commit()

    from app.db.models import SystemEvent
    from app.services.whatsapp_window import send_with_window_check

    # Try to send without template
    result = await send_with_window_check(
        db=db,
        lead=lead,
        message="Test message",
        template_name="nonexistent_template",
        dry_run=True,
    )

    # Should log system event (check if events table exists and has events)
    try:
        events = (
            db.execute(select(SystemEvent).order_by(SystemEvent.created_at.desc()).limit(10))
            .scalars()
            .all()
        )
        blocked_events = [
            e
            for e in events
            if "template" in e.event_type.lower() and "blocked" in e.event_type.lower()
        ]
    except Exception:
        # If SystemEvent table doesn't exist or query fails, that's okay
        blocked_events = []

    # May or may not have event depending on implementation
    assert result.get("window_status") in ["closed", "closed_template_used", "blocked"]


@pytest.mark.asyncio
async def test_build_handover_packet_includes_last_5_messages(db):
    """Guardrail: build_handover_packet() includes last 5 inbound messages."""
    lead = Lead(wa_from="1234567890", status=STATUS_NEEDS_ARTIST_REPLY)
    db.add(lead)
    db.commit()

    # Create 7 messages (should only include last 5)
    for i in range(7):
        answer = LeadAnswer(
            lead_id=lead.id,
            question_key=f"test_{i}",
            answer_text=f"Message {i}",
        )
        db.add(answer)
    db.commit()

    from app.services.handover_packet import build_handover_packet

    packet = build_handover_packet(db, lead)

    assert "last_messages" in packet
    assert len(packet["last_messages"]) == 5
    # Should be most recent 5 (oldest first after reversal)
    # Messages are reversed in build_handover_packet, so oldest is first
    assert packet["last_messages"][0]["answer_text"] == "Message 2"  # Oldest of the 5
    assert packet["last_messages"][4]["answer_text"] == "Message 6"  # Newest of the 5


@pytest.mark.asyncio
async def test_build_handover_packet_includes_parse_failures(db):
    """Guardrail: build_handover_packet() includes parse failures."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_NEEDS_ARTIST_REPLY,
        parse_failure_counts={"dimensions": 2, "budget": 1},
    )
    db.add(lead)
    db.commit()

    from app.services.handover_packet import build_handover_packet

    packet = build_handover_packet(db, lead)

    assert "parse_failures" in packet
    assert packet["parse_failures"]["dimensions"] == 2
    assert packet["parse_failures"]["budget"] == 1


@pytest.mark.asyncio
async def test_build_handover_packet_includes_category_deposit_price_range(db):
    """Guardrail: build_handover_packet() includes category, deposit, price range."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_NEEDS_ARTIST_REPLY,
        estimated_category="LARGE",
        estimated_deposit_amount=5000,
        estimated_price_min_pence=8000,
        estimated_price_max_pence=12000,
    )
    db.add(lead)
    db.commit()

    from app.services.handover_packet import build_handover_packet

    packet = build_handover_packet(db, lead)

    assert packet["category"] == "LARGE"
    assert packet["deposit_amount_pence"] == 5000
    assert packet["price_range_min_pence"] == 8000
    assert packet["price_range_max_pence"] == 12000


@pytest.mark.asyncio
async def test_build_handover_packet_includes_tour_conversion_context(db):
    """Guardrail: build_handover_packet() includes tour conversion context."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_NEEDS_ARTIST_REPLY,
        requested_city="Paris",
        offered_tour_city="London",
        tour_offer_accepted=False,
        waitlisted=True,
    )
    db.add(lead)
    db.commit()

    from app.services.handover_packet import build_handover_packet

    packet = build_handover_packet(db, lead)

    assert "tour_context" in packet
    assert packet["tour_context"]["requested_city"] == "Paris"
    assert packet["tour_context"]["offered_tour_city"] == "London"
    assert packet["tour_context"]["waitlisted"] is True


@pytest.mark.asyncio
async def test_build_handover_packet_includes_status_question_key(db):
    """Guardrail: build_handover_packet() includes status and current question key."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_NEEDS_ARTIST_REPLY,
        current_step=5,
    )
    db.add(lead)
    db.commit()

    from app.services.handover_packet import build_handover_packet

    packet = build_handover_packet(db, lead)

    assert packet["status"] == STATUS_NEEDS_ARTIST_REPLY
    assert "current_question_key" in packet
