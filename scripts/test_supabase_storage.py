"""
Quick test script to verify Supabase Storage connectivity.

Run this inside Docker:
    docker compose exec api python -m scripts.test_supabase_storage
Or:
    docker compose exec api python scripts/test_supabase_storage.py
"""

import os
import sys

# Add app directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from supabase import create_client

from app.core.config import settings


def test_supabase_storage():
    """Test Supabase Storage upload and signed URL generation."""
    print("Testing Supabase Storage connectivity...")
    print(f"URL: {settings.supabase_url}")
    print(f"Bucket: {settings.supabase_storage_bucket}")
    print(
        f"Service Role Key: {'*' * 20}...{settings.supabase_service_role_key[-10:] if settings.supabase_service_role_key else 'NOT SET'}"
    )
    print()

    if not settings.supabase_url or not settings.supabase_service_role_key:
        print("❌ ERROR: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set")
        return False

    try:
        # Create client
        print("1. Creating Supabase client...")
        client = create_client(settings.supabase_url, settings.supabase_service_role_key)
        print("   ✅ Client created")

        # Test upload
        bucket = settings.supabase_storage_bucket
        test_path = "smoke/hello.txt"
        test_content = b"Hello from tattoo-booking-bot!\n"

        print(f"2. Uploading test file to {bucket}/{test_path}...")
        client.storage.from_(bucket).upload(
            test_path,
            test_content,
            file_options={"content-type": "text/plain", "upsert": "true"},
        )
        print("   ✅ Upload successful")

        # Test signed URL
        print(f"3. Generating signed URL for {test_path}...")
        result = client.storage.from_(bucket).create_signed_url(test_path, 3600)

        if isinstance(result, dict):
            signed_url = result.get("signedURL") or result.get("signed_url")
        else:
            signed_url = result

        assert signed_url is not None, "Failed to generate signed URL"
        print(f"   ✅ Signed URL generated: {signed_url[:80]}...")
        print()
        print("✅ All tests passed! Supabase Storage is configured correctly.")
        return True

    except Exception as e:
        print(f"❌ ERROR: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_supabase_storage()
    sys.exit(0 if success else 1)
