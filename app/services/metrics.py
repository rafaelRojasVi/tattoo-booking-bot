"""
Metrics and monitoring for system health and safety.

Tracks:
- Duplicate event rates
- Failed atomic updates
- Window closure events
- Template message usage
"""
import logging
from datetime import datetime, timezone
from typing import Dict
from collections import defaultdict
from threading import Lock

logger = logging.getLogger(__name__)

# In-memory metrics (for simple tracking)
# In production, consider using Prometheus, StatsD, or similar
_metrics_lock = Lock()
_metrics: Dict[str, int] = defaultdict(int)
_metrics_timestamps: Dict[str, datetime] = {}


def record_duplicate_event(event_type: str, event_id: str) -> None:
    """
    Record a duplicate event detection.
    
    Args:
        event_type: Type of event (e.g., "stripe.checkout.session.completed")
        event_id: Event ID that was duplicate
    """
    with _metrics_lock:
        key = f"duplicate.{event_type}"
        _metrics[key] += 1
        _metrics_timestamps[f"{key}.last"] = datetime.now(timezone.utc)
    
    logger.info(f"Duplicate event detected: {event_type} (ID: {event_id})")


def record_failed_atomic_update(
    operation: str,
    lead_id: int,
    expected_status: str,
    actual_status: str,
) -> None:
    """
    Record a failed atomic update (status mismatch).
    
    Args:
        operation: Operation name (e.g., "approve_lead")
        lead_id: Lead ID
        expected_status: Expected status
        actual_status: Actual status
    """
    with _metrics_lock:
        key = f"atomic_update_failed.{operation}"
        _metrics[key] += 1
        _metrics_timestamps[f"{key}.last"] = datetime.now(timezone.utc)
    
    logger.warning(
        f"Atomic update failed: {operation} for lead {lead_id}. "
        f"Expected status '{expected_status}', got '{actual_status}'"
    )


def record_window_closed(lead_id: int, message_type: str) -> None:
    """
    Record a 24-hour window closure event.
    
    Args:
        lead_id: Lead ID
        message_type: Type of message that couldn't be sent
    """
    with _metrics_lock:
        key = f"window_closed.{message_type}"
        _metrics[key] += 1
        _metrics_timestamps[f"{key}.last"] = datetime.now(timezone.utc)
    
    logger.info(f"24h window closed for lead {lead_id}, message type: {message_type}")


def record_template_message_used(template_name: str, success: bool) -> None:
    """
    Record template message usage.
    
    Args:
        template_name: Template name used
        success: Whether template message was sent successfully
    """
    with _metrics_lock:
        key = f"template.{template_name}.{'success' if success else 'failed'}"
        _metrics[key] += 1
        _metrics_timestamps[f"{key}.last"] = datetime.now(timezone.utc)


def get_metrics() -> Dict[str, any]:
    """
    Get current metrics snapshot.
    
    Returns:
        dict with metrics counts and last event timestamps
    """
    with _metrics_lock:
        return {
            "counts": dict(_metrics),
            "last_events": {
                k: v.isoformat() for k, v in _metrics_timestamps.items()
            },
        }


def reset_metrics() -> None:
    """Reset all metrics (useful for testing)."""
    with _metrics_lock:
        _metrics.clear()
        _metrics_timestamps.clear()


def get_metrics_summary() -> str:
    """
    Get a human-readable metrics summary.
    
    Returns:
        Formatted string with metrics summary
    """
    metrics = get_metrics()
    lines = ["=== Metrics Summary ==="]
    
    # Group by category
    duplicates = {k: v for k, v in metrics["counts"].items() if k.startswith("duplicate.")}
    atomic_failures = {k: v for k, v in metrics["counts"].items() if k.startswith("atomic_update_failed.")}
    window_closed = {k: v for k, v in metrics["counts"].items() if k.startswith("window_closed.")}
    templates = {k: v for k, v in metrics["counts"].items() if k.startswith("template.")}
    
    if duplicates:
        lines.append("\nDuplicate Events:")
        for key, count in sorted(duplicates.items()):
            event_type = key.replace("duplicate.", "")
            lines.append(f"  {event_type}: {count}")
    
    if atomic_failures:
        lines.append("\nFailed Atomic Updates:")
        for key, count in sorted(atomic_failures.items()):
            operation = key.replace("atomic_update_failed.", "")
            lines.append(f"  {operation}: {count}")
    
    if window_closed:
        lines.append("\n24h Window Closures:")
        for key, count in sorted(window_closed.items()):
            msg_type = key.replace("window_closed.", "")
            lines.append(f"  {msg_type}: {count}")
    
    if templates:
        lines.append("\nTemplate Messages:")
        for key, count in sorted(templates.items()):
            template_info = key.replace("template.", "")
            lines.append(f"  {template_info}: {count}")
    
    if not any([duplicates, atomic_failures, window_closed, templates]):
        lines.append("\nNo metrics recorded yet.")
    
    return "\n".join(lines)
