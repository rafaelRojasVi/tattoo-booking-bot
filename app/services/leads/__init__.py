"""Lead CRUD and identity. Re-exports for stable public API."""

from app.services.leads.leads import (
    ACTIVE_STATUSES,
    INACTIVE_STATUSES,
    get_lead_or_none,
    get_or_create_lead,
)

__all__ = [
    "ACTIVE_STATUSES",
    "INACTIVE_STATUSES",
    "get_lead_or_none",
    "get_or_create_lead",
]
