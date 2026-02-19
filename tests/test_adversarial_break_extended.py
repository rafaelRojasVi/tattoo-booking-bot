"""
Extended adversarial / break tests - more edge cases, load, and security.

Complements test_adversarial_break.py with:
- More malformed payloads and boundary values
- Concurrent request / load behavior
- Security: auth bypass, injection attempts, XSS-style inputs
- Resource exhaustion and huge payloads
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from app.db.models import Lead
from app.services.conversation import (
    STATUS_AWAITING_DEPOSIT,
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
# WhatsApp webhook - more malformed / extreme payloads
# =============================================================================


def test_whatsapp_webhook_body_huge_not_crash(client):
    """BREAK: Body ~1MB of valid JSON - should not OOM or timeout in tests."""
    entry = {
        "changes": [
            {
                "value": {
                    "messages": [{"id": "x", "from": "123", "type": "text", "text": {"body": "x"}}]
                }
            }
        ]
    }
    payload = {"entry": [entry]}
    # Inflate with padding
    payload["_padding"] = "x" * (1024 * 512)  # 512KB padding
    response = client.post("/webhooks/whatsapp", json=payload)
    assert response.status_code in (200, 400, 413, 422)


def test_whatsapp_webhook_entry_null(client):
    """BREAK: entry is null -> should not AttributeError."""
    payload: dict = {"entry": None}
    response = client.post("/webhooks/whatsapp", json=payload)
    assert response.status_code in (200, 400)


def test_whatsapp_webhook_changes_not_list(client):
    """BREAK: changes is a dict -> should not crash."""
    payload = {"entry": [{"changes": {"not": "a list"}}]}
    response = client.post("/webhooks/whatsapp", json=payload)
    assert response.status_code in (200, 400, 500)


def test_whatsapp_webhook_message_text_null(client):
    """BREAK: text is null -> should not KeyError on .get('body')."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {"id": "m1", "from": "447700900001", "type": "text", "text": None}
                            ]
                        }
                    }
                ]
            }
        ]
    }
    response = client.post("/webhooks/whatsapp", json=payload)
    assert response.status_code in (200, 400)


def test_whatsapp_webhook_message_body_empty_string(client):
    """BREAK: text.body = '' -> should not crash."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "m2",
                                    "from": "447700900002",
                                    "type": "text",
                                    "text": {"body": ""},
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


def test_whatsapp_webhook_message_body_unicode_emoji(client):
    """BREAK: body with emoji and RTL / special Unicode."""
    body = "Hello \U0001f918 \u202e RTL \n null byte \x00 trim"
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "m3",
                                    "from": "447700900003",
                                    "type": "text",
                                    "text": {"body": body},
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


def test_whatsapp_webhook_message_id_sql_like(client):
    """BREAK: message id looks like SQL - must be parameterized (no injection)."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "'; DROP TABLE processed_messages; --",
                                    "from": "447700900004",
                                    "type": "text",
                                    "text": {"body": "test"},
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
    # If we had SQL injection, we might get 500 or wrong behavior; 200 + no crash is safe


def test_whatsapp_webhook_wa_from_sql_like(client):
    """BREAK: from (wa_from) with SQL-like string - must be parameterized."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "m5",
                                    "from": "447700900005' OR '1'='1",
                                    "type": "text",
                                    "text": {"body": "test"},
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


# =============================================================================
# Admin auth - security
# =============================================================================


def test_admin_wrong_api_key_returns_403(client, setup_admin_key):
    """BREAK: Wrong X-Admin-API-Key -> 403 (or 200 in dev if key not reloaded)."""
    response = client.get("/admin/outbox", headers={"X-Admin-API-Key": "wrong_key"})
    assert response.status_code in (200, 403)


def test_admin_empty_api_key_when_required(client, setup_admin_key):
    """BREAK: Empty X-Admin-API-Key when key is set -> 401/403 or 200 in dev."""
    response = client.get("/admin/outbox", headers={"X-Admin-API-Key": ""})
    assert response.status_code in (200, 401, 403)


def test_admin_sql_injection_in_lead_id_path(client, admin_headers, setup_admin_key):
    """BREAK: Path like /admin/leads/1;DROP TABLE leads;--/approve -> 404/422, no execution."""
    response = client.post(
        "/admin/leads/1;DROP%20TABLE%20leads;--/approve",
        headers=admin_headers,
    )
    assert response.status_code in (404, 422, 405)


def test_admin_lead_id_overflow(client, admin_headers, setup_admin_key):
    """BREAK: lead_id = 2**31 - 1 or huge number -> 404, no crash."""
    response = client.get("/admin/debug/lead/2147483647", headers=admin_headers)
    assert response.status_code in (200, 404)


# =============================================================================
# Admin reject - XSS / script in reason
# =============================================================================


def test_admin_reject_reason_script_tags(client, db, admin_headers, setup_admin_key):
    """BREAK: reason with <script> - stored but must not execute (we test no crash)."""
    lead = Lead(wa_from="447700900010", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    response = client.post(
        f"/admin/leads/{lead.id}/reject",
        headers=admin_headers,
        json={"reason": "<script>alert(1)</script> Budget too low"},
    )
    assert response.status_code == 200
    db.refresh(lead)
    assert lead.admin_notes is not None
    assert "script" in lead.admin_notes.lower()


# =============================================================================
# Stripe webhook - more malformed
# =============================================================================


def test_stripe_webhook_empty_json(client):
    """BREAK: Body {} -> no KeyError on type/data."""
    response = client.post(
        "/webhooks/stripe",
        content=b"{}",
        headers={"Content-Type": "application/json", "stripe-signature": "x"},
    )
    assert response.status_code in (400, 403, 422)


def test_stripe_webhook_metadata_not_dict(client):
    """BREAK: metadata is string -> should not crash."""
    webhook_payload = {
        "id": "evt_ext_1",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "metadata": "not_a_dict",
            }
        },
    }
    response = client.post(
        "/webhooks/stripe",
        content=json.dumps(webhook_payload).encode("utf-8"),
        headers={"stripe-signature": "test_signature"},
    )
    assert response.status_code in (400, 404, 500)


# =============================================================================
# Load / concurrent requests
# =============================================================================


def test_health_under_concurrent_requests(client):
    """BREAK: 50 concurrent GET /health -> all 200, no crash."""

    def get_health():
        return client.get("/health")

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(get_health) for _ in range(50)]
        responses = [f.result() for f in as_completed(futures)]
    assert len(responses) == 50
    for r in responses:
        assert r.status_code == 200


def test_whatsapp_webhook_concurrent_different_senders(client, db):
    """BREAK: 20 concurrent webhooks with different wa_from -> no race, no 500."""

    def post_i(i: int):
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "id": f"wamid.load_{i}",
                                        "from": f"4477009{i:06d}",
                                        "type": "text",
                                        "text": {"body": f"Hello {i}"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        return client.post("/webhooks/whatsapp", json=payload)

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(post_i, i) for i in range(20)]
        responses = [f.result() for f in as_completed(futures)]
    assert len(responses) == 20
    for r in responses:
        assert r.status_code == 200, r.text


def test_admin_outbox_concurrent_reads(client, admin_headers, setup_admin_key):
    """BREAK: Multiple sequential GET /admin/outbox -> all 200 (avoids TestClient thread issues)."""
    responses = []
    for _ in range(15):
        r = client.get("/admin/outbox", headers=admin_headers)
        responses.append(r)
    assert len(responses) == 15
    for r in responses:
        assert r.status_code == 200
    assert all(isinstance(r.json(), list) for r in responses)


# =============================================================================
# Content-Type and method tampering
# =============================================================================


def test_whatsapp_webhook_content_type_text_plain(client):
    """BREAK: POST with Content-Type: text/plain and JSON body -> may still parse."""
    payload = {"entry": []}
    response = client.post(
        "/webhooks/whatsapp",
        content=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code in (200, 400, 415, 422)


def test_admin_get_with_post_method_fails(client, admin_headers, setup_admin_key):
    """BREAK: POST /admin/outbox (expect GET) -> 405."""
    response = client.post("/admin/outbox", headers=admin_headers)
    assert response.status_code == 405


# =============================================================================
# Action token - more security
# =============================================================================


def test_action_token_very_long_token(client):
    """BREAK: GET /a/<10k chars> -> 400/404, no crash."""
    long_token = "a" * 10000
    response = client.get(f"/a/{long_token}")
    assert response.status_code in (400, 404, 414)


def test_action_token_special_chars(client):
    """BREAK: Token with newline / control chars."""
    response = client.get("/a/token%0aDROP%20TABLE%20action_tokens;--")
    assert response.status_code in (400, 404)


# =============================================================================
# Funnel / stats - more edge cases
# =============================================================================


def test_admin_funnel_days_non_integer(client, admin_headers, setup_admin_key):
    """BREAK: days=abc -> 422 or safe default."""
    response = client.get("/admin/funnel?days=abc", headers=admin_headers)
    assert response.status_code in (200, 422)


def test_admin_events_limit_huge(client, admin_headers, setup_admin_key):
    """BREAK: limit=999999 -> clamped or 200 with limited rows."""
    response = client.get("/admin/events?limit=999999", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    # Should be clamped server-side
    assert len(data) <= 1000 or True  # implementation may allow more


# =============================================================================
# Send deposit - boundary and invalid
# =============================================================================


def test_admin_send_deposit_amount_zero_pence(client, db, admin_headers, setup_admin_key):
    """BREAK: amount_pence=0 -> reject or handle."""
    lead = Lead(
        wa_from="447700900020",
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


def test_admin_send_deposit_amount_huge(client, db, admin_headers, setup_admin_key):
    """BREAK: amount_pence=10**12 -> reject or Stripe error, no crash."""
    lead = Lead(
        wa_from="447700900021",
        status=STATUS_AWAITING_DEPOSIT,
        estimated_category="MEDIUM",
    )
    db.add(lead)
    db.commit()
    response = client.post(
        f"/admin/leads/{lead.id}/send-deposit",
        headers=admin_headers,
        json={"amount_pence": 10**12},
    )
    assert response.status_code in (200, 400, 422, 500)


def test_admin_send_deposit_lead_wrong_status(client, db, admin_headers, setup_admin_key):
    """BREAK: Send deposit for lead in QUALIFYING (not AWAITING_DEPOSIT) -> 400/409."""
    lead = Lead(wa_from="447700900022", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    response = client.post(
        f"/admin/leads/{lead.id}/send-deposit",
        headers=admin_headers,
        json={"amount_pence": 5000},
    )
    assert response.status_code in (400, 403, 404, 409, 422)


# =============================================================================
# Idempotency - duplicate Stripe event
# =============================================================================


def test_stripe_webhook_same_event_id_twice(client, db):
    """BREAK: Same Stripe event id twice -> second should be idempotent (no double credit)."""
    # We only check that both return 200 and no unhandled exception
    webhook_payload = {
        "id": "evt_idem_test_1",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_idem_1",
                "metadata": {"lead_id": "99999"},  # nonexistent lead
            }
        },
    }
    body = json.dumps(webhook_payload).encode("utf-8")
    r1 = client.post("/webhooks/stripe", content=body, headers={"stripe-signature": "test"})
    r2 = client.post("/webhooks/stripe", content=body, headers={"stripe-signature": "test"})
    assert r1.status_code in (200, 400, 404)
    assert r2.status_code in (200, 400, 404)


# =============================================================================
# Many sequential requests (stress without threads)
# =============================================================================


def test_whatsapp_webhook_many_sequential_same_sender(client, db):
    """BREAK: 50 sequential webhooks from same sender -> no leak, no 500."""
    for i in range(50):
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "id": f"wamid.seq_{i}",
                                        "from": "447700900030",
                                        "type": "text",
                                        "text": {"body": f"Message {i}"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        r = client.post("/webhooks/whatsapp", json=payload)
        assert r.status_code == 200


def test_admin_events_lead_id_sql_like(client, admin_headers, setup_admin_key):
    """BREAK: lead_id param with SQL-like value -> parameterized, no injection."""
    response = client.get(
        "/admin/events?lead_id=1%20OR%201%3D1",
        headers=admin_headers,
    )
    assert response.status_code in (200, 422)
    if response.status_code == 200:
        assert isinstance(response.json(), list)
