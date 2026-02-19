"""
Replay a sample WhatsApp webhook payload to test the webhook endpoint.

This is useful for testing webhook handling without needing to actually
send messages from WhatsApp.

Run from Docker: docker compose exec api python scripts/webhook_replay.py

Usage:
    python scripts/webhook_replay.py [--text "Hello"] [--image] [--from PHONE_NUMBER]
"""

import json
import sys
from pathlib import Path

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

from app.core.config import settings


def create_text_message_payload(wa_from: str, text: str, message_id: str = "wamid.test123"):
    """Create a sample text message webhook payload."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550555555",
                                "phone_number_id": settings.whatsapp_phone_number_id,
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Test User"},
                                    "wa_id": wa_from,
                                }
                            ],
                            "messages": [
                                {
                                    "from": wa_from,
                                    "id": message_id,
                                    "timestamp": "1234567890",
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


def create_image_message_payload(
    wa_from: str, media_id: str = "media_test123", message_id: str = "wamid.test456"
):
    """Create a sample image message webhook payload."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550555555",
                                "phone_number_id": settings.whatsapp_phone_number_id,
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Test User"},
                                    "wa_id": wa_from,
                                }
                            ],
                            "messages": [
                                {
                                    "from": wa_from,
                                    "id": message_id,
                                    "timestamp": "1234567890",
                                    "type": "image",
                                    "image": {
                                        "id": media_id,
                                        "mime_type": "image/jpeg",
                                    },
                                    "caption": "This is a test reference image",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


def calculate_signature(payload_bytes: bytes) -> str | None:
    """Calculate webhook signature for testing."""
    if not settings.whatsapp_app_secret:
        return None

    import hashlib
    import hmac

    signature = hmac.new(
        settings.whatsapp_app_secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()

    return f"sha256={signature}"


def send_webhook_payload(payload: dict, base_url: str = "http://localhost:8000"):
    """Send webhook payload to the webhook endpoint."""
    webhook_url = f"{base_url}/webhooks/whatsapp"

    # Convert to JSON bytes for signature calculation
    payload_json = json.dumps(payload)
    payload_bytes = payload_json.encode("utf-8")

    # Calculate signature if app secret is configured
    signature = calculate_signature(payload_bytes)

    headers = {
        "Content-Type": "application/json",
    }
    if signature:
        headers["X-Hub-Signature-256"] = signature

    print(f"📤 Sending webhook payload to: {webhook_url}")
    print(f"   Payload: {json.dumps(payload, indent=2)}")
    if signature:
        print(f"   Signature: {signature[:20]}...")
    print()

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(webhook_url, json=payload, headers=headers)

            print("📥 Response:")
            print(f"   Status: {response.status_code}")
            print(f"   Body: {response.text}")
            print()

            if response.status_code == 200:
                print("✅ Webhook processed successfully!")
                try:
                    result = response.json()
                    if result.get("lead_id"):
                        print(f"   Lead ID: {result.get('lead_id')}")
                    if result.get("type"):
                        print(f"   Type: {result.get('type')}")
                except Exception:
                    pass
            else:
                print("❌ Webhook returned error status")
                return False

    except Exception as e:
        print(f"❌ Error sending webhook: {e}")
        return False

    return True


def main():
    """CLI entrypoint."""
    import argparse

    parser = argparse.ArgumentParser(description="Replay WhatsApp webhook payload")
    parser.add_argument(
        "--text",
        type=str,
        default="Hello, I want a tattoo",
        help="Text message content",
    )
    parser.add_argument(
        "--image",
        action="store_true",
        help="Send image message instead of text",
    )
    parser.add_argument(
        "--from",
        dest="wa_from",
        type=str,
        default="1234567890",
        help="Sender WhatsApp number (with country code, no +)",
    )
    parser.add_argument(
        "--url",
        type=str,
        default="http://localhost:8000",
        help="Base URL of the API (default: http://localhost:8000)",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("WhatsApp Webhook Replay Test")
    print("=" * 60)
    print()
    print(
        f"Verify Token: {'✅ Set' if settings.whatsapp_verify_token and settings.whatsapp_verify_token != 'your_whatsapp_verify_token_here' else '❌ Missing'}"
    )
    print(
        f"App Secret: {'✅ Set' if settings.whatsapp_app_secret else '⚠️  Not set (signature verification disabled)'}"
    )
    print()

    if args.image:
        payload = create_image_message_payload(args.wa_from)
        print("📷 Creating image message payload...")
    else:
        payload = create_text_message_payload(args.wa_from, args.text)
        print("💬 Creating text message payload...")

    print()

    success = send_webhook_payload(payload, base_url=args.url)

    if success:
        print("💡 Next steps:")
        print("   1. Check the database for new Lead record")
        print("   2. Check for ProcessedMessage record (idempotency)")
        if args.image:
            print("   3. Check for Attachment record with PENDING status")
        print("   4. Check logs for any errors")
    else:
        print("💡 Troubleshooting:")
        print("   1. Ensure the API is running (docker compose up)")
        print("   2. Check WHATSAPP_VERIFY_TOKEN matches your Meta webhook config")
        print("   3. Check webhook signature if WHATSAPP_APP_SECRET is set")
        sys.exit(1)


if __name__ == "__main__":
    main()
