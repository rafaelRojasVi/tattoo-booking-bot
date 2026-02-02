def test_whatsapp_verify_success(client):
    """Test WhatsApp webhook verification succeeds with correct token."""
    # Import settings after env vars are set in conftest
    from app.core.config import settings

    response = client.get(
        "/webhooks/whatsapp",
        params={
            "hub_mode": "subscribe",
            "hub_verify_token": settings.whatsapp_verify_token,
            "hub_challenge": "test_challenge_123",
        },
    )
    assert response.status_code == 200
    assert response.text == "test_challenge_123"


def test_whatsapp_verify_fails_wrong_token(client):
    """Test WhatsApp webhook verification fails with wrong token."""

    response = client.get(
        "/webhooks/whatsapp",
        params={
            "hub_mode": "subscribe",
            "hub_verify_token": "wrong_token",
            "hub_challenge": "test_challenge_123",
        },
    )
    assert response.status_code == 403


def test_whatsapp_verify_fails_wrong_mode(client):
    """Test WhatsApp webhook verification fails with wrong mode."""
    from app.core.config import settings

    response = client.get(
        "/webhooks/whatsapp",
        params={
            "hub_mode": "unsubscribe",
            "hub_verify_token": settings.whatsapp_verify_token,
            "hub_challenge": "test_challenge_123",
        },
    )
    assert response.status_code == 403


def test_whatsapp_inbound_creates_lead(client):
    """Test that receiving a WhatsApp message creates a new lead."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1234567890",
                                    "text": {"body": "Hello, I want a tattoo"},
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
    assert data["received"] is True
    assert data["wa_from"] == "1234567890"
    assert data["text"] == "Hello, I want a tattoo"
    assert "lead_id" in data
    assert data["lead_id"] is not None


def test_whatsapp_inbound_existing_lead(client, db):
    """Test that receiving a message from existing lead returns same lead."""
    from app.db.models import Lead

    # Create existing lead
    existing_lead = Lead(wa_from="1234567890", status="NEW")
    db.add(existing_lead)
    db.commit()
    db.refresh(existing_lead)

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1234567890",
                                    "text": {"body": "Follow up message"},
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
    assert data["lead_id"] == existing_lead.id


def test_whatsapp_inbound_non_message_event(client):
    """Test that non-message events (delivery receipts) are handled gracefully."""
    payload = {
        "entry": [{"changes": [{"value": {"statuses": [{"id": "123", "status": "delivered"}]}}]}]
    }

    response = client.post("/webhooks/whatsapp", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["received"] is True
    assert data["type"] == "non-message-event"
    assert "lead_id" not in data


def test_whatsapp_inbound_malformed_payload(client):
    """Test that malformed payloads don't crash the endpoint."""
    payload = {"invalid": "payload"}

    response = client.post("/webhooks/whatsapp", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["received"] is True
    # Empty entry array returns "empty-entry" type
    assert data["type"] in ["non-message-event", "empty-entry", "malformed-payload"]


def test_whatsapp_signature_verification_valid(client, monkeypatch):
    """Test that valid WhatsApp webhook signature is accepted."""
    import hashlib
    import hmac
    import json

    from app.core.config import settings

    # Set app secret for testing
    test_app_secret = "test_app_secret_12345"
    monkeypatch.setattr(settings, "whatsapp_app_secret", test_app_secret)

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1234567890",
                                    "id": "wamid.test123",
                                    "text": {"body": "Hello"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    # Convert payload to bytes
    payload_bytes = json.dumps(payload).encode("utf-8")

    # Compute HMAC-SHA256 signature
    signature = hmac.new(test_app_secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    signature_header = f"sha256={signature}"

    # Send request with signature header
    response = client.post(
        "/webhooks/whatsapp",
        content=payload_bytes,
        headers={"X-Hub-Signature-256": signature_header, "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["received"] is True
    assert data["wa_from"] == "1234567890"


def test_whatsapp_signature_verification_invalid(client, monkeypatch):
    """Test that invalid WhatsApp webhook signature is rejected with 403."""
    import json

    # Force verification to run and fail (patch at point of use so webhook sees it)
    def _verify_fail(_payload: bytes, _sig: str | None) -> bool:
        return False

    monkeypatch.setattr(
        "app.api.webhooks.verify_whatsapp_signature",
        _verify_fail,
    )

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1234567890",
                                    "id": "wamid.test123",
                                    "text": {"body": "Hello"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    # Convert payload to bytes
    payload_bytes = json.dumps(payload).encode("utf-8")

    # Use invalid signature
    invalid_signature = "sha256=0000000000000000000000000000000000000000000000000000000000000000"

    # Send request with invalid signature header
    response = client.post(
        "/webhooks/whatsapp",
        content=payload_bytes,
        headers={"X-Hub-Signature-256": invalid_signature, "Content-Type": "application/json"},
    )

    assert response.status_code == 403
    data = response.json()
    assert data["received"] is False
    assert "Invalid webhook signature" in data["error"]


def test_whatsapp_signature_verification_missing_header(client, monkeypatch):
    """Test that missing signature header is rejected with 403 when app secret is set."""
    import json

    # Force verification to run and fail (patch at point of use so webhook sees it)
    def _verify_fail(_payload: bytes, _sig: str | None) -> bool:
        return False

    monkeypatch.setattr(
        "app.api.webhooks.verify_whatsapp_signature",
        _verify_fail,
    )

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1234567890",
                                    "id": "wamid.test123",
                                    "text": {"body": "Hello"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    # Convert payload to bytes
    payload_bytes = json.dumps(payload).encode("utf-8")

    # Send request without signature header
    response = client.post(
        "/webhooks/whatsapp",
        content=payload_bytes,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 403
    data = response.json()
    assert data["received"] is False
    assert "Invalid webhook signature" in data["error"]


def test_whatsapp_signature_verification_no_app_secret_allows_request(client, monkeypatch):
    """Test that when app secret is not configured, requests are allowed (dev mode)."""
    import json

    from app.core.config import settings

    # Ensure app secret is not set
    monkeypatch.setattr(settings, "whatsapp_app_secret", None)

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1234567890",
                                    "id": "wamid.test123",
                                    "text": {"body": "Hello"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    # Convert payload to bytes
    payload_bytes = json.dumps(payload).encode("utf-8")

    # Send request without signature header (should be allowed in dev mode)
    response = client.post(
        "/webhooks/whatsapp",
        content=payload_bytes,
        headers={"Content-Type": "application/json"},
    )

    # Should succeed when app secret is not configured
    assert response.status_code == 200
    data = response.json()
    assert data["received"] is True
