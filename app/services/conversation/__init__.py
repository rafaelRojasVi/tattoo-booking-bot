"""
Conversation flow: state machine, qualifying, booking, handover.

Re-exports for stable public API: from app.services.conversation import handle_inbound_message, STATUS_*, etc.
"""

from app.constants.statuses import (
    STATUS_ABANDONED,
    STATUS_AWAITING_DEPOSIT,
    STATUS_BOOKED,
    STATUS_BOOKING_LINK_SENT,
    STATUS_BOOKING_PENDING,
    STATUS_CANCELLED,
    STATUS_COLLECTING_TIME_WINDOWS,
    STATUS_DEPOSIT_EXPIRED,
    STATUS_DEPOSIT_PAID,
    STATUS_NEEDS_ARTIST_REPLY,
    STATUS_NEEDS_FOLLOW_UP,
    STATUS_NEEDS_MANUAL_FOLLOW_UP,
    STATUS_NEW,
    STATUS_OPTOUT,
    STATUS_PENDING_APPROVAL,
    STATUS_QUALIFYING,
    STATUS_REFUNDED,
    STATUS_REJECTED,
    STATUS_STALE,
    STATUS_TOUR_CONVERSION_OFFERED,
    STATUS_WAITLISTED,
)
from app.services.conversation.conversation import (
    HANDOVER_HOLD_REPLY_COOLDOWN_HOURS,
    _complete_qualification,
    _handle_new_lead,
    _handle_qualifying_lead,
    _maybe_send_confirmation_summary,
    get_lead_summary,
    handle_inbound_message,
)
from app.services.conversation.state_machine import (
    ALLOWED_TRANSITIONS,
    advance_step_if_at,
    get_allowed_transitions,
    get_state_semantics,
    is_terminal_state,
    transition,
)

from . import conversation_booking, conversation_qualifying
from .conversation_booking import _handle_booking_pending

__all__ = [
    "ALLOWED_TRANSITIONS",
    "HANDOVER_HOLD_REPLY_COOLDOWN_HOURS",
    "STATUS_ABANDONED",
    "STATUS_AWAITING_DEPOSIT",
    "STATUS_BOOKED",
    "STATUS_BOOKING_LINK_SENT",
    "STATUS_BOOKING_PENDING",
    "STATUS_CANCELLED",
    "STATUS_COLLECTING_TIME_WINDOWS",
    "STATUS_DEPOSIT_EXPIRED",
    "STATUS_DEPOSIT_PAID",
    "STATUS_NEEDS_ARTIST_REPLY",
    "STATUS_NEEDS_FOLLOW_UP",
    "STATUS_NEEDS_MANUAL_FOLLOW_UP",
    "STATUS_NEW",
    "STATUS_OPTOUT",
    "STATUS_PENDING_APPROVAL",
    "STATUS_QUALIFYING",
    "STATUS_REFUNDED",
    "STATUS_REJECTED",
    "STATUS_STALE",
    "STATUS_TOUR_CONVERSION_OFFERED",
    "STATUS_WAITLISTED",
    "_complete_qualification",
    "_handle_new_lead",
    "_handle_qualifying_lead",
    "_maybe_send_confirmation_summary",
    "advance_step_if_at",
    "get_allowed_transitions",
    "get_lead_summary",
    "get_state_semantics",
    "handle_inbound_message",
    "is_terminal_state",
    "transition",
    "conversation_booking",
    "conversation_qualifying",
    "_handle_booking_pending",
]
