"""
System event logging service.

Provides structured logging of key system events and failures to the database.
"""

import logging

from sqlalchemy.orm import Session

from app.db.models import SystemEvent

logger = logging.getLogger(__name__)


def log_event(
    db: Session,
    level: str,
    event_type: str,
    lead_id: int | None = None,
    payload: dict | None = None,
) -> SystemEvent:
    """
    Log a system event to the database.

    Args:
        db: Database session
        level: Event level (INFO, WARN, ERROR)
        event_type: Type of event (e.g., "whatsapp.send_failure", "template.fallback_used")
        lead_id: Optional lead ID associated with the event
        payload: Optional additional event data (dict)

    Returns:
        Created SystemEvent object
    """
    event = SystemEvent(
        level=level.upper(),
        event_type=event_type,
        lead_id=lead_id,
        payload=payload,
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
    return log_event(db, level="INFO", event_type=event_type, lead_id=lead_id, payload=payload)


def warn(
    db: Session,
    event_type: str,
    lead_id: int | None = None,
    payload: dict | None = None,
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
    return log_event(db, level="WARN", event_type=event_type, lead_id=lead_id, payload=payload)


def error(
    db: Session,
    event_type: str,
    lead_id: int | None = None,
    payload: dict | None = None,
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
    return log_event(db, level="ERROR", event_type=event_type, lead_id=lead_id, payload=payload)
