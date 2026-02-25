"""
Shared API error message helpers.

Used to keep status-mismatch HTTP 400 detail strings DRY across admin and action endpoints.
Exact wording is preserved per call site (admin vs actions).
"""


def status_mismatch_detail_admin(
    action_phrase: str, lead_status: str, expected_status: str
) -> str:
    """
    Build 400 detail for status mismatch after update_lead_status_if_matches (admin endpoints).
    Format: "Cannot {action_phrase} in status '{lead_status}'. Lead must be in '{expected_status}'."
    """
    return (
        f"Cannot {action_phrase} in status '{lead_status}'. "
        f"Lead must be in '{expected_status}'."
    )


def status_mismatch_detail_actions(action_phrase: str, lead_status: str) -> str:
    """
    Build 400 detail for status mismatch in action-token handlers (no expected status in message).
    Format: "Cannot {action_phrase} in status '{lead_status}'"
    """
    return f"Cannot {action_phrase} in status '{lead_status}'"
