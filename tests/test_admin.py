import pytest
from app.db.models import Lead


def test_list_leads_empty(client):
    """Test listing leads when database is empty."""
    response = client.get("/admin/leads")
    assert response.status_code == 200
    assert response.json() == []


def test_list_leads_with_data(client, db):
    """Test listing leads returns all leads ordered by creation date."""
    from datetime import datetime, timezone
    
    # Create test leads with explicit timestamps to ensure ordering
    now = datetime.now(timezone.utc)
    lead1 = Lead(wa_from="1111111111", status="NEW", created_at=now)
    # Use timedelta to avoid second overflow
    from datetime import timedelta
    lead2 = Lead(wa_from="2222222222", status="CONTACTED", created_at=now + timedelta(seconds=1))
    lead3 = Lead(wa_from="3333333333", status="NEW", created_at=now + timedelta(seconds=2))

    db.add(lead1)
    db.add(lead2)
    db.add(lead3)
    db.commit()

    response = client.get("/admin/leads")
    assert response.status_code == 200
    data = response.json()

    assert len(data) == 3
    # Should be ordered by created_at desc (newest first)
    # Extract phone numbers to check order
    phone_numbers = [lead["wa_from"] for lead in data]
    assert phone_numbers == ["3333333333", "2222222222", "1111111111"]

    # Check structure
    for lead in data:
        assert "id" in lead
        assert "wa_from" in lead
        assert "status" in lead
        assert "created_at" in lead


def test_list_leads_after_webhook(client):
    """Test that leads created via webhook appear in admin list."""
    # Create lead via webhook
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "9999999999",
                                    "text": {"body": "Test message"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    webhook_response = client.post("/webhooks/whatsapp", json=payload)
    assert webhook_response.status_code == 200
    lead_id = webhook_response.json()["lead_id"]

    # Verify it appears in admin list
    response = client.get("/admin/leads")
    assert response.status_code == 200
    data = response.json()

    assert len(data) == 1
    assert data[0]["id"] == lead_id
    assert data[0]["wa_from"] == "9999999999"
    # Webhook now automatically transitions NEW -> QUALIFYING when message is received
    assert data[0]["status"] == "QUALIFYING"
