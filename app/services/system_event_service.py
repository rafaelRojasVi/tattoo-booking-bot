"""
System event logging service.

Provides structured logging of key system events and failures to the database.
All SystemEvent creation should go through log_event (or info/warn/error) to ensure
consistent payload shape and avoid drift.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.models import SystemEvent

logger = logging.getLogger(__name__)

# Default retention: delete events older than this many days
DEFAULT_RETENTION_DAYS = 90


def _resolve_correlation_id(correlation_id: str | None) -> str | None:
    """Use request-scoped contextvar when not explicitly passed."""
    if correlation_id is not None:
        return correlation_id
    try:
        from app.middleware.correlation_id import get_correlation_id

        return get_correlation_id(None)
    except Exception:
        return None


def log_event(
    db: Session,
    level: str,
    event_type: str,
    lead_id: int | None = None,
    payload: dict | None = None,
    exc: BaseException | None = None,
    correlation_id: str | None = None,
) -> SystemEvent:
    """
    Log a system event to the database.

    Args:
        db: Database session
        level: Event level (INFO, WARN, ERROR)
        event_type: Type of event (e.g., "whatsapp.send_failure", "template.fallback_used")
        lead_id: Optional lead ID associated with the event
        payload: Optional additional event data (dict). Will be normalized/copied.
        exc: Optional exception; if provided, error_type and error message are added to payload.
        correlation_id: Optional correlation ID for request tracing.

    Returns:
        Created SystemEvent object
    """
    normalized: dict = dict(payload) if payload else {}
    if exc is not None:
        normalized["error"] = {
            "type": type(exc).__name__,
            "message": str(exc)[:500],  # Truncate to avoid huge payloads
        }
    resolved_cid = _resolve_correlation_id(correlation_id)
    if resolved_cid is not None:
        normalized["correlation_id"] = resolved_cid

    event = SystemEvent(
        level=level.upper(),
        event_type=event_type,
        lead_id=lead_id,
        payload=normalized if normalized else None,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def info(
    db: Session,
    event_type: str,
    lead_id: int | None = None,
    payload: dict | None = None,
    exc: BaseException | None = None,
    correlation_id: str | None = None,
) -> SystemEvent:
    """
    Log an INFO-level system event.

    Args:
        db: Database session
        event_type: Type of event
        lead_id: Optional lead ID
        payload: Optional event data

    Returns:
        Created SystemEvent object
    """
    return log_event(
        db, level="INFO", event_type=event_type, lead_id=lead_id,
        payload=payload, exc=exc, correlation_id=correlation_id,
    )


def warn(
    db: Session,
    event_type: str,
    lead_id: int | None = None,
    payload: dict | None = None,
    exc: BaseException | None = None,
    correlation_id: str | None = None,
) -> SystemEvent:
    """
    Log a WARN-level system event.

    Args:
        db: Database session
        event_type: Type of event
        lead_id: Optional lead ID
        payload: Optional event data

    Returns:
        Created SystemEvent object
    """
    return log_event(
        db, level="WARN", event_type=event_type, lead_id=lead_id,
        payload=payload, exc=exc, correlation_id=correlation_id,
    )


def error(
    db: Session,
    event_type: str,
    lead_id: int | None = None,
    payload: dict | None = None,
    exc: BaseException | None = None,
    correlation_id: str | None = None,
) -> SystemEvent:
    """
    Log an ERROR-level system event.

    Args:
        db: Database session
        event_type: Type of event
        lead_id: Optional lead ID
        payload: Optional event data

    Returns:
        Created SystemEvent object
    """
    return log_event(
        db, level="ERROR", event_type=event_type, lead_id=lead_id,
        payload=payload, exc=exc, correlation_id=correlation_id,
    )


def cleanup_old_events(
    db: Session,
    *,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    cutoff: datetime | None = None,
) -> int:
    """
    Delete SystemEvents older than retention_days (or before cutoff if provided).

    Args:
        db: Database session
        retention_days: Delete events older than this many days (default 90)
        cutoff: Optional explicit cutoff datetime (overrides retention_days)

    Returns:
        Number of rows deleted
    """
    if cutoff is None:
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=UTC)
    stmt = delete(SystemEvent).where(SystemEvent.created_at < cutoff)
    result = db.execute(stmt)
    db.commit()
    deleted = result.rowcount
    logger.info(f"SystemEvent retention: deleted {deleted} events older than {cutoff.isoformat()}")
    return deleted
