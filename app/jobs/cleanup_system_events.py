"""
Scheduled job for SystemEvent retention cleanup.

Deletes events older than retention_days (default 90).
Run via: python -m app.jobs.cleanup_system_events [--retention-days 90]
"""

import logging
import sys

from app.db.session import SessionLocal
from app.services.system_event_service import cleanup_old_events

logger = logging.getLogger(__name__)


def main() -> None:
    """CLI entrypoint for SystemEvent retention cleanup."""
    import argparse

    parser = argparse.ArgumentParser(description="Clean up old SystemEvents (retention)")
    parser.add_argument(
        "--retention-days",
        type=int,
        default=90,
        help="Delete events older than this many days (default: 90)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    db = SessionLocal()
    try:
        deleted = cleanup_old_events(db, retention_days=args.retention_days)
        logger.info(f"Retention cleanup completed: deleted {deleted} events")
    except Exception as e:
        logger.error(f"Retention cleanup failed: {e}", exc_info=True)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
