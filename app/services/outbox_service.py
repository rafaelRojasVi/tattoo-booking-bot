"""
Outbox-lite service for durable WhatsApp sends.

When OUTBOX_ENABLED=true:
- Persist send intent before attempting
- On success: mark SENT
- On failure: mark FAILED, set next_retry_at (exponential backoff), last_error

Retry via admin endpoint or scheduled job.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import OutboxMessage

logger = logging.getLogger(__name__)


def _exponential_backoff_minutes(attempts: int) -> int:
    """Minutes until next retry: 5, 15, 45, ..."""
    return cast(int, min(5 * (3**attempts), 1440))  # Cap at 24h


def write_outbox(
    db: Session,
    lead_id: int | None,
    to: str,
    message: str,
    template_name: str | None = None,
    template_params: dict | None = None,
) -> OutboxMessage | None:
    """
    Write outbox row before send (when OUTBOX_ENABLED).
    Returns OutboxMessage or None if disabled.
    """
    if not settings.outbox_enabled:
        return None
    payload = {"to": to, "message": message}
    if template_name:
        payload["template_name"] = template_name
        payload["template_params"] = template_params or {}
    outbox = OutboxMessage(
        lead_id=lead_id,
        channel="whatsapp",
        payload_json=payload,
        status="PENDING",
        attempts=0,
    )
    db.add(outbox)
    db.commit()
    db.refresh(outbox)
    return outbox


def mark_outbox_sent(db: Session, outbox: OutboxMessage) -> None:
    """Mark outbox as SENT."""
    outbox.status = "SENT"
    outbox.attempts += 1
    outbox.next_retry_at = None
    outbox.last_error = None
    db.commit()


def mark_outbox_failed(db: Session, outbox: OutboxMessage, exc: Exception) -> None:
    """Mark outbox as FAILED and schedule retry."""
    outbox.status = "FAILED"
    outbox.attempts += 1
    outbox.last_error = str(exc)[:500]
    outbox.next_retry_at = datetime.now(UTC) + timedelta(
        minutes=_exponential_backoff_minutes(outbox.attempts)
    )
    db.commit()


def retry_due_outbox_rows(db: Session, limit: int = 50) -> dict:
    """
    Retry PENDING/FAILED outbox rows where next_retry_at <= now or NULL.

    Returns:
        {retried: int, sent: int, failed: int}
    """
    if not settings.outbox_enabled:
        return {"retried": 0, "sent": 0, "failed": 0}

    now = datetime.now(UTC)
    stmt = (
        select(OutboxMessage)
        .where(OutboxMessage.status.in_(["PENDING", "FAILED"]))
        .where((OutboxMessage.next_retry_at.is_(None)) | (OutboxMessage.next_retry_at <= now))
        .order_by(OutboxMessage.created_at)
        .limit(limit)
    )
    rows = db.execute(stmt).scalars().all()
    results = {"retried": 0, "sent": 0, "failed": 0}

    for row in rows:
        results["retried"] += 1
        payload = row.payload_json
        to = payload.get("to")
        message = payload.get("message", "")
        template_name = payload.get("template_name")
        template_params = payload.get("template_params") or {}

        try:
            import asyncio

            from app.services.messaging import send_whatsapp_message
            from app.services.whatsapp_window import send_template_message

            loop = asyncio.get_event_loop()
            if template_name:
                loop.run_until_complete(
                    send_template_message(to, template_name, template_params, dry_run=False)
                )
            else:
                loop.run_until_complete(send_whatsapp_message(to, message, dry_run=False))
            mark_outbox_sent(db, row)
            results["sent"] += 1
        except Exception as e:
            mark_outbox_failed(db, row, e)
            results["failed"] += 1
            logger.warning(f"Outbox retry failed for id={row.id}: {e}")

    return results
