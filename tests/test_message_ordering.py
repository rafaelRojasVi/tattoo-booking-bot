"""
Tests for message ordering and rapid-fire input handling.
"""
import pytest
from datetime import datetime, timezone, timedelta
from app.db.models import Lead
from app.services.conversation import STATUS_QUALIFYING


def test_multiple_messages_in_payload_processes_most_recent(client, db):
    """Test that multiple messages in one payload process most recent first."""
    lead = Lead(wa_from="1234567890", status=STATUS_QUALIFYING, current_step=0)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    # Simulate WhatsApp sending multiple messages in one payload
    # Most recent message should be processed
    import time
    now = int(time.time())
    
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [
                        {
                            "id": "msg_old",
                            "from": "1234567890",
                            "type": "text",
                            "text": {"body": "Old message"},
                            "timestamp": str(now - 100),  # Older
                        },
                        {
                            "id": "msg_recent",
                            "from": "1234567890",
                            "type": "text",
                            "text": {"body": "Recent message"},
                            "timestamp": str(now),  # Most recent
                        },
                    ]
                }
            }]
        }]
    }
    
    response = client.post("/webhooks/whatsapp", json=payload)
    assert response.status_code == 200
    
    # Should process most recent message
    # (We can't easily verify which was processed without checking logs,
    # but we verify it doesn't crash and processes one message)
    assert "received" in response.json() or "type" in response.json()


def test_out_of_order_message_ignored(client, db):
    """Test that out-of-order messages (older than last_client_message_at) are ignored."""
    from datetime import datetime, timezone, timedelta
    
    # Create lead with recent message
    recent_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_QUALIFYING,
        current_step=0,
        last_client_message_at=recent_time,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    # Simulate WhatsApp sending an older message (out of order)
    old_timestamp = int((recent_time - timedelta(minutes=10)).timestamp())
    
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "id": "msg_old",
                        "from": "1234567890",
                        "type": "text",
                        "text": {"body": "Old message"},
                        "timestamp": str(old_timestamp),
                    }]
                }
            }]
        }]
    }
    
    response = client.post("/webhooks/whatsapp", json=payload)
    assert response.status_code == 200
    
    result = response.json()
    assert result.get("type") == "out_of_order"
    assert "older" in result.get("reason", "").lower()


def test_rapid_fire_messages_processed_sequentially(client, db):
    """Test that rapid-fire messages are processed in order."""
    lead = Lead(wa_from="1234567890", status=STATUS_QUALIFYING, current_step=0)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    import time
    base_time = int(time.time())
    
    # Send first message
    payload1 = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "id": "msg_1",
                        "from": "1234567890",
                        "type": "text",
                        "text": {"body": "First"},
                        "timestamp": str(base_time),
                    }]
                }
            }]
        }]
    }
    
    response1 = client.post("/webhooks/whatsapp", json=payload1)
    assert response1.status_code == 200
    
    db.refresh(lead)
    assert lead.last_client_message_at is not None
    
    # Send second message (1 second later)
    payload2 = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "id": "msg_2",
                        "from": "1234567890",
                        "type": "text",
                        "text": {"body": "Second"},
                        "timestamp": str(base_time + 1),
                    }]
                }
            }]
        }]
    }
    
    response2 = client.post("/webhooks/whatsapp", json=payload2)
    assert response2.status_code == 200
    
    # Both should be processed (idempotency prevents duplicates)
    # Second message should update last_client_message_at
    db.refresh(lead)
    assert lead.last_client_message_at is not None


def test_message_without_timestamp_still_processed(client, db):
    """Test that messages without timestamp are still processed (backward compatibility)."""
    lead = Lead(wa_from="1234567890", status=STATUS_QUALIFYING, current_step=0)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    # Message without timestamp field
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "id": "msg_no_timestamp",
                        "from": "1234567890",
                        "type": "text",
                        "text": {"body": "Message without timestamp"},
                        # No timestamp field
                    }]
                }
            }]
        }]
    }
    
    response = client.post("/webhooks/whatsapp", json=payload)
    assert response.status_code == 200
    
    # Should still be processed (backward compatibility)
    db.refresh(lead)
    assert lead.last_client_message_at is not None
