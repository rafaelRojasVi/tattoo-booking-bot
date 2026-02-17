"""
Media upload service for handling WhatsApp media downloads and Supabase Storage uploads.

This service handles:
- Downloading media from WhatsApp API
- Uploading to Supabase Storage
- Updating Attachment records with status
"""

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.constants.event_types import EVENT_MEDIA_UPLOAD_FAILURE
from app.core.config import settings
from app.db.models import Attachment

logger = logging.getLogger(__name__)


async def attempt_upload_attachment(db: Session, attachment_id: int) -> None:
    """
    Attempt to upload a single attachment.

    This is the core function that performs the upload. It requires a database session
    to be passed in. For background jobs, use `attempt_upload_attachment_job()` instead.

    Args:
        db: Database session
        attachment_id: ID of the Attachment record to process
    """
    attachment = db.get(Attachment, attachment_id)
    if not attachment:
        logger.warning(f"Attachment {attachment_id} not found")
        return

    if attachment.upload_status == "UPLOADED":
        logger.info(f"Attachment {attachment_id} already uploaded, skipping")
        return

    if attachment.upload_status == "FAILED" and attachment.upload_attempts >= 5:
        logger.info(f"Attachment {attachment_id} failed after 5 attempts, skipping")
        return

    # Increment attempts and update timestamp
    attachment.upload_attempts += 1
    attachment.last_attempt_at = datetime.now(UTC)
    db.commit()
    db.refresh(attachment)

    try:
        # Download media from WhatsApp
        media_bytes, content_type = await _download_whatsapp_media(attachment.whatsapp_media_id)

        # Upload to Supabase Storage
        bucket = settings.supabase_storage_bucket or "reference-images"
        object_key = f"leads/{attachment.lead_id}/{attachment.id}"

        await _upload_to_supabase(bucket, object_key, media_bytes, content_type)

        # Mark as uploaded
        attachment.upload_status = "UPLOADED"
        attachment.uploaded_at = datetime.now(UTC)
        attachment.bucket = bucket
        attachment.object_key = object_key
        attachment.content_type = content_type
        attachment.size_bytes = len(media_bytes)
        attachment.last_error = None
        db.commit()
        db.refresh(attachment)

        logger.info(f"Successfully uploaded attachment {attachment_id} to {bucket}/{object_key}")

    except Exception as e:
        logger.error(f"Failed to upload attachment {attachment_id}: {e}", exc_info=True)
        db.rollback()

        # Refresh attachment to get latest state
        db.refresh(attachment)
        attachment.last_error = str(e)[:500]  # Truncate error message

        if attachment.upload_attempts >= 5:
            attachment.upload_status = "FAILED"
            attachment.failed_at = datetime.now(UTC)

        db.commit()

        # Log system event
        from app.services.system_event_service import error

        error(
            db=db,
            event_type=EVENT_MEDIA_UPLOAD_FAILURE,
            lead_id=attachment.lead_id,
            payload={
                "attachment_id": attachment_id,
                "attempts": attachment.upload_attempts,
                "error": str(e)[:200],
            },
        )


async def attempt_upload_attachment_job(attachment_id: int) -> None:
    """
    Background job wrapper for attempt_upload_attachment.

    This function creates its own database session and is suitable for use in
    background tasks, Celery workers, cron jobs, etc.

    Args:
        attachment_id: ID of the Attachment record to process
    """
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        await attempt_upload_attachment(db, attachment_id)
    finally:
        db.close()


async def _download_whatsapp_media(media_id: str) -> tuple[bytes, str]:
    """
    Download media from WhatsApp API.

    Args:
        media_id: WhatsApp media ID

    Returns:
        Tuple of (media_bytes, content_type)
    """
    from app.services.http_client import create_httpx_client

    # Get media URL from WhatsApp
    url = f"https://graph.facebook.com/v18.0/{media_id}"
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
    }

    async with create_httpx_client() as client:
        # First, get media URL
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        media_info = response.json()

        # Download actual media
        media_url = media_info.get("url")
        if not media_url:
            raise ValueError(f"No URL in WhatsApp media response: {media_info}")

        media_response = await client.get(media_url, headers=headers)
        media_response.raise_for_status()

        content_type = media_response.headers.get("content-type", "application/octet-stream")
        return media_response.content, content_type


async def _upload_to_supabase(bucket: str, object_key: str, media_bytes: bytes, content_type: str) -> None:
    """
    Upload media to Supabase Storage.

    Args:
        bucket: Supabase storage bucket name
        object_key: Object key (path) in bucket
        media_bytes: Media file bytes
        content_type: MIME type of the media
    """
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise ValueError(
            "Supabase not configured: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY required"
        )

    try:
        from supabase import create_client, Client

        supabase: Client = create_client(settings.supabase_url, settings.supabase_service_role_key)

        # Upload file
        supabase.storage.from_(bucket).upload(
            path=object_key,
            file=media_bytes,
            file_options={"content-type": content_type, "upsert": "true"},
        )

        logger.info(f"Uploaded {len(media_bytes)} bytes to {bucket}/{object_key}")

    except ImportError:
        raise ValueError(
            "supabase package not installed. Install with: pip install supabase"
        )
    except Exception as e:
        logger.error(f"Supabase upload failed: {e}", exc_info=True)
        raise
