#!/usr/bin/env python3
"""
Check that the app imports cleanly (same chain as CI when loading conftest).
Run before pushing to catch ModuleNotFoundError / ImportError from reorg.

From repo root:
  python scripts/check_imports.py
  uv run python scripts/check_imports.py
  pytest tests/ --collect-only -q   # alternative: collect tests (loads conftest)
"""
import os
import sys

# Ensure repo root is on path (when run as python scripts/check_imports.py)
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

# Same env as tests/conftest.py so app.main and its deps load
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test_token")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "test_token")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test_id")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_test")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test")
os.environ.setdefault("FRESHA_BOOKING_URL", "https://test.com")
os.environ.setdefault("WHATSAPP_DRY_RUN", "true")
os.environ.setdefault("DEMO_MODE", "false")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

def main() -> int:
    try:
        from app.main import app  # noqa: F401
        print("OK: app.main imports successfully (same as CI conftest load).")
        return 0
    except Exception as e:
        print("FAIL: Import error (CI would fail here):", file=sys.stderr)
        print(e, file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
