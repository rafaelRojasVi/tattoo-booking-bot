"""
Sweeper job for pending media uploads.

This job retries failed uploads and processes pending attachments.
Can be run as a CLI command or scheduled via cron.
"""

import logging
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models import Attachment
from app.db.session import SessionLocal
from app.services.integrations.media_upload import attempt_upload_attachment

logger = logging.getLogger(__name__)


def run_sweep(limit: int = 50, retry_delay_minutes: int = 5) -> dict:
    """
    Sweep pending uploads and retry failed ones.

    Args:
        limit: Maximum number of attachments to process in this run
        retry_delay_minutes: Minimum minutes between retry attempts

    Returns:
        Summary dict with counts
    """
    db: Session = SessionLocal()
    try:
        # Find attachments that need processing:
        # - PENDING status with no attempts yet, OR
        # - PENDING status with last_attempt_at older than retry_delay_minutes
        cutoff_time = datetime.now(UTC) - timedelta(minutes=retry_delay_minutes)

        pending_attachments = (
            db.query(Attachment)
            .filter(
                Attachment.upload_status == "PENDING",
                or_(
                    Attachment.last_attempt_at.is_(None),
                    Attachment.last_attempt_at < cutoff_time,
                ),
                Attachment.upload_attempts < 5,  # Don't retry if already failed 5 times
            )
            .limit(limit)
            .all()
        )

        results = {
            "checked": len(pending_attachments),
            "processed": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
        }

        for attachment in pending_attachments:
            try:
                # Attempt upload (async function, run it synchronously)
                import asyncio

                # Get or create event loop
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                # Pass the existing db session to the core function
                loop.run_until_complete(attempt_upload_attachment(db, attachment.id))

                results["processed"] += 1

                # Refresh to get updated status
                db.refresh(attachment)

                if attachment.upload_status == "UPLOADED":
                    results["success"] += 1
                elif attachment.upload_status == "FAILED":
                    results["failed"] += 1
                else:
                    results["skipped"] += 1

            except Exception as e:
                logger.error(f"Error processing attachment {attachment.id}: {e}", exc_info=True)
                results["failed"] += 1

        logger.info(
            f"Upload sweep completed: {results['success']} succeeded, "
            f"{results['failed']} failed, {results['skipped']} skipped"
        )

        return results

    finally:
        db.close()


def main() -> None:
    """CLI entrypoint for sweeper job."""
    import argparse

    parser = argparse.ArgumentParser(description="Sweep pending media uploads")
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of attachments to process (default: 50)",
    )
    parser.add_argument(
        "--retry-delay",
        type=int,
        default=5,
        help="Minimum minutes between retry attempts (default: 5)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info(f"Starting upload sweep (limit={args.limit}, retry_delay={args.retry_delay}min)")

    try:
        results = run_sweep(limit=args.limit, retry_delay_minutes=args.retry_delay)

        logger.info(
            f"Sweep completed: checked={results['checked']}, "
            f"processed={results['processed']}, success={results['success']}, "
            f"failed={results['failed']}, skipped={results['skipped']}"
        )

        # Exit with error code if there were failures
        if results["failed"] > 0:
            sys.exit(1)

    except Exception as e:
        logger.error(f"Sweep job failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
