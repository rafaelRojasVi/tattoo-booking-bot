"""
Pure policy helpers for conversation flows (no DB, no IO).

Centralizes keyword/intent checks and cooldown logic so behavior is testable
and consistent across qualifying and booking.
"""

from datetime import datetime, timedelta


def normalize_message(text: str) -> str:
    """Normalize inbound text for keyword matching (strip, upper)."""
    return text.strip().upper()


# --- Opt-out / opt-back-in (compliance) ---

OPT_OUT_KEYWORDS = frozenset({"STOP", "UNSUBSCRIBE", "OPT OUT", "OPTOUT"})


def is_opt_out_message(message_text: str) -> bool:
    """True if the message is a clear opt-out request (STOP, UNSUBSCRIBE, etc.)."""
    return normalize_message(message_text) in OPT_OUT_KEYWORDS


OPT_BACK_IN_KEYWORDS = frozenset({"START", "RESUME", "CONTINUE", "YES"})


def is_opt_back_in_message(message_text: str) -> bool:
    """True if the message requests to opt back in after OPTOUT (restart flow)."""
    return normalize_message(message_text) in OPT_BACK_IN_KEYWORDS


# --- Qualifying: human / refund / delete ---

HUMAN_REQUEST_KEYWORDS = frozenset({"HUMAN", "PERSON", "TALK TO SOMEONE", "REAL PERSON", "AGENT"})


def is_human_request_message(message_text: str) -> bool:
    """True if the message asks for a human/agent."""
    return normalize_message(message_text) in HUMAN_REQUEST_KEYWORDS


def is_refund_request_message(message_text: str) -> bool:
    """True if the message mentions refund."""
    return "REFUND" in normalize_message(message_text)


DELETE_DATA_PHRASES = ("DELETE MY DATA", "DELETE DATA", "REMOVE MY DATA", "GDPR")


def is_delete_data_request_message(message_text: str) -> bool:
    """True if the message requests data deletion / GDPR."""
    upper = normalize_message(message_text)
    return any(phrase in upper for phrase in DELETE_DATA_PHRASES)


# --- Handover hold cooldown (booking) ---


def handover_hold_cooldown_elapsed(
    last_hold_at: datetime | None,
    now_utc: datetime,
    cooldown_hours: float,
) -> bool:
    """
    True if we may send another handover holding message (cooldown elapsed or never sent).

    Uses >= so exactly cooldown_hours ago allows sending again.
    """
    if last_hold_at is None:
        return True
    return (now_utc - last_hold_at) >= timedelta(hours=cooldown_hours)
