"""
Tests for webhook idempotency - preventing duplicate message processing.
"""

from sqlalchemy import select

from app.db.models import Lead, ProcessedMessage


def test_duplicate_message_id_ignored(client, db):
    """Test that duplicate message IDs are ignored."""
    message_id = "wamid.test123"

    # First message - should process normally
    payload1 = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": message_id,
                                    "from": "1234567890",
                                    "text": {"body": "First message"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    response1 = client.post("/webhooks/whatsapp", json=payload1)
    assert response1.status_code == 200
    data1 = response1.json()
    assert data1["received"] is True
    assert "lead_id" in data1

    # Check message was marked as processed
    stmt = select(ProcessedMessage).where(
        ProcessedMessage.provider == "whatsapp",
        ProcessedMessage.message_id == message_id,
    )
    processed = db.execute(stmt).scalar_one_or_none()
    assert processed is not None
    assert processed.lead_id == data1["lead_id"]

    # Second message with same ID - should be ignored
    payload2 = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": message_id,
                                    "from": "1234567890",
                                    "text": {"body": "Duplicate message"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    response2 = client.post("/webhooks/whatsapp", json=payload2)
    assert response2.status_code == 200
    data2 = response2.json()
    assert data2["received"] is True
    assert data2["type"] == "duplicate"
    assert data2["message_id"] == message_id

    # Should still have only one processed message record
    processed_count = (
        db.query(ProcessedMessage)
        .filter(
            ProcessedMessage.provider == "whatsapp",
            ProcessedMessage.message_id == message_id,
        )
        .count()
    )
    assert processed_count == 1

    # Should not have created a new answer (duplicate was ignored)
    lead = db.query(Lead).filter(Lead.id == data1["lead_id"]).first()
    # The first message would have started qualification, but duplicate shouldn't add another answer


def test_different_message_ids_processed(client, db):
    """Test that different message IDs are processed separately."""
    message_id1 = "wamid.test123"
    message_id2 = "wamid.test456"

    # First message
    payload1 = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": message_id1,
                                    "from": "1234567890",
                                    "text": {"body": "First message"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    response1 = client.post("/webhooks/whatsapp", json=payload1)
    assert response1.status_code == 200

    # Second message with different ID
    payload2 = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": message_id2,
                                    "from": "1234567890",
                                    "text": {"body": "Second message"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    response2 = client.post("/webhooks/whatsapp", json=payload2)
    assert response2.status_code == 200
    data2 = response2.json()
    assert data2["received"] is True
    # Normal processing doesn't have "type" field (only duplicates/non-messages do)
    assert "type" not in data2 or data2.get("type") != "duplicate"
    # Should have conversation result for normal processing
    assert "conversation" in data2 or "lead_id" in data2

    # Should have two processed message records
    processed_count = db.query(ProcessedMessage).count()
    assert processed_count == 2


def test_message_without_id_still_processed(client, db):
    """Test that messages without ID are still processed (for backward compatibility)."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    # No "id" field
                                    "from": "1234567890",
                                    "text": {"body": "Message without ID"},
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
    assert "lead_id" in data

    # Should not have created a processed_message record (no message_id)
    processed_count = db.query(ProcessedMessage).count()
    assert processed_count == 0
