"""
Helpers for optional datetime handling (mypy-safe .isoformat() / .replace() on Optional[datetime]).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def iso_or_none(dt: datetime | None | Any) -> str | None:
    """
    Return ISO format string for dt, or None if dt is None.
    Accepts datetime or SQLAlchemy DateTime (Mapped[DateTime | None]) for convenience.
    """
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return None


def dt_replace_utc(dt: datetime | None | Any) -> datetime | None:
    """
    Return dt with tzinfo=UTC if naive, or None if dt is None.
    Use for optional datetimes that may be naive (e.g. from DB).
    """
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt
    return None
