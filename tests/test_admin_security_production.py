"""
Tests for admin security in production environment.
"""
import pytest
from unittest.mock import patch
from fastapi import HTTPException
from app.api.auth import get_admin_auth


def test_production_requires_admin_key():
    """Test that production environment requires admin_api_key."""
    with patch("app.api.auth.settings") as mock_settings:
        mock_settings.app_env = "production"
        mock_settings.admin_api_key = None
        
        # Should raise RuntimeError
        with pytest.raises(RuntimeError, match="ADMIN_API_KEY must be set in production"):
            get_admin_auth(api_key=None)


def test_production_with_admin_key_works():
    """Test that production with admin_api_key works."""
    with patch("app.api.auth.settings") as mock_settings:
        mock_settings.app_env = "production"
        mock_settings.admin_api_key = "test-key-123"
        
        # Should work with correct key
        result = get_admin_auth(api_key="test-key-123")
        assert result is True
        
        # Should fail with wrong key
        with pytest.raises(HTTPException) as exc_info:
            get_admin_auth(api_key="wrong-key")
        assert exc_info.value.status_code == 403


def test_dev_mode_allows_no_key():
    """Test that dev mode allows access without admin_api_key."""
    with patch("app.api.auth.settings") as mock_settings:
        mock_settings.app_env = "dev"
        mock_settings.admin_api_key = None
        
        # Should allow access
        result = get_admin_auth(api_key=None)
        assert result is True


def test_dev_mode_with_key_still_requires_key():
    """Test that dev mode with key set still requires correct key."""
    with patch("app.api.auth.settings") as mock_settings:
        mock_settings.app_env = "dev"
        mock_settings.admin_api_key = "dev-key"
        
        # Should work with correct key
        result = get_admin_auth(api_key="dev-key")
        assert result is True
        
        # Should fail with wrong key
        with pytest.raises(HTTPException) as exc_info:
            get_admin_auth(api_key="wrong-key")
        assert exc_info.value.status_code == 403
