"""
Funnel metrics service - computes conversion rates and funnel statistics.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Lead
from app.constants.statuses import (
    STATUS_ABANDONED,
    STATUS_BOOKED,
    STATUS_NEEDS_ARTIST_REPLY,
    STATUS_NEEDS_FOLLOW_UP,
    STATUS_PENDING_APPROVAL,
    STATUS_REJECTED,
    STATUS_STALE,
)

logger = logging.getLogger(__name__)


def get_funnel_metrics(db: Session, days: int = 7) -> dict:
    """
    Get funnel metrics for the last N days.

    Args:
        db: Database session
        days: Number of days to look back

    Returns:
        Dict with counts and conversion rates
    """
    # Clamp days to avoid OverflowError (timedelta max ~999999999 days on some platforms)
    days = max(1, min(days, 3650))  # 1 to ~10 years
    cutoff_date = datetime.now(UTC) - timedelta(days=days)

    # Base query: leads created in time window
    base_stmt = select(Lead).where(Lead.created_at >= cutoff_date)

    # Counts by status/event
    counts = {}

    # New leads (all leads created in time window, regardless of current status)
    counts["new_leads"] = len(db.execute(base_stmt).scalars().all())

    # Qualifying started
    counts["qualifying_started"] = len(
        db.execute(base_stmt.where(Lead.qualifying_started_at.isnot(None))).scalars().all()
    )

    # Qualifying completed
    counts["qualifying_completed"] = len(
        db.execute(base_stmt.where(Lead.qualifying_completed_at.isnot(None))).scalars().all()
    )

    # Pending approval
    counts["pending_approval"] = len(
        db.execute(base_stmt.where(Lead.status == STATUS_PENDING_APPROVAL)).scalars().all()
    )

    # Approved (has approved_at timestamp)
    counts["approved"] = len(
        db.execute(base_stmt.where(Lead.approved_at.isnot(None))).scalars().all()
    )

    # Rejected
    counts["rejected"] = len(
        db.execute(base_stmt.where(Lead.status == STATUS_REJECTED)).scalars().all()
    )

    # Needs follow up
    counts["needs_follow_up"] = len(
        db.execute(base_stmt.where(Lead.status == STATUS_NEEDS_FOLLOW_UP)).scalars().all()
    )

    # Needs artist reply
    counts["needs_artist_reply"] = len(
        db.execute(base_stmt.where(Lead.status == STATUS_NEEDS_ARTIST_REPLY)).scalars().all()
    )

    # Deposit sent (has deposit_sent_at)
    counts["deposit_sent"] = len(
        db.execute(base_stmt.where(Lead.deposit_sent_at.isnot(None))).scalars().all()
    )

    # Deposit paid
    counts["deposit_paid"] = len(
        db.execute(base_stmt.where(Lead.deposit_paid_at.isnot(None))).scalars().all()
    )

    # Booked
    counts["booked"] = len(
        db.execute(base_stmt.where(Lead.status == STATUS_BOOKED)).scalars().all()
    )

    # Abandoned
    counts["abandoned"] = len(
        db.execute(base_stmt.where(Lead.status == STATUS_ABANDONED)).scalars().all()
    )

    # Stale
    counts["stale"] = len(db.execute(base_stmt.where(Lead.status == STATUS_STALE)).scalars().all())

    # Compute rates
    rates = {}

    # Consult start rate = qualifying_started / new_leads
    if counts["new_leads"] > 0:
        rates["consult_start_rate"] = counts["qualifying_started"] / counts["new_leads"]
    else:
        rates["consult_start_rate"] = 0.0

    # Consult completion rate = qualifying_completed / qualifying_started
    if counts["qualifying_started"] > 0:
        rates["consult_completion_rate"] = (
            counts["qualifying_completed"] / counts["qualifying_started"]
        )
    else:
        rates["consult_completion_rate"] = 0.0

    # Approval rate = approved / pending_approval (use pending_approval count, not all completed)
    if counts["pending_approval"] > 0:
        rates["approval_rate"] = counts["approved"] / counts["pending_approval"]
    else:
        rates["approval_rate"] = 0.0

    # Deposit pay rate = deposit_paid / deposit_sent
    if counts["deposit_sent"] > 0:
        rates["deposit_pay_rate"] = counts["deposit_paid"] / counts["deposit_sent"]
    else:
        rates["deposit_pay_rate"] = 0.0

    # Booking completion rate = booked / deposit_paid
    if counts["deposit_paid"] > 0:
        rates["booking_completion_rate"] = counts["booked"] / counts["deposit_paid"]
    else:
        rates["booking_completion_rate"] = 0.0

    # Overall conversion = booked / new_leads
    if counts["new_leads"] > 0:
        rates["overall_conversion"] = counts["booked"] / counts["new_leads"]
    else:
        rates["overall_conversion"] = 0.0

    # Drop-off rates
    if counts["qualifying_started"] > 0:
        rates["abandoned_rate"] = counts["abandoned"] / counts["qualifying_started"]
    else:
        rates["abandoned_rate"] = 0.0

    if counts["qualifying_completed"] > 0:
        rates["stale_rate"] = counts["stale"] / counts["qualifying_completed"]
    else:
        rates["stale_rate"] = 0.0

    if counts["qualifying_completed"] > 0:
        rates["needs_follow_up_rate"] = counts["needs_follow_up"] / counts["qualifying_completed"]
    else:
        rates["needs_follow_up_rate"] = 0.0

    return {
        "period_days": days,
        "cutoff_date": cutoff_date.isoformat(),
        "counts": counts,
        "rates": rates,
    }
