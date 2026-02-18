"""
Lead status constants - centralized to avoid circular imports.
"""

# Core statuses (Phase 1 proposal lifecycle)
STATUS_NEW = "NEW"
STATUS_QUALIFYING = "QUALIFYING"
STATUS_PENDING_APPROVAL = "PENDING_APPROVAL"
STATUS_AWAITING_DEPOSIT = "AWAITING_DEPOSIT"
STATUS_DEPOSIT_PAID = "DEPOSIT_PAID"
STATUS_BOOKING_PENDING = "BOOKING_PENDING"  # Phase 1: replaces BOOKING_LINK_SENT
STATUS_BOOKED = "BOOKED"

# Operational statuses
STATUS_NEEDS_ARTIST_REPLY = "NEEDS_ARTIST_REPLY"
STATUS_NEEDS_FOLLOW_UP = "NEEDS_FOLLOW_UP"
STATUS_REJECTED = "REJECTED"

# Housekeeping statuses
STATUS_ABANDONED = "ABANDONED"
STATUS_STALE = "STALE"
STATUS_OPTOUT = "OPTOUT"  # Client opted out (STOP/UNSUBSCRIBE)

# Travel/tour statuses (Phase 1)
STATUS_TOUR_CONVERSION_OFFERED = "TOUR_CONVERSION_OFFERED"
STATUS_WAITLISTED = "WAITLISTED"

# Booking statuses
STATUS_COLLECTING_TIME_WINDOWS = (
    "COLLECTING_TIME_WINDOWS"  # Collecting preferred time windows when no slots available
)

# Payment-related statuses (future features)
STATUS_DEPOSIT_EXPIRED = "DEPOSIT_EXPIRED"  # Deposit link sent but not paid after X days
STATUS_REFUNDED = "REFUNDED"  # Stripe refund event or manual refund
STATUS_CANCELLED = "CANCELLED"  # Client cancels after paying / before booking

# Legacy (kept for backward compatibility)
STATUS_NEEDS_MANUAL_FOLLOW_UP = "NEEDS_MANUAL_FOLLOW_UP"  # Maps to NEEDS_FOLLOW_UP
STATUS_BOOKING_LINK_SENT = "BOOKING_LINK_SENT"  # Legacy - maps to BOOKING_PENDING
