"""
Tests for media upload functionality.
"""

import pytest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.db.models import Attachment, Lead
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
def pending_attachment(db, lead):
    """Create a pending attachment."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_123",
        upload_status="PENDING",
        upload_attempts=0,
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return attachment


@pytest.mark.asyncio
async def test_attempt_upload_success(db, pending_attachment):
    """Test successful upload flow."""
    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.media_upload._upload_to_supabase"
    ) as mock_upload:
        # Mock successful download
        mock_download.return_value = (b"fake_image_data", "image/jpeg")

        # Mock successful upload
        mock_upload.return_value = None

        # Run upload
        await attempt_upload_attachment(db, pending_attachment.id)

        # Verify attachment was updated
        db.refresh(pending_attachment)
        assert pending_attachment.upload_status == "UPLOADED"
        assert pending_attachment.uploaded_at is not None
        assert pending_attachment.upload_attempts == 1
        assert pending_attachment.bucket == "reference-images"
        assert pending_attachment.object_key == f"leads/{pending_attachment.lead_id}/{pending_attachment.id}"
        assert pending_attachment.content_type == "image/jpeg"
        assert pending_attachment.size_bytes == len(b"fake_image_data")
        assert pending_attachment.last_error is None

        # Verify functions were called
        mock_download.assert_called_once_with("media_123")
        mock_upload.assert_called_once()


@pytest.mark.asyncio
async def test_attempt_upload_failure_retry(db, pending_attachment):
    """Test upload failure with retry capability."""
    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.system_event_service.error"
    ) as mock_error:
        # Mock download failure
        mock_download.side_effect = Exception("WhatsApp API error")

        # Run upload (will fail)
        await attempt_upload_attachment(db, pending_attachment.id)

        # Verify attachment was updated with error
        db.refresh(pending_attachment)
        assert pending_attachment.upload_status == "PENDING"  # Still pending, not failed yet
        assert pending_attachment.upload_attempts == 1
        assert pending_attachment.last_attempt_at is not None
        assert pending_attachment.last_error is not None
        assert "WhatsApp API error" in pending_attachment.last_error

        # Verify system event was logged
        mock_error.assert_called_once()


@pytest.mark.asyncio
async def test_attempt_upload_fails_after_5_attempts(db, lead):
    """Test that attachment is marked as FAILED after 5 attempts."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_123",
        upload_status="PENDING",
        upload_attempts=4,  # Already tried 4 times
        provider="supabase",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    with patch("app.services.media_upload._download_whatsapp_media") as mock_download, patch(
        "app.services.system_event_service.error"
    ) as mock_error:
        # Mock download failure
        mock_download.side_effect = Exception("Persistent error")

        # Run upload (5th attempt, should mark as FAILED)
        await attempt_upload_attachment(db, attachment.id)

        # Verify attachment was marked as FAILED
        db.refresh(attachment)
        assert attachment.upload_status == "FAILED"
        assert attachment.upload_attempts == 5
        assert attachment.failed_at is not None
        assert attachment.last_error is not None


@pytest.mark.asyncio
async def test_attempt_upload_skips_already_uploaded(db, lead):
    """Test that already uploaded attachments are skipped."""
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_123",
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
        # Run upload
        await attempt_upload_attachment(db, attachment.id)

        # Verify download was not called
        mock_download.assert_not_called()


def test_sweep_pending_uploads_creates_pending(db, lead):
    """Test that sweeper finds and processes pending uploads."""
    from app.jobs.sweep_pending_uploads import run_sweep

    # Create pending attachment
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_123",
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


def test_sweep_pending_uploads_respects_retry_delay(db, lead):
    """Test that sweeper respects retry delay."""
    from app.jobs.sweep_pending_uploads import run_sweep

    # Create attachment with recent attempt
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_123",
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


def test_sweep_pending_uploads_skips_failed(db, lead):
    """Test that sweeper skips attachments that failed 5 times."""
    from app.jobs.sweep_pending_uploads import run_sweep

    # Create failed attachment
    attachment = Attachment(
        lead_id=lead.id,
        whatsapp_media_id="media_123",
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


@pytest.mark.asyncio
async def test_download_whatsapp_media_success():
    """Test successful WhatsApp media download."""
    from app.services.media_upload import _download_whatsapp_media

    # media_upload imports create_httpx_client from http_client inside _download_whatsapp_media
    with patch("app.services.http_client.create_httpx_client") as mock_client:
        # Mock HTTP client
        mock_response_1 = MagicMock()
        mock_response_1.json.return_value = {"url": "https://example.com/media.jpg"}
        mock_response_1.raise_for_status = MagicMock()

        mock_response_2 = MagicMock()
        mock_response_2.content = b"fake_image_data"
        mock_response_2.headers = {"content-type": "image/jpeg"}
        mock_response_2.raise_for_status = MagicMock()

        async def mock_get(url, headers=None):
            if "media_id" in url:
                return mock_response_1
            return mock_response_2

        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value.get = mock_get
        mock_client.return_value = mock_client_instance

        # Run download
        media_bytes, content_type = await _download_whatsapp_media("media_123")

        # Verify results
        assert media_bytes == b"fake_image_data"
        assert content_type == "image/jpeg"


@pytest.mark.asyncio
async def test_upload_to_supabase_success():
    """Test successful Supabase upload."""
    pytest.importorskip("supabase")
    from app.services.media_upload import _upload_to_supabase
    from app.core.config import settings

    # Mock settings; patch supabase.create_client (used inside _upload_to_supabase)
    with patch.object(settings, "supabase_url", "https://test.supabase.co"), patch.object(
        settings, "supabase_service_role_key", "test_key"
    ), patch("supabase.create_client") as mock_create_client:
        # Mock Supabase client
        mock_storage = MagicMock()
        mock_storage.from_.return_value.upload = MagicMock()

        mock_client = MagicMock()
        mock_client.storage = mock_storage
        mock_create_client.return_value = mock_client

        # Run upload
        await _upload_to_supabase("test-bucket", "test/key", b"fake_data", "image/jpeg")

        # Verify upload was called
        mock_storage.from_.assert_called_once_with("test-bucket")
        mock_storage.from_.return_value.upload.assert_called_once()


@pytest.mark.asyncio
async def test_upload_to_supabase_not_configured():
    """Test that upload fails if Supabase is not configured."""
    from app.services.media_upload import _upload_to_supabase
    from app.core.config import settings

    # Mock settings without Supabase config
    with patch.object(settings, "supabase_url", None), patch.object(
        settings, "supabase_service_role_key", None
    ):
        # Run upload (should raise ValueError)
        with pytest.raises(ValueError, match="Supabase not configured"):
            await _upload_to_supabase("test-bucket", "test/key", b"fake_data", "image/jpeg")
