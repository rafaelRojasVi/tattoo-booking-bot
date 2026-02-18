"""
Abuse/load hardening tests.

- Rate limiting: 10 requests ok, 11th returns 429; window reset after time passes
- Outbox retry: limit=50 respects batch size; backoff on failure
- WhatsApp webhook retry storm: same message_id 20x concurrent → only 1 advances step
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from app.db.models import Lead, OutboxMessage
from app.services.conversation import STATUS_QUALIFYING

# =============================================================================
# Rate limiting
# =============================================================================


@pytest.fixture
def admin_headers():
    return {"X-Admin-API-Key": "test_admin_key"}


@pytest.fixture
def setup_admin_key(monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "test_admin_key")
    monkeypatch.setenv("APP_ENV", "dev")


def test_rate_limit_10_requests_ok_11th_returns_429(
    client, admin_headers, setup_admin_key, monkeypatch
):
    """10 requests within window succeed; 11th returns 429."""
    from app.core.config import settings
    from app.middleware.rate_limit import _rate_limit_store

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_requests", 10)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    _rate_limit_store.clear()

    # Use consistent IP so we hit same bucket
    headers = {**admin_headers, "X-Forwarded-For": "10.0.0.100"}

    # First 10 requests succeed
    for i in range(10):
        resp = client.get("/admin/outbox", headers=headers)
        assert resp.status_code == 200, f"Request {i + 1} should succeed"

    # 11th returns 429
    resp = client.get("/admin/outbox", headers=headers)
    assert resp.status_code == 429
    assert "rate limit" in resp.json().get("error", "").lower()


def test_rate_limit_window_reset_after_time_passes(
    client, admin_headers, setup_admin_key, monkeypatch
):
    """After window passes, requests succeed again."""
    from app.core.config import settings
    from app.middleware.rate_limit import _rate_limit_store

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_requests", 10)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    _rate_limit_store.clear()

    # First 10 requests see time=0 (store gets 10 zeros). 11th sees time=70 so cutoff=10, zeros expire.
    call_count = [0]

    def mock_time():
        call_count[0] += 1
        if call_count[0] <= 20:  # 2 per request * 10 = 20
            return 0.0
        return 70.0  # 11th request and beyond see time=70

    headers = {**admin_headers, "X-Forwarded-For": "10.0.0.101"}

    with patch("app.middleware.rate_limit.time.time", side_effect=mock_time):
        for i in range(10):
            resp = client.get("/admin/outbox", headers=headers)
            assert resp.status_code == 200, f"Request {i + 1} should succeed"

        # 11th: time=70, entries at 0 expire (cutoff=10), so under limit
        resp = client.get("/admin/outbox", headers=headers)
        assert resp.status_code == 200, "After window passes, request should succeed"


# =============================================================================
# Outbox retry
# =============================================================================


def test_outbox_retry_limit_50_only_50_attempted(
    client, db, admin_headers, setup_admin_key, monkeypatch
):
    """Seed 100 FAILED with next_retry_at <= now; retry?limit=50 → only 50 attempted."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "outbox_enabled", True)

    lead = Lead(wa_from="447700900100", status="NEW")
    db.add(lead)
    db.commit()
    db.refresh(lead)

    now = datetime.now(UTC)
    for i in range(100):
        msg = OutboxMessage(
            lead_id=lead.id,
            channel="whatsapp",
            payload_json={"to": lead.wa_from, "message": f"Test {i}"},
            status="FAILED",
            attempts=1,
            last_error="Simulated failure",
            next_retry_at=now - timedelta(minutes=1),
        )
        db.add(msg)
    db.commit()

    # Mock send to always fail so we can observe attempts/backoff
    with patch(
        "app.services.messaging.send_whatsapp_message",
        side_effect=Exception("Mock send failure"),
    ):
        response = client.post(
            "/admin/outbox/retry?limit=50",
            headers=admin_headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["outbox_retry"]["retried"] == 50
    assert data["outbox_retry"]["failed"] == 50

    # Exactly 50 should have been retried (attempts incremented, next_retry_at updated)
    from sqlalchemy import func, select

    retried = db.execute(
        select(func.count())
        .select_from(OutboxMessage)
        .where(OutboxMessage.status == "FAILED", OutboxMessage.attempts == 2)
    ).scalar()
    assert retried == 50

    # 50 should be untouched (still attempts=1)
    untouched = db.execute(
        select(func.count())
        .select_from(OutboxMessage)
        .where(OutboxMessage.status == "FAILED", OutboxMessage.attempts == 1)
    ).scalar()
    assert untouched == 50


def test_outbox_retry_backoff_increments_next_retry_at(
    client, db, admin_headers, setup_admin_key, monkeypatch
):
    """On retry failure, attempts increments and next_retry_at increases (backoff)."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "outbox_enabled", True)

    lead = Lead(wa_from="447700900101", status="NEW")
    db.add(lead)
    db.commit()
    db.refresh(lead)

    msg = OutboxMessage(
        lead_id=lead.id,
        channel="whatsapp",
        payload_json={"to": lead.wa_from, "message": "Test"},
        status="FAILED",
        attempts=1,
        last_error="Previous failure",
        next_retry_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    prev_attempts = msg.attempts
    prev_next_retry = msg.next_retry_at

    with patch(
        "app.services.messaging.send_whatsapp_message",
        side_effect=Exception("Mock failure"),
    ):
        client.post("/admin/outbox/retry?limit=1", headers=admin_headers)

    db.refresh(msg)
    assert msg.attempts == prev_attempts + 1
    assert msg.next_retry_at is not None
    assert msg.next_retry_at > prev_next_retry or prev_next_retry is None


# =============================================================================
# WhatsApp webhook retry storm
# =============================================================================


def _make_whatsapp_payload(wa_from: str, text: str, message_id: str):
    """Build WhatsApp webhook payload with given message_id."""
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
                                    "timestamp": str(int(datetime.now(UTC).timestamp())),
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }


def test_whatsapp_retry_storm_same_message_id_20_concurrent_only_one_advances(client, db):
    """Send same message_id 20 times concurrently; only 1 advances step, others are duplicates."""
    # Create lead in QUALIFYING at step 0 (idea question)
    lead = Lead(
        wa_from="447700900200",
        status=STATUS_QUALIFYING,
        current_step=0,
        qualifying_started_at=datetime.now(UTC),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    payload = _make_whatsapp_payload(
        wa_from="447700900200",
        text="A dragon tattoo on my arm",
        message_id="wamid.storm_test_001",
    )

    def post_webhook():
        return client.post("/webhooks/whatsapp", json=payload)

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(post_webhook) for _ in range(20)]
        responses = [f.result() for f in as_completed(futures)]

    assert len(responses) == 20
    success_count = sum(1 for r in responses if r.status_code == 200)
    assert success_count == 20

    # Exactly 1 should have "conversation" (processed); others "duplicate"
    duplicate = [r for r in responses if r.json().get("type") == "duplicate"]
    processed = [r for r in responses if "conversation" in r.json()]

    assert len(duplicate) == 19, f"Expected 19 duplicates, got {len(duplicate)}"
    assert len(processed) == 1, f"Expected 1 processed, got {len(processed)}"

    # Verify lead advanced exactly once
    db.refresh(lead)
    assert lead.current_step == 1


def test_whatsapp_retry_storm_outbox_at_most_once(client, db, monkeypatch):
    """With OUTBOX_ENABLED, same message_id 20x concurrent → outbox created at most once."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "outbox_enabled", True)

    lead = Lead(
        wa_from="447700900201",
        status=STATUS_QUALIFYING,
        current_step=0,
        qualifying_started_at=datetime.now(UTC),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    payload = _make_whatsapp_payload(
        wa_from="447700900201",
        text="Upper arm",
        message_id="wamid.storm_test_002",
    )

    def post_webhook():
        return client.post("/webhooks/whatsapp", json=payload)

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(post_webhook) for _ in range(20)]
        list(as_completed(futures))

    # Count outbox rows for this lead (only from the one processed message)
    from sqlalchemy import func, select

    outbox_count = db.execute(
        select(func.count()).select_from(OutboxMessage).where(OutboxMessage.lead_id == lead.id)
    ).scalar()
    assert outbox_count <= 1, f"Outbox should have at most 1 row, got {outbox_count}"
