"""
Adversarial / break tests - inputs designed to expose bugs, edge cases, or security issues.

These tests try to break the system with malformed, extreme, or malicious inputs.
If they fail (assertion fails), they may have exposed a bug that should be fixed.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import ActionToken, Lead, OutboxMessage
from app.services.conversation import (
    STATUS_AWAITING_DEPOSIT,
    STATUS_BOOKING_PENDING,
    STATUS_DEPOSIT_PAID,
    STATUS_PENDING_APPROVAL,
)


@pytest.fixture
def admin_headers():
    return {"X-Admin-API-Key": "test_admin_key"}


@pytest.fixture
def setup_admin_key(monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "test_admin_key")
    monkeypatch.setenv("APP_ENV", "dev")


# =============================================================================
# Stripe webhook - invalid lead_id parsing
# =============================================================================


def test_stripe_webhook_metadata_lead_id_not_a_number(client):
    """BREAK: metadata.lead_id = 'not_a_number' -> should return 400, not 500."""
    webhook_payload = {
        "id": "evt_adv_1",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "metadata": {"lead_id": "not_a_number"},
            }
        },
    }
    response = client.post(
        "/webhooks/stripe",
        content=json.dumps(webhook_payload).encode("utf-8"),
        headers={"stripe-signature": "test_signature"},
    )
    assert response.status_code == 400
    assert "lead" in response.json().get("error", "").lower()


def test_stripe_webhook_metadata_lead_id_float_string(client):
    """BREAK: metadata.lead_id = '1.5' -> should reject (lead_id must be integer)."""
    webhook_payload = {
        "id": "evt_adv_2",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "metadata": {"lead_id": "1.5"},
            }
        },
    }
    response = client.post(
        "/webhooks/stripe",
        content=json.dumps(webhook_payload).encode("utf-8"),
        headers={"stripe-signature": "test_signature"},
    )
    assert response.status_code == 400


def test_stripe_webhook_metadata_lead_id_negative(client, db):
    """BREAK: metadata.lead_id = '-1' -> rejected (lead_id must be positive)."""
    webhook_payload = {
        "id": "evt_adv_3",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "metadata": {"lead_id": "-1"},
            }
        },
    }
    response = client.post(
        "/webhooks/stripe",
        content=json.dumps(webhook_payload).encode("utf-8"),
        headers={"stripe-signature": "test_signature"},
    )
    assert response.status_code == 400


def test_stripe_webhook_metadata_lead_id_empty_string(client):
    """BREAK: metadata.lead_id = '' -> should return 400 (no lead_id)."""
    webhook_payload = {
        "id": "evt_adv_4",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "metadata": {"lead_id": ""},
            }
        },
    }
    response = client.post(
        "/webhooks/stripe",
        content=json.dumps(webhook_payload).encode("utf-8"),
        headers={"stripe-signature": "test_signature"},
    )
    assert response.status_code == 400


# =============================================================================
# Admin outbox - limit edge cases
# =============================================================================


def test_admin_outbox_limit_negative(client, admin_headers, setup_admin_key):
    """BREAK: limit=-1 -> min(-1, 100) = -1, SQL LIMIT -1 may behave oddly."""
    response = client.get("/admin/outbox?limit=-1", headers=admin_headers)
    # Should not crash; either clamp to 1 or return 400
    assert response.status_code in (200, 400)
    if response.status_code == 200:
        data = response.json()
        assert isinstance(data, list)


def test_admin_outbox_limit_zero(client, admin_headers, setup_admin_key):
    """BREAK: limit=0 -> min(0, 100) = 0."""
    response = client.get("/admin/outbox?limit=0", headers=admin_headers)
    assert response.status_code == 200
    assert response.json() == []


def test_admin_outbox_status_invalid(client, admin_headers, setup_admin_key):
    """BREAK: status='INVALID_STATUS' or status='<script>' - should not crash."""
    response = client.get(
        "/admin/outbox?status=INVALID_STATUS_THAT_DOES_NOT_EXIST",
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json() == []


def test_admin_outbox_status_sql_injection_attempt(client, admin_headers, setup_admin_key):
    """BREAK: status with SQL injection attempt - parameterized query should be safe."""
    response = client.get(
        "/admin/outbox?status=FAILED' OR '1'='1",
        headers=admin_headers,
    )
    # Should not crash; status.upper() gives "FAILED' OR '1'='1", no matching rows
    assert response.status_code == 200
    assert isinstance(response.json(), list)


# =============================================================================
# Rate limit - IP spoofing
# =============================================================================


def test_rate_limit_x_forwarded_for_spoofing(client, admin_headers, setup_admin_key):
    """BREAK: X-Forwarded-For can be spoofed - app should not crash with spoofed header."""
    # Rate limit is disabled in tests; we just verify spoofed header doesn't crash
    resp = client.get(
        "/admin/outbox",
        headers={
            **admin_headers,
            "X-Forwarded-For": "10.0.0.1, 192.168.1.1",  # Spoofed chain
        },
    )
    assert resp.status_code == 200


# =============================================================================
# WhatsApp webhook - message without id (idempotency bypass)
# =============================================================================


def test_whatsapp_message_without_id_can_duplicate(client):
    """BREAK: Two messages without message_id could both be processed (no idempotency)."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "447700900001",
                                    "type": "text",
                                    "text": {"body": "First message"},
                                    # No "id" field - WhatsApp can send some events without id
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    resp1 = client.post("/webhooks/whatsapp", json=payload)
    assert resp1.status_code == 200

    resp2 = client.post("/webhooks/whatsapp", json=payload)
    assert resp2.status_code == 200
    # Both are processed - idempotency is skipped when message_id is None
    # This is expected behavior; we're documenting it
    assert resp1.json().get("received") is True
    assert resp2.json().get("received") is True


# =============================================================================
# Correlation ID - very long header
# =============================================================================


def test_correlation_id_very_long_header(client, admin_headers, setup_admin_key):
    """BREAK: X-Correlation-ID with 10000 chars - middleware has len<=128 check."""
    long_cid = "x" * 10000
    response = client.get(
        "/admin/outbox",
        headers={**admin_headers, "X-Correlation-ID": long_cid},
    )
    # Should not crash; middleware generates new UUID if len > 128
    assert response.status_code == 200


# =============================================================================
# Admin lead endpoints - invalid lead_id
# =============================================================================


def test_admin_approve_nonexistent_lead(client, admin_headers, setup_admin_key):
    """BREAK: POST /admin/leads/999999/approve - lead not found."""
    response = client.post(
        "/admin/leads/999999/approve",
        headers=admin_headers,
    )
    assert response.status_code == 404


def test_admin_approve_lead_id_zero(client, admin_headers, setup_admin_key):
    """BREAK: POST /admin/leads/0/approve."""
    response = client.post(
        "/admin/leads/0/approve",
        headers=admin_headers,
    )
    assert response.status_code == 404


def test_admin_approve_lead_id_negative(client, admin_headers, setup_admin_key):
    """BREAK: POST /admin/leads/-1/approve - FastAPI may reject before handler."""
    response = client.post(
        "/admin/leads/-1/approve",
        headers=admin_headers,
    )
    assert response.status_code in (404, 422)


# =============================================================================
# Health / ready - robustness
# =============================================================================


def test_health_endpoint_always_returns_200(client):
    """Health should never crash."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json().get("ok") is True


def test_ready_endpoint_handles_db(client):
    """Ready should return 200 or 503, never 500 from unhandled exception."""
    response = client.get("/ready")
    assert response.status_code in (200, 503)


# =============================================================================
# Outbox - next_retry_at serialization
# =============================================================================


def test_admin_outbox_with_null_next_retry_at(client, db, admin_headers, setup_admin_key):
    """BREAK: Outbox row with next_retry_at=None - serialization should handle."""
    lead = Lead(wa_from="447700900002", status="NEW")
    db.add(lead)
    db.commit()

    msg = OutboxMessage(
        lead_id=lead.id,
        channel="whatsapp",
        payload_json={"to": "447700900002", "message": "test"},
        status="FAILED",
        attempts=1,
        last_error="Test error",
        next_retry_at=None,  # Explicitly None
    )
    db.add(msg)
    db.commit()

    response = client.get("/admin/outbox?status=FAILED", headers=admin_headers)
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) >= 1
    r = next(x for x in rows if x["id"] == msg.id)
    assert r["next_retry_at"] is None


# =============================================================================
# Stripe - malformed event structure
# =============================================================================


def test_stripe_webhook_malformed_event_no_data_object(client):
    """BREAK: Event with missing data.object -> should return 400, not KeyError 500."""
    webhook_payload = {
        "id": "evt_adv_5",
        "type": "checkout.session.completed",
        "data": {},  # No "object" key
    }
    response = client.post(
        "/webhooks/stripe",
        content=json.dumps(webhook_payload).encode("utf-8"),
        headers={"stripe-signature": "test_signature"},
    )
    assert response.status_code == 400
    assert "malformed" in response.json().get("error", "").lower()


# =============================================================================
# WhatsApp webhook - malformed / extreme payloads
# =============================================================================


def test_whatsapp_webhook_invalid_json(client):
    """BREAK: Body is not valid JSON -> should return 400."""
    response = client.post(
        "/webhooks/whatsapp",
        content=b"not valid json {{{",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert "json" in response.json().get("error", "").lower()


def test_whatsapp_webhook_empty_body(client):
    """BREAK: Empty body -> JSON decode or signature may fail."""
    response = client.post(
        "/webhooks/whatsapp",
        content=b"",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code in (400, 403)


def test_whatsapp_webhook_entry_not_list(client):
    """BREAK: entry is not a list (e.g. dict) -> IndexError or TypeError."""
    payload = {"entry": {"not": "a list"}}
    response = client.post("/webhooks/whatsapp", json=payload)
    assert response.status_code == 200
    assert "received" in response.json() or "error" in str(response.json()).lower()


def test_whatsapp_webhook_message_from_as_integer(client):
    """BREAK: message.from is integer instead of string -> validation may fail."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "msg_adv_1",
                                    "from": 447700900001,  # Integer, not string
                                    "type": "text",
                                    "text": {"body": "hello"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    response = client.post("/webhooks/whatsapp", json=payload)
    assert response.status_code in (200, 400)
    if response.status_code == 200:
        data = response.json()
        assert "received" in data or "error" in str(data).lower()


def test_whatsapp_webhook_empty_messages_array(client):
    """BREAK: messages is empty array -> no message to process."""
    payload = {
        "entry": [{"changes": [{"value": {"messages": []}}]}]
    }
    response = client.post("/webhooks/whatsapp", json=payload)
    assert response.status_code == 200
    assert response.json().get("type") == "non-message-event" or "received" in response.json()


# =============================================================================
# WhatsApp webhook GET verify
# =============================================================================


def test_whatsapp_verify_wrong_mode(client):
    """BREAK: hub_mode != subscribe -> 403."""
    response = client.get(
        "/webhooks/whatsapp?hub_mode=wrong&hub_verify_token=test_token&hub_challenge=abc"
    )
    assert response.status_code == 403


def test_whatsapp_verify_missing_challenge(client):
    """BREAK: hub_challenge is None/empty -> should not crash."""
    response = client.get(
        "/webhooks/whatsapp?hub_mode=subscribe&hub_verify_token=test_token"
    )
    assert response.status_code == 200
    assert response.text == "" or response.text == ""


# =============================================================================
# Action token - invalid paths
# =============================================================================


def test_action_token_empty_token(client):
    """BREAK: GET /a/ with empty token (path segment)."""
    response = client.get("/a/")
    assert response.status_code in (404, 405, 400)


def test_action_token_invalid_format(client):
    """BREAK: GET /a/invalid_token_that_does_not_exist -> 400."""
    response = client.get("/a/invalid_token_that_does_not_exist")
    assert response.status_code == 400
    assert "invalid" in response.text.lower() or "error" in response.text.lower()


def test_action_token_path_traversal_attempt(client):
    """BREAK: Token with path traversal -> should not access other paths."""
    response = client.get("/a/../../../etc/passwd")
    assert response.status_code in (400, 404)


# =============================================================================
# Admin funnel / slot-parse-stats - days edge cases
# =============================================================================


def test_admin_funnel_days_zero(client, admin_headers, setup_admin_key):
    """BREAK: days=0 -> may cause division by zero or empty range."""
    response = client.get("/admin/funnel?days=0", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert "counts" in data or "rates" in data


def test_admin_funnel_days_negative(client, admin_headers, setup_admin_key):
    """BREAK: days=-1 -> may cause negative range."""
    response = client.get("/admin/funnel?days=-1", headers=admin_headers)
    assert response.status_code in (200, 422)


def test_admin_funnel_days_huge(client, admin_headers, setup_admin_key):
    """BREAK: days=999999 -> may cause slow query or overflow."""
    response = client.get("/admin/funnel?days=999999", headers=admin_headers)
    assert response.status_code == 200


def test_admin_slot_parse_stats_days_zero(client, admin_headers, setup_admin_key):
    """BREAK: days=0 for slot-parse-stats."""
    response = client.get("/admin/slot-parse-stats?days=0", headers=admin_headers)
    assert response.status_code == 200


# =============================================================================
# Admin events - limit / lead_id edge cases
# =============================================================================


def test_admin_events_limit_zero(client, admin_headers, setup_admin_key):
    """BREAK: limit=0 -> should return empty list."""
    response = client.get("/admin/events?limit=0", headers=admin_headers)
    assert response.status_code == 200
    assert response.json() == []


def test_admin_events_limit_negative(client, admin_headers, setup_admin_key):
    """BREAK: limit=-1 -> should not crash."""
    response = client.get("/admin/events?limit=-1", headers=admin_headers)
    assert response.status_code in (200, 422)


def test_admin_events_lead_id_nonexistent(client, admin_headers, setup_admin_key):
    """BREAK: lead_id=999999 -> should return empty list."""
    response = client.get("/admin/events?lead_id=999999", headers=admin_headers)
    assert response.status_code == 200
    assert response.json() == []


# =============================================================================
# Admin retention cleanup
# =============================================================================


def test_admin_retention_cleanup_days_zero(client, admin_headers, setup_admin_key):
    """BREAK: retention_days=0 -> may delete all events."""
    response = client.post(
        "/admin/events/retention-cleanup?retention_days=0",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "deleted" in data


def test_admin_retention_cleanup_days_negative(client, admin_headers, setup_admin_key):
    """BREAK: retention_days=-1 -> should not crash."""
    response = client.post(
        "/admin/events/retention-cleanup?retention_days=-1",
        headers=admin_headers,
    )
    assert response.status_code in (200, 422)


# =============================================================================
# Admin send-booking-link - invalid request body
# =============================================================================


def test_admin_send_booking_link_empty_url(client, db, admin_headers, setup_admin_key):
    """BREAK: booking_url empty string -> may fail validation."""
    lead = Lead(wa_from="447700900003", status=STATUS_DEPOSIT_PAID)
    db.add(lead)
    db.commit()
    response = client.post(
        f"/admin/leads/{lead.id}/send-booking-link",
        headers=admin_headers,
        json={"booking_url": "", "booking_tool": "FRESHA"},
    )
    assert response.status_code in (200, 400, 422)


def test_admin_send_booking_link_missing_url(client, db, admin_headers, setup_admin_key):
    """BREAK: Missing booking_url in body -> 422."""
    lead = Lead(wa_from="447700900004", status=STATUS_DEPOSIT_PAID)
    db.add(lead)
    db.commit()
    response = client.post(
        f"/admin/leads/{lead.id}/send-booking-link",
        headers=admin_headers,
        json={"booking_tool": "FRESHA"},
    )
    assert response.status_code == 422


# =============================================================================
# Admin send-deposit - amount_pence edge cases
# =============================================================================


def test_admin_send_deposit_negative_amount(client, db, admin_headers, setup_admin_key):
    """BREAK: amount_pence=-1 in request -> should reject with 400."""
    lead = Lead(
        wa_from="447700900005",
        status=STATUS_AWAITING_DEPOSIT,
        estimated_category="MEDIUM",
    )
    db.add(lead)
    db.commit()
    response = client.post(
        f"/admin/leads/{lead.id}/send-deposit",
        headers=admin_headers,
        json={"amount_pence": -1},
    )
    assert response.status_code == 400
    assert "amount" in response.json().get("detail", "").lower()


def test_admin_send_deposit_zero_amount(client, db, admin_headers, setup_admin_key):
    """BREAK: amount_pence=0 -> may create invalid checkout."""
    lead = Lead(
        wa_from="447700900006",
        status=STATUS_AWAITING_DEPOSIT,
        estimated_category="MEDIUM",
    )
    db.add(lead)
    db.commit()
    response = client.post(
        f"/admin/leads/{lead.id}/send-deposit",
        headers=admin_headers,
        json={"amount_pence": 0},
    )
    assert response.status_code in (200, 400, 422)


# =============================================================================
# Admin reject - extreme reason
# =============================================================================


def test_admin_reject_very_long_reason(client, db, admin_headers, setup_admin_key):
    """BREAK: reason with 10000 chars -> may hit DB column limit."""
    lead = Lead(wa_from="447700900007", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    long_reason = "x" * 10000
    response = client.post(
        f"/admin/leads/{lead.id}/reject",
        headers=admin_headers,
        json={"reason": long_reason},
    )
    assert response.status_code in (200, 400, 422, 500)


# =============================================================================
# Stripe - more malformed events
# =============================================================================


def test_stripe_webhook_data_is_null(client):
    """BREAK: event.data is null -> KeyError."""
    webhook_payload = {
        "id": "evt_adv_6",
        "type": "checkout.session.completed",
        "data": None,
    }
    response = client.post(
        "/webhooks/stripe",
        content=json.dumps(webhook_payload).encode("utf-8"),
        headers={"stripe-signature": "test_signature"},
    )
    assert response.status_code == 400


def test_stripe_webhook_metadata_lead_id_unicode(client):
    """BREAK: metadata.lead_id = '１２３' (fullwidth digits) -> parse."""
    webhook_payload = {
        "id": "evt_adv_7",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "metadata": {"lead_id": "１２３"},
            }
        },
    }
    response = client.post(
        "/webhooks/stripe",
        content=json.dumps(webhook_payload).encode("utf-8"),
        headers={"stripe-signature": "test_signature"},
    )
    assert response.status_code in (400, 404)


# =============================================================================
# Admin debug lead - nonexistent
# =============================================================================


def test_admin_debug_lead_nonexistent(client, admin_headers, setup_admin_key):
    """BREAK: GET /admin/debug/lead/999999 -> 404."""
    response = client.get("/admin/debug/lead/999999", headers=admin_headers)
    assert response.status_code == 404


# =============================================================================
# Admin outbox retry - limit edge case
# =============================================================================


def test_admin_outbox_retry_limit_zero(client, admin_headers, setup_admin_key):
    """BREAK: POST /admin/outbox/retry?limit=0 -> should not crash."""
    response = client.post(
        "/admin/outbox/retry?limit=0",
        headers=admin_headers,
    )
    assert response.status_code == 200


# =============================================================================
# Admin without auth
# =============================================================================


def test_admin_outbox_without_auth(client):
    """BREAK: GET /admin/outbox without X-Admin-API-Key -> 401 in prod, may pass in dev."""
    response = client.get("/admin/outbox")
    assert response.status_code in (200, 401)


# =============================================================================
# Sweep expired deposits - hours edge case
# =============================================================================


def test_admin_sweep_expired_hours_zero(client, admin_headers, setup_admin_key):
    """BREAK: hours_threshold=0 -> may cause logic issues."""
    response = client.post(
        "/admin/sweep-expired-deposits?hours_threshold=0",
        headers=admin_headers,
    )
    assert response.status_code == 200


def test_admin_sweep_expired_hours_negative(client, admin_headers, setup_admin_key):
    """BREAK: hours_threshold=-1 -> should not crash."""
    response = client.post(
        "/admin/sweep-expired-deposits?hours_threshold=-1",
        headers=admin_headers,
    )
    assert response.status_code in (200, 422)
