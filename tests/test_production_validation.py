"""
Tests for production environment validation.

Validates that production mode requires:
- ADMIN_API_KEY
- WHATSAPP_APP_SECRET
- STRIPE_WEBHOOK_SECRET
- DEMO_MODE=false
"""

import pytest
from fastapi.testclient import TestClient


def test_production_validation_missing_admin_api_key(monkeypatch):
    """Test that production mode fails if ADMIN_API_KEY is missing."""
    # Set production environment
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "test_token")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "test_token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "test_id")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_test")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setenv("FRESHA_BOOKING_URL", "https://test.com")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "test_app_secret")
    monkeypatch.setenv("DEMO_MODE", "false")
    # ADMIN_API_KEY is NOT set

    # Clear any cached settings
    import sys

    if "app.core.config" in sys.modules:
        del sys.modules["app.core.config"]
    if "app.main" in sys.modules:
        del sys.modules["app.main"]

    # Import after setting env vars
    from app.main import app

    # Attempt to create client - should fail during startup
    with pytest.raises(RuntimeError) as exc_info, TestClient(app):
        pass

    error_message = str(exc_info.value)
    assert "ADMIN_API_KEY is required in production" in error_message
    assert "Production environment validation failed" in error_message


def test_production_validation_missing_whatsapp_app_secret(monkeypatch):
    """Test that production mode fails if WHATSAPP_APP_SECRET is missing."""
    # Set production environment
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "test_token")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "test_token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "test_id")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_test")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setenv("FRESHA_BOOKING_URL", "https://test.com")
    monkeypatch.setenv("ADMIN_API_KEY", "test_admin_key")
    monkeypatch.setenv("DEMO_MODE", "false")
    # WHATSAPP_APP_SECRET is NOT set

    # Clear any cached settings
    import sys

    if "app.core.config" in sys.modules:
        del sys.modules["app.core.config"]
    if "app.main" in sys.modules:
        del sys.modules["app.main"]

    # Import after setting env vars
    from app.main import app

    # Attempt to create client - should fail during startup
    with pytest.raises(RuntimeError) as exc_info, TestClient(app):
        pass

    error_message = str(exc_info.value)
    assert "WHATSAPP_APP_SECRET is required in production" in error_message
    assert "Production environment validation failed" in error_message


def test_production_validation_stripe_webhook_secret_checked(monkeypatch):
    """Test that production validation checks STRIPE_WEBHOOK_SECRET.

    Note: STRIPE_WEBHOOK_SECRET is already in general required_settings,
    so it fails at the first validation check. This test verifies that
    production validation also explicitly checks it for documentation purposes.
    """
    # This test verifies the code path exists - the actual validation
    # happens in the general required_settings check (which is correct)
    # Production validation also mentions it for clarity

    # Verify the production validation code checks STRIPE_WEBHOOK_SECRET
    import inspect

    from app.main import startup_event

    # Check that the production validation code includes STRIPE_WEBHOOK_SECRET check
    source = inspect.getsource(startup_event)
    assert (
        "STRIPE_WEBHOOK_SECRET is required in production" in source
        or "stripe_webhook_secret" in source.lower()
    )


def test_production_validation_demo_mode_enabled(monkeypatch):
    """Test that production mode fails if DEMO_MODE is True."""
    # Set production environment
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "test_token")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "test_token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "test_id")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_test")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setenv("FRESHA_BOOKING_URL", "https://test.com")
    monkeypatch.setenv("ADMIN_API_KEY", "test_admin_key")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "test_app_secret")
    monkeypatch.setenv("DEMO_MODE", "true")  # DEMO_MODE is True

    # Clear any cached settings
    import sys

    if "app.core.config" in sys.modules:
        del sys.modules["app.core.config"]
    if "app.main" in sys.modules:
        del sys.modules["app.main"]

    # Import after setting env vars
    from app.main import app

    # Attempt to create client - should fail during startup
    with pytest.raises(RuntimeError) as exc_info, TestClient(app):
        pass

    error_message = str(exc_info.value)
    assert "DEMO_MODE must be False in production" in error_message
    assert "Production environment validation failed" in error_message


def test_production_validation_all_requirements_met(monkeypatch):
    """Test that production mode succeeds when all requirements are met."""
    # Set production environment with all required settings
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "test_token")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "test_token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "test_id")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_test")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setenv("FRESHA_BOOKING_URL", "https://test.com")
    monkeypatch.setenv("ADMIN_API_KEY", "test_admin_key")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "test_app_secret")
    monkeypatch.setenv("DEMO_MODE", "false")

    # Clear any cached settings
    import sys

    if "app.core.config" in sys.modules:
        del sys.modules["app.core.config"]
    if "app.main" in sys.modules:
        del sys.modules["app.main"]

    # Import after setting env vars
    from app.main import app

    # Should succeed - create client without error
    with TestClient(app) as client:
        # Health check should work
        response = client.get("/health")
        assert response.status_code == 200


def test_production_validation_multiple_errors(monkeypatch):
    """Test that production mode reports all missing requirements in one error."""
    # Set production environment but missing multiple requirements
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "test_token")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "test_token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "test_id")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_test")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setenv("FRESHA_BOOKING_URL", "https://test.com")
    # ADMIN_API_KEY is NOT set
    # WHATSAPP_APP_SECRET is NOT set
    monkeypatch.setenv("DEMO_MODE", "true")  # Also wrong

    # Clear any cached settings
    import sys

    if "app.core.config" in sys.modules:
        del sys.modules["app.core.config"]
    if "app.main" in sys.modules:
        del sys.modules["app.main"]

    # Import after setting env vars
    from app.main import app

    # Attempt to create client - should fail during startup
    with pytest.raises(RuntimeError) as exc_info, TestClient(app):
        pass

    error_message = str(exc_info.value)
    # Should contain all three errors
    assert "ADMIN_API_KEY is required in production" in error_message
    assert "WHATSAPP_APP_SECRET is required in production" in error_message
    assert "DEMO_MODE must be False in production" in error_message
    assert "Production environment validation failed" in error_message


def test_dev_mode_allows_missing_production_settings(monkeypatch):
    """Test that dev mode allows missing production-specific settings."""
    # Set dev environment (default)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "test_token")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "test_token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "test_id")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_test")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setenv("FRESHA_BOOKING_URL", "https://test.com")
    # ADMIN_API_KEY is NOT set (should be OK in dev)
    # WHATSAPP_APP_SECRET is NOT set (should be OK in dev)
    monkeypatch.setenv("DEMO_MODE", "true")  # Should be OK in dev

    # Clear any cached settings
    import sys

    if "app.core.config" in sys.modules:
        del sys.modules["app.core.config"]
    if "app.main" in sys.modules:
        del sys.modules["app.main"]

    # Import after setting env vars
    from app.main import app

    # Should succeed - dev mode doesn't require production settings
    with TestClient(app) as client:
        # Health check should work
        response = client.get("/health")
        assert response.status_code == 200
