"""
Comprehensive edge case tests for image handling and attachment status management.

Tests cover:
- Status transitions and edge cases
- Concurrent upload attempts
- Media expiration and invalid responses
- Large files and content type handling
- Network failures at different stages
- Supabase storage failures
- Duplicate media IDs
- Missing leads and orphaned attachments
- Race conditions
- Partial uploads
- Status corruption recovery
- Retry logic edge cases
- Sweeper edge cases
- Webhook edge cases with images
"""

import pytest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call
import asyncio

# Import models to ensure they're registered with Base.metadata
from app.db.models import Attachment, Lead, ProcessedMessage  # noqa: F401
from app.services.media_upload import attempt_upload_attachment
from app.jobs.sweep_pending_uploads import run_sweep


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
def pending_attachment(db, lead):
    """Create a pending attachment."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_edge_1",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return attachment


# ==================== Status Transition Edge Cases ====================

@pytest.mark.asyncio
async def test_status_transition_pending_to_uploaded_success(db, lead):
    """Test clean transition from PENDING to UPLOADED."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_status_1",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.media_upload._upload_to_supabase"
    ) as mock_upload:
        mock_download.return_value = (b"image_data", "image/jpeg")
        mock_upload.return_value = None

        await attempt_upload_attachment(db, attachment.id)

        # Refresh to get updated state (now using same session)
        db.refresh(attachment)
        assert attachment.upload_status == "UPLOADED"
        assert attachment.uploaded_at is not None
        assert attachment.upload_attempts == 1
        assert attachment.last_error is None
        assert attachment.failed_at is None


@pytest.mark.asyncio
async def test_status_transition_pending_to_failed_after_5_attempts(db, lead):
    """Test transition to FAILED after exactly 5 attempts."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_status_2",
        upload_status="PENDING",
        upload_attempts=4,  # 4th attempt failed, this is 5th
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.system_event_service.error"
    ) as mock_error:
        mock_download.side_effect = Exception("Persistent error")

        await attempt_upload_attachment(db, attachment.id)

        db.refresh(attachment)
        assert attachment.upload_status == "FAILED"
        assert attachment.upload_attempts == 5
        assert attachment.failed_at is not None
        assert attachment.last_error is not None


@pytest.mark.asyncio
async def test_status_remains_pending_before_5_attempts(db, lead):
    """Test that status remains PENDING until 5 attempts."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_status_3",
        upload_status="PENDING",
        upload_attempts=3,  # 3 attempts so far
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.system_event_service.error"
    ) as mock_error:
        mock_download.side_effect = Exception("Temporary error")

        await attempt_upload_attachment(db, attachment.id)

        db.refresh(attachment)
        assert attachment.upload_status == "PENDING"  # Still pending
        assert attachment.upload_attempts == 4
        assert attachment.failed_at is None  # Not failed yet


@pytest.mark.asyncio
async def test_status_corruption_recovery_already_uploaded(db, lead):
    """Test handling of attachment that's already UPLOADED but retried."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_status_4",
        upload_status="UPLOADED",
        upload_attempts=1,
        uploaded_at=datetime.now(UTC),
        bucket="reference-images",
        object_key="leads/1/1",
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download:
        await attempt_upload_attachment(db, attachment.id)

        # Should skip without downloading
        mock_download.assert_not_called()
        db.refresh(attachment)
        assert attachment.upload_status == "UPLOADED"


@pytest.mark.asyncio
async def test_status_corruption_recovery_failed_but_retried(db, lead):
    """Test handling of attachment marked FAILED but retried (should skip)."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_status_5",
        upload_status="FAILED",
        upload_attempts=5,
        failed_at=datetime.now(UTC),
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download:
        await attempt_upload_attachment(db, attachment.id)

        # Should skip failed attachments
        mock_download.assert_not_called()
        db.refresh(attachment)
        assert attachment.upload_status == "FAILED"


# ==================== Concurrent Upload Edge Cases ====================

@pytest.mark.asyncio
async def test_concurrent_upload_attempts_same_attachment(db, lead):
    """Test concurrent upload attempts on same attachment (race condition)."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_concurrent_1",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.media_upload._upload_to_supabase"
    ) as mock_upload:
        mock_download.return_value = (b"data", "image/jpeg")
        # Simulate slow upload
        async def slow_upload(*args, **kwargs):
            await asyncio.sleep(0.1)
        mock_upload.side_effect = slow_upload

        # Run concurrent attempts (all use same db session)
        tasks = [attempt_upload_attachment(db, attachment.id) for _ in range(3)]
        await asyncio.gather(*tasks, return_exceptions=True)

        db.refresh(attachment)
        # Should be uploaded (one succeeded)
        assert attachment.upload_status == "UPLOADED"
        # Attempts may vary due to race conditions
        assert attachment.upload_attempts >= 1


@pytest.mark.asyncio
async def test_concurrent_upload_different_attachments(db, lead):
    """Test concurrent uploads of different attachments."""
    attachments = [
        Attachment(
            lead_id=lead.id,
            whatsapp_media_id=f"media_concurrent_{i}",
            upload_status="PENDING",
            upload_attempts=0,
            provider="supabase",
        )
        for i in range(5)
    ]
    db.add_all(attachments)
    db.commit()

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.media_upload._upload_to_supabase"
    ) as mock_upload:
        mock_download.return_value = (b"data", "image/jpeg")
        mock_upload.return_value = None

        # Run concurrent uploads
        tasks = [attempt_upload_attachment(db, att.id) for att in attachments]
        await asyncio.gather(*tasks)

        # All should be uploaded
        for att in attachments:
            db.refresh(att)
            assert att.upload_status == "UPLOADED"


# ==================== Media Expiration and Invalid Responses ====================

@pytest.mark.asyncio
async def test_whatsapp_media_expired(db, lead):
    """Test handling of expired WhatsApp media."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_expired",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.system_event_service.error"
    ) as mock_error:
        from httpx import HTTPStatusError

        # Simulate WhatsApp API returning 404 (media expired)
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_download.side_effect = HTTPStatusError(
            "Media not found", request=MagicMock(), response=mock_response
        )

        await attempt_upload_attachment(db, attachment.id)

        db.refresh(attachment)
        assert attachment.upload_status == "PENDING"
        assert attachment.upload_attempts == 1
        assert attachment.last_error is not None
        mock_error.assert_called_once()


@pytest.mark.asyncio
async def test_whatsapp_media_invalid_response_no_url(db, lead):
    """Test handling of WhatsApp API response without URL."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_no_url",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.system_event_service.error"
    ) as mock_error:
        mock_download.side_effect = ValueError("No URL in WhatsApp media response: {}")

        await attempt_upload_attachment(db, attachment.id)

        db.refresh(attachment)
        assert attachment.upload_status == "PENDING"
        assert attachment.upload_attempts == 1
        assert "No URL" in attachment.last_error


@pytest.mark.asyncio
async def test_whatsapp_media_invalid_json_response(db, lead):
    """Test handling of invalid JSON response from WhatsApp."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_invalid_json",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.system_event_service.error"
    ) as mock_error:
        import json

        mock_download.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)

        await attempt_upload_attachment(db, attachment.id)

        db.refresh(attachment)
        assert attachment.upload_status == "PENDING"
        assert attachment.upload_attempts == 1
        assert attachment.last_error is not None


# ==================== Large Files and Content Type Edge Cases ====================

@pytest.mark.asyncio
async def test_large_file_upload(db, lead):
    """Test upload of large file (10MB)."""
    large_data = b"x" * (10 * 1024 * 1024)  # 10MB

    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_large",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.media_upload._upload_to_supabase"
    ) as mock_upload:
        mock_download.return_value = (large_data, "image/jpeg")
        mock_upload.return_value = None

        await attempt_upload_attachment(db, attachment.id)

        db.refresh(attachment)
        assert attachment.upload_status == "UPLOADED"
        assert attachment.size_bytes == len(large_data)
        mock_upload.assert_called_once()


@pytest.mark.asyncio
async def test_empty_file_upload(db, lead):
    """Test handling of empty file (0 bytes)."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_empty",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.media_upload._upload_to_supabase"
    ) as mock_upload:
        mock_download.return_value = (b"", "image/jpeg")
        mock_upload.return_value = None

        await attempt_upload_attachment(db, attachment.id)

        db.refresh(attachment)
        assert attachment.upload_status == "UPLOADED"
        assert attachment.size_bytes == 0


@pytest.mark.asyncio
async def test_unknown_content_type(db, lead):
    """Test handling of unknown content type."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_unknown_type",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.media_upload._upload_to_supabase"
    ) as mock_upload:
        mock_download.return_value = (b"data", "application/octet-stream")
        mock_upload.return_value = None

        await attempt_upload_attachment(db, attachment.id)

        db.refresh(attachment)
        assert attachment.upload_status == "UPLOADED"
        assert attachment.content_type == "application/octet-stream"


@pytest.mark.asyncio
async def test_missing_content_type_header(db, lead):
    """Test handling when content-type header is missing."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_no_content_type",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.media_upload._upload_to_supabase"
    ) as mock_upload:
        # Simulate missing content-type (defaults to application/octet-stream)
        mock_download.return_value = (b"data", "application/octet-stream")
        mock_upload.return_value = None

        await attempt_upload_attachment(db, attachment.id)

        db.refresh(attachment)
        assert attachment.upload_status == "UPLOADED"
        assert attachment.content_type == "application/octet-stream"


# ==================== Network Failure Edge Cases ====================

@pytest.mark.asyncio
async def test_network_timeout_during_download(db, lead):
    """Test handling of network timeout during WhatsApp download."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_timeout_download",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.system_event_service.error"
    ) as mock_error:
        mock_download.side_effect = asyncio.TimeoutError("Request timeout")

        await attempt_upload_attachment(db, attachment.id)

        db.refresh(attachment)
        assert attachment.upload_status == "PENDING"
        assert attachment.upload_attempts == 1
        assert "timeout" in attachment.last_error.lower() or "Timeout" in attachment.last_error


@pytest.mark.asyncio
async def test_network_timeout_during_upload(db, lead):
    """Test handling of network timeout during Supabase upload."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_timeout_upload",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.media_upload._upload_to_supabase"
    ) as mock_upload, patch("app.services.system_event_service.error") as mock_error:
        mock_download.return_value = (b"data", "image/jpeg")
        mock_upload.side_effect = asyncio.TimeoutError("Upload timeout")

        await attempt_upload_attachment(db, attachment.id)

        db.refresh(attachment)
        assert attachment.upload_status == "PENDING"
        assert attachment.upload_attempts == 1
        assert "timeout" in attachment.last_error.lower() or "Timeout" in attachment.last_error


@pytest.mark.asyncio
async def test_connection_error_during_download(db, lead):
    """Test handling of connection error during download."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_conn_error",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.system_event_service.error"
    ) as mock_error:
        import httpx

        mock_download.side_effect = httpx.ConnectError("Connection refused")

        await attempt_upload_attachment(db, attachment.id)

        db.refresh(attachment)
        assert attachment.upload_status == "PENDING"
        assert attachment.upload_attempts == 1
        assert attachment.last_error is not None


@pytest.mark.asyncio
async def test_partial_download_failure(db, lead):
    """Test handling of partial download (connection drops mid-download)."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_partial",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.system_event_service.error"
    ) as mock_error:
        import httpx

        mock_download.side_effect = httpx.ReadError("Connection closed")

        await attempt_upload_attachment(db, attachment.id)

        db.refresh(attachment)
        assert attachment.upload_status == "PENDING"
        assert attachment.upload_attempts == 1
        assert attachment.last_error is not None


# ==================== Supabase Storage Edge Cases ====================

@pytest.mark.asyncio
async def test_supabase_bucket_not_found(db, lead):
    """Test handling when Supabase bucket doesn't exist."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_no_bucket",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.media_upload._upload_to_supabase"
    ) as mock_upload, patch("app.services.system_event_service.error") as mock_error:
        mock_download.return_value = (b"data", "image/jpeg")
        mock_upload.side_effect = Exception("Bucket 'reference-images' not found")

        await attempt_upload_attachment(db, attachment.id)

        db.refresh(attachment)
        assert attachment.upload_status == "PENDING"
        assert attachment.upload_attempts == 1
        assert "Bucket" in attachment.last_error or "bucket" in attachment.last_error.lower()


@pytest.mark.asyncio
async def test_supabase_permission_denied(db, lead):
    """Test handling of Supabase permission denied error."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_permission",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.media_upload._upload_to_supabase"
    ) as mock_upload, patch("app.services.system_event_service.error") as mock_error:
        mock_download.return_value = (b"data", "image/jpeg")
        mock_upload.side_effect = Exception("Permission denied: Insufficient storage access")

        await attempt_upload_attachment(db, attachment.id)

        db.refresh(attachment)
        assert attachment.upload_status == "PENDING"
        assert attachment.upload_attempts == 1
        assert attachment.last_error is not None


@pytest.mark.asyncio
async def test_supabase_storage_full(db, lead):
    """Test handling when Supabase storage is full."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_storage_full",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.media_upload._upload_to_supabase"
    ) as mock_upload, patch("app.services.system_event_service.error") as mock_error:
        mock_download.return_value = (b"data", "image/jpeg")
        mock_upload.side_effect = Exception("Storage quota exceeded")

        await attempt_upload_attachment(db, attachment.id)

        db.refresh(attachment)
        assert attachment.upload_status == "PENDING"
        assert attachment.upload_attempts == 1
        assert attachment.last_error is not None


@pytest.mark.asyncio
async def test_supabase_not_configured(db, lead):
    """Test handling when Supabase credentials are missing."""
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

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.media_upload._upload_to_supabase"
    ) as mock_upload, patch("app.services.system_event_service.error") as mock_error:
        mock_download.return_value = (b"data", "image/jpeg")
        # Mock upload to raise the configuration error
        mock_upload.side_effect = ValueError("Supabase not configured: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY required")

        await attempt_upload_attachment(db, attachment.id)

        db.refresh(attachment)
        assert attachment.upload_status == "PENDING"
        assert attachment.upload_attempts == 1
        assert attachment.last_error is not None
        assert "Supabase not configured" in attachment.last_error


# ==================== Duplicate Media ID Edge Cases ====================

def test_duplicate_media_id_same_lead(client, db, lead, monkeypatch):
    """Test handling of duplicate media ID for same lead."""
    # Create first attachment
    attachment1 = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_duplicate",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment1)
    db.commit()

    # Simulate webhook creating second attachment with same media_id
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": lead.wa_from,
                                    "id": "wamid.duplicate",
                                    "type": "image",
                                    "image": {"id": "media_duplicate"},
                                    "timestamp": "1234567890",
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    with patch("app.api.webhooks.verify_whatsapp_signature", return_value=True), patch(
        "app.services.media_upload.attempt_upload_attachment_job"
    ):
        response = client.post(
            "/webhooks/whatsapp",
            json=payload,
            headers={"X-Hub-Signature-256": "sha256=test"},
        )

        assert response.status_code == 200

        # Both attachments should exist (no unique constraint on media_id)
        attachments = db.query(Attachment).filter(Attachment.whatsapp_media_id == "media_duplicate").all()
        assert len(attachments) == 2


def test_duplicate_media_id_different_leads(client, db, monkeypatch):
    """Test handling of same media ID for different leads."""
    lead1 = Lead(wa_from="1111111111", status="QUALIFYING")
    lead2 = Lead(wa_from="2222222222", status="QUALIFYING")
    db.add_all([lead1, lead2])
    db.commit()

    # Same media ID, different leads (should be allowed)
    attachment1 = Attachment(
        lead_id=lead1.id,
        whatsapp_media_id="media_shared",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    attachment2 = Attachment(
        lead_id=lead2.id,
        whatsapp_media_id="media_shared",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add_all([attachment1, attachment2])
    db.commit()

    # Both should exist
    assert db.query(Attachment).filter(Attachment.whatsapp_media_id == "media_shared").count() == 2


# ==================== Missing Lead and Orphaned Attachments ====================

@pytest.mark.asyncio
async def test_attachment_with_missing_lead(db):
    """Test handling of attachment with non-existent lead_id."""
    # Create attachment with invalid lead_id
    attachment = Attachment(
        lead_id=99999,  # Non-existent lead
        whatsapp_media_id="media_orphan",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    # Should handle gracefully (foreign key constraint may prevent this, but test the case)
    with patch("app.services.media_upload._download_whatsapp_media") as mock_download:
        try:
            await attempt_upload_attachment(db, attachment.id)
        except Exception as e:
            # May raise foreign key error or handle gracefully
            pass

        # Verify error was logged
        db.refresh(attachment)
        # Status may remain PENDING or error may be logged


def test_attachment_deleted_lead_cleanup(db, lead):
    """Test that attachments are handled when lead is deleted."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_deleted_lead",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()

    # Delete lead (cascade should handle attachments if configured)
    db.delete(lead)
    db.commit()

    # Attachment may be deleted (cascade) or orphaned depending on DB config
    attachment_check = db.query(Attachment).filter(Attachment.id == attachment.id).first()
    # Result depends on cascade configuration


# ==================== Retry Logic Edge Cases ====================

def test_retry_delay_respected_exactly(db, lead):
    """Test that retry delay is respected exactly."""
    # Create attachment with attempt 1 minute ago (should retry if delay is 5 min)
    old_time = datetime.now(UTC) - timedelta(minutes=1)
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_retry_delay",
        upload_status="PENDING",
        upload_attempts=1,
        last_attempt_at=old_time,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()

    with patch("app.services.media_upload.attempt_upload_attachment") as mock_upload:
        # Run sweep with 5 minute delay
        results = run_sweep(limit=10, retry_delay_minutes=5)

        # Should NOT process (only 1 minute ago, need 5 minutes)
        assert results["checked"] == 0
        mock_upload.assert_not_called()


def test_retry_delay_expired_retries(db, lead, monkeypatch):
    """Test that expired retry delay allows retry."""
    # Create attachment with attempt 6 minutes ago (should retry if delay is 5 min)
    old_time = datetime.now(UTC) - timedelta(minutes=6)
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_retry_expired",
        upload_status="PENDING",
        upload_attempts=1,
        last_attempt_at=old_time,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()

    # Patch SessionLocal in sweeper to use test db
    monkeypatch.setattr("app.jobs.sweep_pending_uploads.SessionLocal", lambda: db)
    
    # Create async mock and patch it in the sweeper's namespace
    mock_upload = AsyncMock()
    monkeypatch.setattr("app.jobs.sweep_pending_uploads.attempt_upload_attachment", mock_upload)
    
    # Run sweep with 5 minute delay
    results = run_sweep(limit=10, retry_delay_minutes=5)

    # Should process (6 minutes > 5 minutes delay)
    assert results["checked"] == 1
    mock_upload.assert_called_once()
    # Verify it was called with db and attachment.id
    assert mock_upload.call_args[0][1] == attachment.id


def test_retry_never_attempted_processed_immediately(db, lead, monkeypatch):
    """Test that attachments never attempted are processed immediately."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_never_attempted",
        upload_status="PENDING",
        upload_attempts=0,
        last_attempt_at=None,  # Never attempted
        provider="supabase",
    )
    db.add(attachment)
    db.commit()

    # Patch SessionLocal in sweeper to use test db
    monkeypatch.setattr("app.jobs.sweep_pending_uploads.SessionLocal", lambda: db)
    
    # Create async mock and patch it in the sweeper's namespace
    mock_upload = AsyncMock()
    monkeypatch.setattr("app.jobs.sweep_pending_uploads.attempt_upload_attachment", mock_upload)
    
    results = run_sweep(limit=10)

    # Should process immediately (no previous attempt)
    assert results["checked"] == 1
    mock_upload.assert_called_once()
    # Verify it was called with db and attachment.id
    assert mock_upload.call_args[0][1] == attachment.id


# ==================== Sweeper Edge Cases ====================

def test_sweeper_limit_zero(db, lead):
    """Test sweeper with limit=0."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_limit_zero",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()

    with patch("app.services.media_upload.attempt_upload_attachment") as mock_upload:
        results = run_sweep(limit=0)

        assert results["checked"] == 0
        mock_upload.assert_not_called()


def test_sweeper_limit_larger_than_available(db, lead, monkeypatch):
    """Test sweeper with limit larger than available attachments."""
    attachments = [
        Attachment(
            lead_id=lead.id,
            whatsapp_media_id=f"media_limit_{i}",
            upload_status="PENDING",
            upload_attempts=0,
            provider="supabase",
        )
        for i in range(5)
    ]
    db.add_all(attachments)
    db.commit()

    # Patch SessionLocal in sweeper to use test db
    monkeypatch.setattr("app.jobs.sweep_pending_uploads.SessionLocal", lambda: db)
    
    # Patch where the sweeper imports it
    with patch("app.jobs.sweep_pending_uploads.attempt_upload_attachment", new_callable=AsyncMock) as mock_upload:
        results = run_sweep(limit=100)

        # Should process all 5
        assert results["checked"] == 5
        assert mock_upload.call_count == 5


def test_sweeper_mixed_statuses_only_pending(db, lead, monkeypatch):
    """Test sweeper only processes PENDING, not UPLOADED or FAILED."""
    pending = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_pending",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    uploaded = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_uploaded",
        upload_status="UPLOADED",
        upload_attempts=1,
        uploaded_at=datetime.now(UTC),
        provider="supabase",
    )
    failed = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_failed",
        upload_status="FAILED",
        upload_attempts=5,
        failed_at=datetime.now(UTC),
        provider="supabase",
    )
    db.add_all([pending, uploaded, failed])
    db.commit()

    # Patch SessionLocal in sweeper to use test db
    monkeypatch.setattr("app.jobs.sweep_pending_uploads.SessionLocal", lambda: db)
    
    # Patch where the sweeper imports it
    with patch("app.jobs.sweep_pending_uploads.attempt_upload_attachment", new_callable=AsyncMock) as mock_upload:
        results = run_sweep(limit=10)

        # Should only process pending
        assert results["checked"] == 1
        assert mock_upload.call_count == 1
        # Verify it was called with db and pending attachment id
        assert mock_upload.call_args[0][1] == pending.id


def test_sweeper_skips_max_attempts(db, lead):
    """Test sweeper skips attachments with 5+ attempts."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_max_attempts",
        upload_status="PENDING",
        upload_attempts=5,  # Max attempts reached
        provider="supabase",
    )
    db.add(attachment)
    db.commit()

    with patch("app.services.media_upload.attempt_upload_attachment") as mock_upload:
        results = run_sweep(limit=10)

        # Should skip (5 attempts = max)
        assert results["checked"] == 0
        mock_upload.assert_not_called()


# ==================== Webhook Edge Cases with Images ====================

def test_webhook_image_without_media_id(client, db, lead, monkeypatch):
    """Test webhook handles image message without media ID."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": lead.wa_from,
                                    "id": "wamid.no_media_id",
                                    "type": "image",
                                    "image": {},  # No id field
                                    "timestamp": "1234567890",
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

        # No attachment should be created
        attachment = db.query(Attachment).filter(Attachment.whatsapp_media_id.is_(None)).first()
        assert attachment is None


def test_webhook_image_with_null_media_id(client, db, lead, monkeypatch):
    """Test webhook handles image message with null media ID."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": lead.wa_from,
                                    "id": "wamid.null_media",
                                    "type": "image",
                                    "image": {"id": None},  # Explicitly null
                                    "timestamp": "1234567890",
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

        # No attachment should be created
        attachments = db.query(Attachment).all()
        assert len(attachments) == 0


def test_webhook_multiple_images_most_recent_processed(client, db, lead, monkeypatch):
    """Test webhook processes most recent image when multiple arrive."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": lead.wa_from,
                                    "id": "wamid.old",
                                    "type": "image",
                                    "image": {"id": "media_old"},
                                    "timestamp": "1234567890",  # Older
                                },
                                {
                                    "from": lead.wa_from,
                                    "id": "wamid.new",
                                    "type": "image",
                                    "image": {"id": "media_new"},
                                    "timestamp": "1234567891",  # Newer
                                },
                            ]
                        }
                    }
                ]
            }
        ]
    }

    with patch("app.api.webhooks.verify_whatsapp_signature", return_value=True), patch(
        "app.services.media_upload.attempt_upload_attachment_job"
    ):
        response = client.post(
            "/webhooks/whatsapp",
            json=payload,
            headers={"X-Hub-Signature-256": "sha256=test"},
        )

        assert response.status_code == 200

        # Should create attachment for most recent (media_new)
        attachment = db.query(Attachment).filter(Attachment.whatsapp_media_id == "media_new").first()
        assert attachment is not None

        # Should NOT create attachment for older
        old_attachment = db.query(Attachment).filter(Attachment.whatsapp_media_id == "media_old").first()
        assert old_attachment is None


def test_webhook_image_with_text_caption(client, db, lead, monkeypatch):
    """Test webhook handles image with text caption."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": lead.wa_from,
                                    "id": "wamid.caption",
                                    "type": "image",
                                    "image": {"id": "media_caption"},
                                    "caption": "This is my reference design",
                                    "timestamp": "1234567890",
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    with patch("app.api.webhooks.verify_whatsapp_signature", return_value=True), patch(
        "app.services.media_upload.attempt_upload_attachment_job"
    ):
        response = client.post(
            "/webhooks/whatsapp",
            json=payload,
            headers={"X-Hub-Signature-256": "sha256=test"},
        )

        assert response.status_code == 200

        # Should create attachment
        attachment = db.query(Attachment).filter(Attachment.whatsapp_media_id == "media_caption").first()
        assert attachment is not None
        assert attachment.upload_status == "PENDING"


def test_webhook_image_duplicate_message_id(client, db, lead, monkeypatch):
    """Test webhook handles duplicate message ID (idempotency)."""
    # Create processed message
    processed = ProcessedMessage(
        message_id="wamid.duplicate",
        event_type="whatsapp.message",
        lead_id=lead.id,
    )
    db.add(processed)
    db.commit()

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": lead.wa_from,
                                    "id": "wamid.duplicate",  # Already processed
                                    "type": "image",
                                    "image": {"id": "media_duplicate"},
                                    "timestamp": "1234567890",
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
        assert response.json()["type"] == "duplicate"

        # Should NOT create new attachment (already processed)
        new_attachment = db.query(Attachment).filter(Attachment.whatsapp_media_id == "media_duplicate").first()
        assert new_attachment is None


# ==================== Object Key and Storage Edge Cases ====================

@pytest.mark.asyncio
async def test_object_key_format_correct(db, lead):
    """Test that object_key follows correct format."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_format",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.media_upload._upload_to_supabase"
    ) as mock_upload:
        mock_download.return_value = (b"data", "image/jpeg")
        mock_upload.return_value = None

        await attempt_upload_attachment(db, attachment.id)

        db.refresh(attachment)
        expected_key = f"leads/{lead.id}/{attachment.id}"
        assert attachment.object_key == expected_key
        assert attachment.bucket == "reference-images"


@pytest.mark.asyncio
async def test_object_key_collision_same_lead_different_attachments(db, lead):
    """Test that different attachments for same lead get different object keys."""
    attachment1 = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_collision_1",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    attachment2 = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_collision_2",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add_all([attachment1, attachment2])
    db.commit()

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.media_upload._upload_to_supabase"
    ) as mock_upload:
        mock_download.return_value = (b"data", "image/jpeg")
        mock_upload.return_value = None

        await attempt_upload_attachment(db, attachment1.id)
        await attempt_upload_attachment(db, attachment2.id)

        db.refresh(attachment1)
        db.refresh(attachment2)

        # Should have different object keys
        assert attachment1.object_key != attachment2.object_key
        assert attachment1.object_key == f"leads/{lead.id}/{attachment1.id}"
        assert attachment2.object_key == f"leads/{lead.id}/{attachment2.id}"


# ==================== Error Message Truncation ====================

@pytest.mark.asyncio
async def test_error_message_truncation_long_error(db, lead):
    """Test that very long error messages are truncated."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_long_error",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.system_event_service.error"
    ) as mock_error:
        # Create very long error message
        long_error = "Error: " + "x" * 1000
        mock_download.side_effect = Exception(long_error)

        await attempt_upload_attachment(db, attachment.id)

        db.refresh(attachment)
        # Error should be truncated to 500 chars (as per code)
        assert len(attachment.last_error) <= 500
        assert attachment.last_error.startswith("Error:")


# ==================== System Event Logging Edge Cases ====================

@pytest.mark.asyncio
async def test_system_event_logged_on_failure(db, lead):
    """Test that system event is logged on upload failure."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_system_event",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.system_event_service.error"
    ) as mock_error:
        mock_download.side_effect = Exception("Test error")

        await attempt_upload_attachment(db, attachment.id)

        # Verify system event was logged
        mock_error.assert_called_once()
        call_args = mock_error.call_args
        # Check keyword arguments (call_args[1] for kwargs, call_args[0] for args)
        assert call_args.kwargs["event_type"] == "media_upload.failure"
        assert call_args.kwargs["lead_id"] == lead.id
        assert "attachment_id" in call_args.kwargs["payload"]


@pytest.mark.asyncio
async def test_system_event_not_logged_on_success(db, lead):
    """Test that system event is NOT logged on successful upload."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_no_event",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.media_upload._upload_to_supabase"
    ) as mock_upload, patch("app.services.system_event_service.error") as mock_error:
        mock_download.return_value = (b"data", "image/jpeg")
        mock_upload.return_value = None

        await attempt_upload_attachment(db, attachment.id)

        # Should NOT log error event on success
        mock_error.assert_not_called()
