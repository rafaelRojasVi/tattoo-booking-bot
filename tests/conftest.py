import os
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Set test environment variables before importing app
# Force dev mode for default test app; production validation tests override and reload
os.environ["APP_ENV"] = "dev"
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test_token")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "test_token")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test_id")
# Note: WHATSAPP_APP_SECRET not set by default - allows tests without signature verification
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_test")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test")
os.environ.setdefault("FRESHA_BOOKING_URL", "https://test.com")
os.environ.setdefault("WHATSAPP_DRY_RUN", "true")
os.environ.setdefault("DEMO_MODE", "false")  # Ensure demo mode is off in tests
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")  # Disable rate limiting in tests

from app.db.base import Base
from app.db.deps import get_db
# Import all models so Base.metadata includes every table (e.g. attachments)
import app.db.models as _models  # noqa: F401
from app.db.models import Attachment, Lead, LeadAnswer, ProcessedMessage, ActionToken, SystemEvent  # noqa: F401
from app.main import app

# Test database URL (in-memory SQLite for fast tests)
SQLALCHEMY_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///:memory:")


def is_sqlite() -> bool:
    """Return True if the test database is SQLite (e.g. in-memory tests)."""
    url = SQLALCHEMY_DATABASE_URL or ""
    return url.startswith("sqlite")


# SQLite needs check_same_thread=False and StaticPool; Postgres does not support check_same_thread
if is_sqlite():
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
else:
    engine = create_engine(SQLALCHEMY_DATABASE_URL)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Make the app use the same DB so background tasks (e.g. attachment upload job) see the same schema
import app.db.session as _db_session

_db_session.engine = engine
_db_session.SessionLocal = TestingSessionLocal


@pytest.fixture(scope="function")
def db():
    """Create a fresh database for each test."""
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db):
    """Create a test client with database dependency override."""

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True, scope="function")
def mock_stripe(monkeypatch):
    """
    Automatically mock Stripe API calls for all tests.
    This prevents any real Stripe API calls and ensures deterministic test behavior.
    """
    # Mock checkout session creation
    mock_session = MagicMock()
    mock_session.id = "cs_test_mock123"
    mock_session.url = "https://checkout.stripe.com/test/cs_test_mock123"
    # Calculate expires_at (24 hours from now)
    expires_at = datetime.now(UTC) + timedelta(hours=24)
    mock_session.expires_at = int(expires_at.timestamp())

    # Patch stripe.checkout.Session.create
    def mock_create(*args, **kwargs):
        return mock_session

    monkeypatch.setattr("stripe.checkout.Session.create", mock_create)

    # Mock webhook signature verification (success by default)
    # Tests that need to test signature failure should override this
    def mock_construct_event(payload, sig_header, secret, tolerance=300):
        """Mock webhook event construction - succeeds by default."""
        import json

        try:
            if isinstance(payload, bytes):
                event_data = json.loads(payload.decode("utf-8"))
            else:
                event_data = json.loads(payload)
            return event_data
        except Exception:
            # Return a default test event if parsing fails
            return {
                "id": "evt_test_mock",
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "id": "cs_test_mock123",
                        "client_reference_id": "1",
                        "metadata": {"lead_id": "1"},
                    }
                },
            }

    monkeypatch.setattr("stripe.Webhook.construct_event", mock_construct_event)

    yield
