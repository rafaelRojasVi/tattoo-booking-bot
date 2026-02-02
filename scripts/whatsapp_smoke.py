"""
WhatsApp Cloud API smoke test script.

Tests sending a message via WhatsApp Cloud API.
Run from Docker: docker compose exec api python scripts/whatsapp_smoke.py

Usage:
    python scripts/whatsapp_smoke.py [--to PHONE_NUMBER] [--template hello_world]
"""

import asyncio
import sys
from pathlib import Path

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import settings
from app.services.messaging import send_whatsapp_message


async def send_test_message(to: str | None = None, use_template: bool = False):
    """Send a test WhatsApp message."""
    # Default to a test number (you should replace this with your test number)
    recipient = to or "1234567890"  # Replace with your test WhatsApp number
    
    if use_template:
        # Use hello_world template (requires template to be approved in Meta dashboard)
        print("⚠️  Template messages require approval in Meta dashboard.")
        print("   For initial testing, use plain text messages instead.")
        print("   Run without --template flag to send plain text.")
        return
    
    message = "Hello! This is a test message from your tattoo booking bot. 🎨"
    
    print(f"📤 Sending WhatsApp message...")
    print(f"   To: {recipient}")
    print(f"   Message: {message}")
    print(f"   Dry Run: {settings.whatsapp_dry_run}")
    print()
    
    try:
        result = await send_whatsapp_message(
            to=recipient,
            message=message,
            dry_run=settings.whatsapp_dry_run,
        )
        
        print("✅ Result:")
        print(f"   Status: {result.get('status')}")
        if result.get('message_id'):
            print(f"   Message ID: {result.get('message_id')}")
        if result.get('status') == 'dry_run':
            print()
            print("💡 This was a dry run. To send real messages:")
            print("   1. Set WHATSAPP_DRY_RUN=false in .env")
            print("   2. Ensure WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID are set")
            print("   3. Run this script again")
        
    except Exception as e:
        print(f"❌ Error sending message: {e}")
        print()
        print("💡 Troubleshooting:")
        print("   1. Check WHATSAPP_ACCESS_TOKEN is set and valid")
        print("   2. Check WHATSAPP_PHONE_NUMBER_ID is set correctly")
        print("   3. Verify the recipient number is in your test number's allowed list")
        print("   4. Check Meta dashboard for API errors")
        sys.exit(1)


def main():
    """CLI entrypoint."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Send a test WhatsApp message")
    parser.add_argument(
        "--to",
        type=str,
        help="Recipient WhatsApp number (with country code, no +)",
    )
    parser.add_argument(
        "--template",
        action="store_true",
        help="Use hello_world template (requires approval)",
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("WhatsApp Cloud API Smoke Test")
    print("=" * 60)
    print()
    print(f"Access Token: {'✅ Set' if settings.whatsapp_access_token and settings.whatsapp_access_token not in ['test_token', ''] else '❌ Missing'}")
    print(f"Phone Number ID: {'✅ Set' if settings.whatsapp_phone_number_id and settings.whatsapp_phone_number_id not in ['test_id', ''] else '❌ Missing'}")
    print(f"Dry Run Mode: {'✅ Enabled' if settings.whatsapp_dry_run else '❌ Disabled (will send real messages!)'}")
    print()
    
    asyncio.run(send_test_message(to=args.to, use_template=args.template))


if __name__ == "__main__":
    main()
