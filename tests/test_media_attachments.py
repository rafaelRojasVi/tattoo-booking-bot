"""
Comprehensive tests for media attachment handling and edge cases.

Tests cover:
- Image/document message handling
- Attachment creation
- Upload retry logic
- Error handling
- Status transitions
- Edge cases
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from app.db.models import Attachment, Lead
from app.jobs.sweep_pending_uploads import run_sweep
from app.services.media_upload import attempt_upload_attachment


@pytest.fixture
def lead(db):
    """Create a test lead."""
    lead = Lead(
        wa_from="1234567890",
        status="QUALIFYING",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


@pytest.fixture
def whatsapp_image_payload():
    """Sample WhatsApp image message payload."""
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1234567890",
                                    "id": "wamid.123",
                                    "type": "image",
                                    "image": {"id": "media_123", "mime_type": "image/jpeg"},
                                    "timestamp": "1234567890",
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }


@pytest.fixture
def whatsapp_image_with_caption_payload():
    """WhatsApp image message with caption."""
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1234567890",
                                    "id": "wamid.124",
                                    "type": "image",
                                    "image": {"id": "media_124", "mime_type": "image/png"},
                                    "caption": "This is my reference design",
                                    "timestamp": "1234567891",
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }


@pytest.fixture
def whatsapp_document_payload():
    """WhatsApp document message payload."""
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1234567890",
                                    "id": "wamid.125",
                                    "type": "document",
                                    "document": {
                                        "id": "media_125",
                                        "mime_type": "application/pdf",
                                        "filename": "design.pdf",
                                    },
                                    "timestamp": "1234567892",
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }


@pytest.fixture
def whatsapp_multiple_media_payload():
    """WhatsApp payload with multiple media messages."""
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1234567890",
                                    "id": "wamid.126",
                                    "type": "image",
                                    "image": {"id": "media_126"},
                                    "timestamp": "1234567893",
                                },
                                {
                                    "from": "1234567890",
                                    "id": "wamid.127",
                                    "type": "image",
                                    "image": {"id": "media_127"},
                                    "timestamp": "1234567894",
                                },
                            ]
                        }
                    }
                ]
            }
        ]
    }


def test_webhook_creates_attachment_for_image(
    client, db, lead, whatsapp_image_payload, monkeypatch
):
    """Test that webhook creates Attachment record for image messages."""
    # Mock signature verification
    with patch("app.api.webhooks.verify_whatsapp_signature", return_value=True):
        # Mock background task (we'll verify attachment creation, not upload)
        with patch("app.services.media_upload.attempt_upload_attachment_job") as mock_upload:
            response = client.post(
                "/webhooks/whatsapp",
                json=whatsapp_image_payload,
                headers={"X-Hub-Signature-256": "sha256=test"},
            )

            assert response.status_code == 200

            # Verify attachment was created
            attachment = (
                db.query(Attachment).filter(Attachment.whatsapp_media_id == "media_123").first()
            )
            assert attachment is not None
            assert attachment.lead_id == lead.id
            assert attachment.upload_status == "PENDING"
            assert attachment.upload_attempts == 0
            assert attachment.whatsapp_media_id == "media_123"
            assert attachment.provider == "supabase"

            # Verify background task was scheduled
            mock_upload.assert_called_once()


def test_webhook_creates_attachment_for_image_with_caption(
    client, db, lead, whatsapp_image_with_caption_payload, monkeypatch
):
    """Test attachment creation for image with caption."""
    with patch("app.api.webhooks.verify_whatsapp_signature", return_value=True):
        with patch("app.services.media_upload.attempt_upload_attachment_job"):
            response = client.post(
                "/webhooks/whatsapp",
                json=whatsapp_image_with_caption_payload,
                headers={"X-Hub-Signature-256": "sha256=test"},
            )

            assert response.status_code == 200

            # Verify attachment was created
            attachment = (
                db.query(Attachment).filter(Attachment.whatsapp_media_id == "media_124").first()
            )
            assert attachment is not None
            assert attachment.upload_status == "PENDING"


def test_webhook_creates_attachment_for_document(
    client, db, lead, whatsapp_document_payload, monkeypatch
):
    """Test attachment creation for document messages."""
    with patch("app.api.webhooks.verify_whatsapp_signature", return_value=True):
        with patch("app.services.media_upload.attempt_upload_attachment_job"):
            response = client.post(
                "/webhooks/whatsapp",
                json=whatsapp_document_payload,
                headers={"X-Hub-Signature-256": "sha256=test"},
            )

            assert response.status_code == 200

            # Verify attachment was created
            attachment = (
                db.query(Attachment).filter(Attachment.whatsapp_media_id == "media_125").first()
            )
            assert attachment is not None
            assert attachment.upload_status == "PENDING"


def test_webhook_handles_multiple_media_messages(
    client, db, lead, whatsapp_multiple_media_payload, monkeypatch
):
    """Test that webhook processes most recent media when multiple messages arrive."""
    with patch("app.api.webhooks.verify_whatsapp_signature", return_value=True):
        with patch("app.services.media_upload.attempt_upload_attachment_job"):
            response = client.post(
                "/webhooks/whatsapp",
                json=whatsapp_multiple_media_payload,
                headers={"X-Hub-Signature-256": "sha256=test"},
            )

            assert response.status_code == 200

            # Should create attachment for most recent message (media_127, timestamp 1234567894)
            attachment = (
                db.query(Attachment).filter(Attachment.whatsapp_media_id == "media_127").first()
            )
            assert attachment is not None

            # Should NOT create attachment for older message
            old_attachment = (
                db.query(Attachment).filter(Attachment.whatsapp_media_id == "media_126").first()
            )
            assert old_attachment is None


def test_webhook_ignores_non_media_messages(client, db, lead, monkeypatch):
    """Test that non-media messages don't create attachments."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1234567890",
                                    "id": "wamid.128",
                                    "type": "text",
                                    "text": {"body": "Hello"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    with patch("app.api.webhooks.verify_whatsapp_signature", return_value=True):
        response = client.post(
            "/webhooks/whatsapp",
            json=payload,
            headers={"X-Hub-Signature-256": "sha256=test"},
        )

        assert response.status_code == 200

        # No attachment should be created for text messages
        attachment = db.query(Attachment).first()
        assert attachment is None


def test_webhook_handles_media_without_media_id(client, db, lead, monkeypatch):
    """Test webhook handles media messages with missing media ID gracefully."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1234567890",
                                    "id": "wamid.129",
                                    "type": "image",
                                    "image": {},  # No id field
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    with patch("app.api.webhooks.verify_whatsapp_signature", return_value=True):
        with patch("app.services.media_upload.attempt_upload_attachment_job"):
            response = client.post(
                "/webhooks/whatsapp",
                json=payload,
                headers={"X-Hub-Signature-256": "sha256=test"},
            )

            assert response.status_code == 200

            # No attachment should be created if media_id is missing
            attachment = db.query(Attachment).filter(Attachment.whatsapp_media_id.is_(None)).first()
            assert attachment is None


@pytest.mark.asyncio
async def test_upload_success_transitions_to_uploaded(db, lead):
    """Test successful upload transitions status to UPLOADED."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_success",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with (
        patch("app.services.media_upload._download_whatsapp_media") as mock_download,
        patch("app.services.media_upload._upload_to_supabase") as mock_upload,
    ):
        mock_download.return_value = (b"fake_image_data", "image/jpeg")
        mock_upload.return_value = None

        await attempt_upload_attachment(db, attachment.id)

        db.refresh(attachment)
        assert attachment.upload_status == "UPLOADED"
        assert attachment.uploaded_at is not None
        assert attachment.bucket == "reference-images"
        assert attachment.object_key == f"leads/{lead.id}/{attachment.id}"
        assert attachment.content_type == "image/jpeg"
        assert attachment.size_bytes == len(b"fake_image_data")
        assert attachment.last_error is None


@pytest.mark.asyncio
async def test_upload_failure_increments_attempts(db, lead):
    """Test that upload failure increments attempts and stores error."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_fail",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with (
        patch("app.services.media_upload._download_whatsapp_media") as mock_download,
        patch("app.services.system_event_service.error") as mock_error,
    ):
        mock_download.side_effect = Exception("WhatsApp API error: Media not found")

        await attempt_upload_attachment(db, attachment.id)

        db.refresh(attachment)
        assert attachment.upload_status == "PENDING"  # Still pending, not failed yet
        assert attachment.upload_attempts == 1
        assert attachment.last_attempt_at is not None
        assert attachment.last_error is not None
        assert "WhatsApp API error" in attachment.last_error
        assert attachment.uploaded_at is None


@pytest.mark.asyncio
async def test_upload_fails_after_5_attempts(db, lead):
    """Test that attachment is marked FAILED after 5 failed attempts."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_fail_5",
        upload_status="PENDING",
        upload_attempts=4,  # Already tried 4 times
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with (
        patch("app.services.media_upload._download_whatsapp_media") as mock_download,
        patch("app.services.system_event_service.error") as mock_error,
    ):
        mock_download.side_effect = Exception("Persistent error")

        await attempt_upload_attachment(db, attachment.id)

        db.refresh(attachment)
        assert attachment.upload_status == "FAILED"
        assert attachment.upload_attempts == 5
        assert attachment.failed_at is not None
        assert attachment.last_error is not None


@pytest.mark.asyncio
async def test_upload_skips_already_uploaded(db, lead):
    """Test that already uploaded attachments are skipped."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_uploaded",
        upload_status="UPLOADED",
        upload_attempts=1,
        uploaded_at=datetime.now(UTC),
        bucket="reference-images",
        object_key="leads/1/1",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download:
        await attempt_upload_attachment(db, attachment.id)

        # Verify download was not called
        mock_download.assert_not_called()

        # Status should remain UPLOADED
        db.refresh(attachment)
        assert attachment.upload_status == "UPLOADED"


@pytest.mark.asyncio
async def test_upload_handles_whatsapp_download_failure(db, lead):
    """Test handling of WhatsApp media download failures."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_download_fail",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with (
        patch("app.services.media_upload._download_whatsapp_media") as mock_download,
        patch("app.services.system_event_service.error") as mock_error,
    ):
        # Simulate WhatsApp API failure
        mock_download.side_effect = Exception("WhatsApp API: Media expired or not found")

        await attempt_upload_attachment(db, attachment.id)

        db.refresh(attachment)
        assert attachment.upload_status == "PENDING"
        assert attachment.upload_attempts == 1
        assert "WhatsApp API" in attachment.last_error
        mock_error.assert_called_once()


@pytest.mark.asyncio
async def test_upload_handles_supabase_upload_failure(db, lead):
    """Test handling of Supabase upload failures."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_supabase_fail",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with (
        patch("app.services.media_upload._download_whatsapp_media") as mock_download,
        patch("app.services.media_upload._upload_to_supabase") as mock_upload,
        patch("app.services.system_event_service.error") as mock_error,
    ):
        mock_download.return_value = (b"fake_data", "image/jpeg")
        mock_upload.side_effect = Exception("Supabase: Bucket not found")

        await attempt_upload_attachment(db, attachment.id)

        db.refresh(attachment)
        assert attachment.upload_status == "PENDING"
        assert attachment.upload_attempts == 1
        assert "Supabase" in attachment.last_error


@pytest.mark.asyncio
async def test_upload_handles_missing_supabase_config(db, lead):
    """Test handling when Supabase is not configured."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_no_config",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    # Patch settings where media_upload reads it so _upload_to_supabase sees None
    with (
        patch("app.services.media_upload._download_whatsapp_media") as mock_download,
        patch("app.services.media_upload.settings") as mock_settings,
        patch("app.services.system_event_service.error") as mock_error,
    ):
        mock_download.return_value = (b"fake_data", "image/jpeg")
        mock_settings.supabase_url = None
        mock_settings.supabase_service_role_key = None

        await attempt_upload_attachment(db, attachment.id)

        db.refresh(attachment)
        assert attachment.upload_status == "PENDING"
        assert attachment.upload_attempts == 1
        # Either "Supabase not configured" (settings None) or "supabase package not installed" (ImportError in Docker)
        assert "Supabase" in attachment.last_error or "supabase" in attachment.last_error.lower()


def test_sweeper_finds_pending_attachments(db, lead):
    """Test that sweeper finds and processes pending attachments."""
    # Create pending attachment
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_sweep_1",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()

    # Patch where the job imports it so the job uses the mock
    with patch("app.jobs.sweep_pending_uploads.attempt_upload_attachment") as mock_upload:

        async def mock_upload_func(db_arg, att_id):
            att = db_arg.query(Attachment).filter(Attachment.id == att_id).first()
            if att:
                att.upload_status = "UPLOADED"
                att.uploaded_at = datetime.now(UTC)
                db_arg.commit()

        mock_upload.side_effect = mock_upload_func

        # Run sweep
        results = run_sweep(limit=10)

        # Verify results
        assert results["checked"] == 1
        assert results["processed"] == 1
        assert results["success"] == 1


def test_sweeper_respects_retry_delay(db, lead):
    """Test that sweeper respects retry delay between attempts."""
    # Create attachment with recent attempt
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_sweep_2",
        upload_status="PENDING",
        upload_attempts=1,
        last_attempt_at=datetime.now(UTC),  # Just attempted
        provider="supabase",
    )
    db.add(attachment)
    db.commit()

    with patch("app.services.media_upload.attempt_upload_attachment") as mock_upload:
        # Run sweep with 5 minute retry delay
        results = run_sweep(limit=10, retry_delay_minutes=5)

        # Verify attachment was not processed (too recent)
        assert results["checked"] == 0
        mock_upload.assert_not_called()


def test_sweeper_processes_stale_attempts(db, lead):
    """Test that sweeper processes attachments with stale attempts."""
    # Create attachment with old attempt (6 minutes ago)
    old_time = datetime.now(UTC) - timedelta(minutes=6)
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_sweep_3",
        upload_status="PENDING",
        upload_attempts=1,
        last_attempt_at=old_time,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()

    with patch("app.jobs.sweep_pending_uploads.attempt_upload_attachment") as mock_upload:

        async def _noop(_db, _att_id):
            pass

        mock_upload.side_effect = _noop

        # Run sweep with 5 minute retry delay
        results = run_sweep(limit=10, retry_delay_minutes=5)

        # Should process stale attempts
        assert results["checked"] == 1
        mock_upload.assert_called_once()


def test_sweeper_skips_failed_attachments(db, lead):
    """Test that sweeper skips attachments that failed 5 times."""
    # Create failed attachment
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_sweep_4",
        upload_status="PENDING",
        upload_attempts=5,  # Already failed 5 times
        provider="supabase",
    )
    db.add(attachment)
    db.commit()

    with patch("app.services.media_upload.attempt_upload_attachment") as mock_upload:
        # Run sweep
        results = run_sweep(limit=10)

        # Verify attachment was not processed
        assert results["checked"] == 0
        mock_upload.assert_not_called()


def test_sweeper_handles_mixed_statuses(db, lead):
    """Test sweeper handles multiple attachments with different statuses."""
    # Create various attachments
    pending = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_mixed_1",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    uploaded = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_mixed_2",
        upload_status="UPLOADED",
        upload_attempts=1,
        uploaded_at=datetime.now(UTC),
        provider="supabase",
    )
    failed = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_mixed_3",
        upload_status="FAILED",
        upload_attempts=5,
        failed_at=datetime.now(UTC),
        provider="supabase",
    )
    db.add_all([pending, uploaded, failed])
    db.commit()

    with patch("app.jobs.sweep_pending_uploads.attempt_upload_attachment") as mock_upload:

        async def mock_upload_func(db_arg, att_id):
            att = db_arg.query(Attachment).filter(Attachment.id == att_id).first()
            if att and att.upload_status == "PENDING":
                att.upload_status = "UPLOADED"
                att.uploaded_at = datetime.now(UTC)
                db_arg.commit()

        mock_upload.side_effect = mock_upload_func

        results = run_sweep(limit=10)

        # Should only process pending
        assert results["checked"] == 1
        assert results["success"] == 1


def test_attachment_created_without_lead_answer(db, lead):
    """Test that attachment can be created without lead_answer_id."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_no_answer",
        upload_status="PENDING",
        upload_attempts=0,
        lead_answer_id=None,  # No answer associated
        provider="supabase",
    )
    db.add(attachment)
    db.commit()

    assert attachment.lead_answer_id is None
    assert attachment.lead_id == lead.id


def test_attachment_object_key_format(db, lead):
    """Test that object_key follows expected format after upload."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_format",
        upload_status="UPLOADED",
        bucket="reference-images",
        object_key=f"leads/{lead.id}/123",
        provider="supabase",
    )
    db.add(attachment)
    db.commit()

    assert attachment.object_key.startswith("leads/")
    assert str(lead.id) in attachment.object_key
    assert attachment.bucket == "reference-images"


@pytest.mark.asyncio
async def test_upload_handles_network_timeout(db, lead):
    """Test handling of network timeouts during download."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_timeout",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with (
        patch("app.services.media_upload._download_whatsapp_media") as mock_download,
        patch("app.services.system_event_service.error") as mock_error,
    ):
        mock_download.side_effect = TimeoutError("Request timeout")

        await attempt_upload_attachment(db, attachment.id)

        db.refresh(attachment)
        assert attachment.upload_status == "PENDING"
        assert attachment.upload_attempts == 1
        assert "timeout" in attachment.last_error.lower() or "Timeout" in attachment.last_error


@pytest.mark.asyncio
async def test_upload_handles_invalid_media_response(db, lead):
    """Test handling of invalid WhatsApp media API response."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_invalid",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with (
        patch("app.services.media_upload._download_whatsapp_media") as mock_download,
        patch("app.services.system_event_service.error") as mock_error,
    ):
        # Simulate invalid response (no URL in media info)
        mock_download.side_effect = ValueError("No URL in WhatsApp media response")

        await attempt_upload_attachment(db, attachment.id)

        db.refresh(attachment)
        assert attachment.upload_status == "PENDING"
        assert attachment.upload_attempts == 1
        assert "No URL" in attachment.last_error


def test_sweeper_limit_respected(db, lead):
    """Test that sweeper respects the limit parameter."""
    # Create 15 pending attachments
    attachments = [
        Attachment(
            lead_id=lead.id,
            whatsapp_media_id=f"media_limit_{i}",
            upload_status="PENDING",
            upload_attempts=0,
            provider="supabase",
        )
        for i in range(15)
    ]
    db.add_all(attachments)
    db.commit()

    # Patch where the job imports it so the job uses the mock
    with patch("app.jobs.sweep_pending_uploads.attempt_upload_attachment") as mock_upload:

        async def _noop(_db, _att_id):
            pass

        mock_upload.side_effect = _noop

        results = run_sweep(limit=10)

        # Should only process 10 (the limit)
        assert results["checked"] == 10
        assert mock_upload.call_count == 10


def test_attachment_created_for_video_message(client, db, lead, monkeypatch):
    """Test that video messages are handled (though we only create attachments for image/document)."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1234567890",
                                    "id": "wamid.130",
                                    "type": "video",
                                    "video": {"id": "media_video"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    with patch("app.api.webhooks.verify_whatsapp_signature", return_value=True):
        response = client.post(
            "/webhooks/whatsapp",
            json=payload,
            headers={"X-Hub-Signature-256": "sha256=test"},
        )

        assert response.status_code == 200

        # Video messages should NOT create attachments (only image/document)
        attachment = (
            db.query(Attachment).filter(Attachment.whatsapp_media_id == "media_video").first()
        )
        assert attachment is None


def test_attachment_created_for_audio_message(client, db, lead, monkeypatch):
    """Test that audio messages don't create attachments."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1234567890",
                                    "id": "wamid.131",
                                    "type": "audio",
                                    "audio": {"id": "media_audio"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    with patch("app.api.webhooks.verify_whatsapp_signature", return_value=True):
        response = client.post(
            "/webhooks/whatsapp",
            json=payload,
            headers={"X-Hub-Signature-256": "sha256=test"},
        )

        assert response.status_code == 200

        # Audio messages should NOT create attachments
        attachment = (
            db.query(Attachment).filter(Attachment.whatsapp_media_id == "media_audio").first()
        )
        assert attachment is None
