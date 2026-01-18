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
