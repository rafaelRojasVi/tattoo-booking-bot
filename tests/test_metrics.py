"""
Tests for metrics and monitoring.
"""

from app.services.metrics import (
    get_metrics,
    get_metrics_summary,
    record_duplicate_event,
    record_failed_atomic_update,
    record_template_message_used,
    record_window_closed,
    reset_metrics,
)


def test_record_duplicate_event():
    """Test recording duplicate events."""
    reset_metrics()

    record_duplicate_event("stripe.checkout.session.completed", "evt_123")
    record_duplicate_event("whatsapp.message", "msg_456")
    record_duplicate_event("stripe.checkout.session.completed", "evt_789")

    metrics = get_metrics()
    assert metrics["counts"]["duplicate.stripe.checkout.session.completed"] == 2
    assert metrics["counts"]["duplicate.whatsapp.message"] == 1


def test_record_failed_atomic_update():
    """Test recording failed atomic updates."""
    reset_metrics()

    record_failed_atomic_update(
        operation="approve_lead",
        lead_id=1,
        expected_status="PENDING_APPROVAL",
        actual_status="AWAITING_DEPOSIT",
    )
    record_failed_atomic_update(
        operation="send_booking_link",
        lead_id=2,
        expected_status="DEPOSIT_PAID",
        actual_status="BOOKING_LINK_SENT",
    )

    metrics = get_metrics()
    assert metrics["counts"]["atomic_update_failed.approve_lead"] == 1
    assert metrics["counts"]["atomic_update_failed.send_booking_link"] == 1


def test_record_window_closed():
    """Test recording window closure events."""
    reset_metrics()

    record_window_closed(lead_id=1, message_type="deposit_link")
    record_window_closed(lead_id=2, message_type="reminder")

    metrics = get_metrics()
    assert metrics["counts"]["window_closed.deposit_link"] == 1
    assert metrics["counts"]["window_closed.reminder"] == 1


def test_record_template_message_used():
    """Test recording template message usage."""
    reset_metrics()

    record_template_message_used("reminder_qualifying", success=True)
    record_template_message_used("reminder_booking", success=True)
    record_template_message_used("reminder_qualifying", success=False)

    metrics = get_metrics()
    assert metrics["counts"]["template.reminder_qualifying.success"] == 1
    assert metrics["counts"]["template.reminder_qualifying.failed"] == 1
    assert metrics["counts"]["template.reminder_booking.success"] == 1


def test_get_metrics_summary():
    """Test metrics summary generation."""
    reset_metrics()

    record_duplicate_event("stripe.checkout.session.completed", "evt_123")
    record_failed_atomic_update("approve_lead", 1, "PENDING_APPROVAL", "AWAITING_DEPOSIT")
    record_window_closed(1, "deposit_link")
    record_template_message_used("reminder_qualifying", success=True)

    summary = get_metrics_summary()

    assert "Duplicate Events" in summary
    assert "stripe.checkout.session.completed" in summary
    assert "Failed Atomic Updates" in summary
    assert "approve_lead" in summary
    assert "24h Window Closures" in summary
    assert "deposit_link" in summary
    assert "Template Messages" in summary
    assert "reminder_qualifying" in summary


def test_reset_metrics():
    """Test resetting metrics."""
    reset_metrics()

    record_duplicate_event("test.event", "evt_123")
    metrics_before = get_metrics()
    assert len(metrics_before["counts"]) > 0

    reset_metrics()
    metrics_after = get_metrics()
    assert len(metrics_after["counts"]) == 0
