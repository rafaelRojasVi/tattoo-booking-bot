"""
Test script to verify attachment creation and upload pipeline.

Run this inside Docker:
    docker compose exec api python scripts/test_attachment_pipeline.py
"""

import os
import sys

# Add app directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.models import Attachment
from app.db.session import SessionLocal


def check_attachments():
    """Check for recent attachments in the database."""
    db = SessionLocal()
    try:
        # Get most recent attachment
        attachment = db.query(Attachment).order_by(Attachment.id.desc()).first()

        if not attachment:
            print("❌ No attachments found in database")
            print("   → Send a WhatsApp image message to create one")
            return False

        print(f"✅ Found attachment ID: {attachment.id}")
        print(f"   Lead ID: {attachment.lead_id}")
        print(f"   Status: {attachment.upload_status}")
        print(f"   WhatsApp Media ID: {attachment.whatsapp_media_id}")
        print(f"   Upload Attempts: {attachment.upload_attempts}")
        print(f"   Object Key: {attachment.object_key or '(not uploaded yet)'}")
        print(f"   Created At: {attachment.created_at}")

        if attachment.last_error:
            print(f"   Last Error: {attachment.last_error[:100]}")

        return True

    finally:
        db.close()


def list_all_attachments():
    """List all attachments with their status."""
    db = SessionLocal()
    try:
        attachments = db.query(Attachment).order_by(Attachment.id.desc()).limit(10).all()

        if not attachments:
            print("No attachments found")
            return

        print("\n📋 Recent attachments (showing up to 10):")
        print(f"{'ID':<5} {'Lead':<6} {'Status':<12} {'Attempts':<8} {'Object Key':<30}")
        print("-" * 80)

        for att in attachments:
            object_key = (
                (att.object_key or "")[:28] + ".."
                if att.object_key and len(att.object_key) > 30
                else (att.object_key or "")
            )
            print(
                f"{att.id:<5} {att.lead_id:<6} {att.upload_status:<12} {att.upload_attempts:<8} {object_key:<30}"
            )

    finally:
        db.close()


if __name__ == "__main__":
    print("Checking attachment pipeline...\n")

    if check_attachments():
        print()
        list_all_attachments()
        print("\n💡 To process pending uploads, run:")
        print(
            "   docker compose exec api python -m app.jobs.sweep_pending_uploads --limit 50 --verbose"
        )
    else:
        print("\n💡 To test attachment creation:")
        print("   1. Send an image via WhatsApp webhook")
        print("   2. Or use the demo endpoint (if DEMO_MODE=true)")
        print("   3. Then run this script again to check")
