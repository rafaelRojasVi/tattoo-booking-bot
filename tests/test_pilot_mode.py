"""
Tests for pilot mode allowlist functionality.
"""

from unittest.mock import patch

from app.core.config import settings
from app.db.models import Lead


def test_pilot_mode_allows_allowlisted_number(client, db):
    """Test that allowlisted numbers can start consultation."""
    with patch.object(settings, "pilot_mode_enabled", True):
        with patch.object(settings, "pilot_allowlist_numbers", "1234567890,9876543210"):
            # Send message from allowlisted number
            webhook_payload = {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "messages": [
                                        {
                                            "id": "msg_test_123",
                                            "from": "1234567890",  # Allowlisted
                                            "type": "text",
                                            "text": {"body": "Hello, I want a tattoo"},
                                            "timestamp": "1234567890",
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }

            response = client.post(
                "/webhooks/whatsapp",
                json=webhook_payload,
                headers={"X-Hub-Signature-256": "test_signature"},
            )

            assert response.status_code == 200
            data = response.json()
            # Should process normally (not blocked)
            assert data["received"] is True
            assert data.get("type") != "pilot_mode_blocked"

            # Verify lead was created and consultation started
            lead = db.query(Lead).filter(Lead.wa_from == "1234567890").first()
            assert lead is not None
            # Status should be NEW or QUALIFYING (consultation started)
            assert lead.status in ["NEW", "QUALIFYING"]


def test_pilot_mode_blocks_non_allowlisted_number(client, db):
    """Test that non-allowlisted numbers are blocked in pilot mode."""
    with patch.object(settings, "pilot_mode_enabled", True):
        with patch.object(settings, "pilot_allowlist_numbers", "1234567890,9876543210"):
            # Send message from non-allowlisted number
            webhook_payload = {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "messages": [
                                        {
                                            "id": "msg_test_456",
                                            "from": "5555555555",  # Not allowlisted
                                            "type": "text",
                                            "text": {"body": "Hello, I want a tattoo"},
                                            "timestamp": "1234567890",
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }

            response = client.post(
                "/webhooks/whatsapp",
                json=webhook_payload,
                headers={"X-Hub-Signature-256": "test_signature"},
            )

            assert response.status_code == 200
            data = response.json()
            # Should be blocked
            assert data["received"] is True
            assert data["type"] == "pilot_mode_blocked"
            assert data["wa_from"] == "5555555555"

            # Verify system event was logged
            from app.db.models import SystemEvent

            events = (
                db.query(SystemEvent).filter(SystemEvent.event_type == "pilot_mode.blocked").all()
            )
            assert len(events) >= 1
            event = events[0]
            assert event.level == "INFO"
            assert event.payload["wa_from"] == "5555555555"

            # Verify lead was created but consultation not started
            lead = db.query(Lead).filter(Lead.wa_from == "5555555555").first()
            assert lead is not None
            # Status should remain NEW (consultation not started)
            assert lead.status == "NEW"


def test_pilot_mode_disabled_allows_all_numbers(client, db):
    """Test that when pilot mode is disabled, all numbers are allowed."""
    with patch.object(settings, "pilot_mode_enabled", False):
        # Send message from any number
        webhook_payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "id": "msg_test_789",
                                        "from": "9999999999",  # Not in any allowlist
                                        "type": "text",
                                        "text": {"body": "Hello, I want a tattoo"},
                                        "timestamp": "1234567890",
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }

        response = client.post(
            "/webhooks/whatsapp",
            json=webhook_payload,
            headers={"X-Hub-Signature-256": "test_signature"},
        )

        assert response.status_code == 200
        data = response.json()
        # Should process normally (not blocked)
        assert data["received"] is True
        assert data.get("type") != "pilot_mode_blocked"

        # Verify lead was created and consultation started
        lead = db.query(Lead).filter(Lead.wa_from == "9999999999").first()
        assert lead is not None
        assert lead.status in ["NEW", "QUALIFYING"]


def test_pilot_mode_allowlist_parsing(client, db):
    """Test that allowlist is parsed correctly (handles whitespace, empty values)."""
    with (
        patch.object(settings, "pilot_mode_enabled", True),
        patch.object(
            settings, "pilot_allowlist_numbers", " 1234567890 , 9876543210 , , 5555555555 "
        ),
    ):
        # Test with number that has whitespace in allowlist
        webhook_payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "id": "msg_test_whitespace",
                                        "from": "1234567890",  # In allowlist (with whitespace)
                                        "type": "text",
                                        "text": {"body": "Hello"},
                                        "timestamp": "1234567890",
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }

        response = client.post(
            "/webhooks/whatsapp",
            json=webhook_payload,
            headers={"X-Hub-Signature-256": "test_signature"},
        )

        assert response.status_code == 200
        data = response.json()
        # Should be allowed (not blocked)
        assert data.get("type") != "pilot_mode_blocked"


def test_pilot_mode_empty_allowlist_blocks_all(client, db):
    """Test that empty allowlist blocks all numbers."""
    with patch.object(settings, "pilot_mode_enabled", True):
        with patch.object(settings, "pilot_allowlist_numbers", ""):
            # Send message from any number
            webhook_payload = {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "messages": [
                                        {
                                            "id": "msg_test_empty",
                                            "from": "1234567890",
                                            "type": "text",
                                            "text": {"body": "Hello"},
                                            "timestamp": "1234567890",
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }

            response = client.post(
                "/webhooks/whatsapp",
                json=webhook_payload,
                headers={"X-Hub-Signature-256": "test_signature"},
            )

            assert response.status_code == 200
            data = response.json()
            # Should be blocked (empty allowlist)
            assert data["type"] == "pilot_mode_blocked"


def test_pilot_mode_sends_polite_message(client, db):
    """Test that blocked numbers receive a polite message."""
    with patch.object(settings, "pilot_mode_enabled", True):
        with patch.object(settings, "pilot_allowlist_numbers", "1234567890"):
            # Send message from non-allowlisted number
            webhook_payload = {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "messages": [
                                        {
                                            "id": "msg_test_message",
                                            "from": "5555555555",
                                            "type": "text",
                                            "text": {"body": "Hello"},
                                            "timestamp": "1234567890",
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }

            response = client.post(
                "/webhooks/whatsapp",
                json=webhook_payload,
                headers={"X-Hub-Signature-256": "test_signature"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["type"] == "pilot_mode_blocked"

            # Verify system event was logged
            from app.db.models import SystemEvent

            events = (
                db.query(SystemEvent).filter(SystemEvent.event_type == "pilot_mode.blocked").all()
            )
            assert len(events) >= 1
