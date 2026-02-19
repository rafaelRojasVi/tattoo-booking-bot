from unittest.mock import patch


def test_whatsapp_inbound_image_message(client):
    """Test handling of image messages with caption."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1234567890",
                                    "type": "image",
                                    "image": {"id": "img123"},
                                    "caption": "Check out this design",
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
    assert data["text"] == "Check out this design"
    assert data["message_type"] == "image"


def test_whatsapp_inbound_image_no_caption(client):
    """Test image message without caption."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1234567890",
                                    "type": "image",
                                    "image": {"id": "img123"},
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
    assert data["text"] == "[image message]"


def test_whatsapp_inbound_video_message(client):
    """Test handling of video messages."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1234567890",
                                    "type": "video",
                                    "video": {"id": "vid123"},
                                    "caption": "My tattoo process",
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
    assert data["message_type"] == "video"
    assert data["text"] == "My tattoo process"


def test_whatsapp_inbound_location_message(client):
    """Test handling of location messages."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1234567890",
                                    "type": "location",
                                    "location": {
                                        "latitude": 51.5074,
                                        "longitude": -0.1278,
                                    },
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
    assert data["message_type"] == "location"
    assert "[Location:" in data["text"]


def test_whatsapp_inbound_audio_message(client):
    """Test handling of audio/voice messages."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1234567890",
                                    "type": "audio",
                                    "audio": {"id": "audio123"},
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
    assert data["message_type"] == "audio"
    assert data["text"] == "[audio message]"


def test_whatsapp_inbound_empty_text(client):
    """Test message with empty text body."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1234567890",
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
    data = response.json()
    assert data["wa_from"] == "1234567890"
    assert data["text"] == ""


def test_whatsapp_inbound_missing_text_field(client):
    """Test message with missing text field."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1234567890",
                                    "type": "text",
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
    assert data["wa_from"] == "1234567890"
    assert data["text"] is None


def test_whatsapp_inbound_invalid_phone_number(client):
    """Test rejection of invalid phone numbers."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "123",  # Too short
                                    "text": {"body": "Hello"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    response = client.post("/webhooks/whatsapp", json=payload)
    assert response.status_code == 400
    data = response.json()
    assert "error" in data
    assert "phone number" in data["error"].lower()


def test_whatsapp_inbound_empty_phone_number(client):
    """Test rejection of empty phone number."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "",
                                    "text": {"body": "Hello"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    response = client.post("/webhooks/whatsapp", json=payload)
    assert response.status_code == 400


def test_whatsapp_inbound_empty_entry(client):
    """Test handling of payload with empty entry array."""
    payload: dict[str, list] = {"entry": []}

    response = client.post("/webhooks/whatsapp", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "empty-entry"


def test_whatsapp_inbound_empty_changes(client):
    """Test handling of payload with empty changes array."""
    payload: dict[str, list] = {"entry": [{"changes": []}]}

    response = client.post("/webhooks/whatsapp", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "empty-changes"


def test_whatsapp_inbound_invalid_json(client):
    """Test handling of invalid JSON payload."""
    response = client.post(
        "/webhooks/whatsapp",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    data = response.json()
    assert "error" in data


def test_whatsapp_inbound_database_error(client, db):
    """Test handling of database errors."""
    from sqlalchemy.exc import SQLAlchemyError

    # Mock database error
    with patch("app.api.webhooks.get_or_create_lead") as mock_get_lead:
        mock_get_lead.side_effect = SQLAlchemyError("Database connection failed")

        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "1234567890",
                                        "text": {"body": "Hello"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }

        response = client.post("/webhooks/whatsapp", json=payload)
        assert response.status_code == 500
        data = response.json()
        assert "error" in data
        assert "Database" in data["error"]


def test_whatsapp_inbound_service_validation_error(client):
    """Test service layer validation error handling."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": None,  # Invalid
                                    "text": {"body": "Hello"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    response = client.post("/webhooks/whatsapp", json=payload)
    # Should handle gracefully (returns non-message-event)
    assert response.status_code == 200


def test_whatsapp_inbound_multiple_messages(client):
    """Test handling when multiple messages are in the payload."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1111111111",
                                    "text": {"body": "First message"},
                                },
                                {
                                    "from": "2222222222",
                                    "text": {"body": "Second message"},
                                },
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
    # Should process first message only
    assert data["wa_from"] == "1111111111"
    assert data["text"] == "First message"


def test_whatsapp_inbound_document_message(client):
    """Test handling of document messages."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1234567890",
                                    "type": "document",
                                    "document": {"id": "doc123", "filename": "design.pdf"},
                                    "caption": "My tattoo design",
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
    assert data["message_type"] == "document"
    assert data["text"] == "My tattoo design"
