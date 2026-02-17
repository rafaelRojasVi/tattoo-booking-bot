"""
Admin API request/response schemas.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class RejectRequest(BaseModel):
    """Request schema for rejecting a lead."""

    reason: str | None = None


class SendDepositRequest(BaseModel):
    """Request schema for sending deposit link."""

    amount_pence: int | None = None  # Optional override, defaults to tier calculation


class SendBookingLinkRequest(BaseModel):
    """Request schema for sending booking link."""

    booking_url: str
    booking_tool: str = "FRESHA"  # FRESHA, CALENDLY, GCAL, OTHER


class LeadResponse(BaseModel):
    """Response schema for a single lead."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    wa_from: str
    status: str
    current_step: int | None = None
    created_at: datetime
    # Optional detailed fields
    summary: dict[str, Any] | None = None


class LeadListResponse(BaseModel):
    """Response schema for list of leads."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    wa_from: str
    status: str
    current_step: int | None = None
    created_at: datetime


class FunnelMetricsResponse(BaseModel):
    """Response schema for funnel metrics."""

    counts: dict[str, int]
    rates: dict[str, float]
    days: int


class AdminActionResponse(BaseModel):
    """Response schema for admin actions (approve, reject, send-deposit, etc.)."""

    success: bool
    message: str
    lead_id: int
    status: str
    # Optional fields for specific actions
    deposit_amount_pence: int | None = None
    checkout_url: str | None = None
    checkout_session_id: str | None = None
    booking_link: str | None = None
