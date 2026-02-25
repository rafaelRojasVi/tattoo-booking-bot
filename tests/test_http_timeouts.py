"""
Test that all httpx.AsyncClient instances use explicit timeouts.

This ensures external HTTP calls don't block workers indefinitely.
"""

from pathlib import Path

import httpx

from app.services.integrations.http_client import create_httpx_client, get_httpx_timeout


def test_http_client_helper_returns_timeout():
    """Test that get_httpx_timeout() returns a proper timeout object."""
    timeout = get_httpx_timeout()
    assert isinstance(timeout, httpx.Timeout)
    # httpx.Timeout stores default timeout in connect/read/write/pool, check connect as proxy
    assert timeout.connect == 5.0
    assert timeout.read == 10.0
    assert timeout.write == 5.0
    assert timeout.pool == 5.0


def test_create_httpx_client_uses_timeout():
    """Test that create_httpx_client() creates a client with timeout."""
    client = create_httpx_client()
    assert isinstance(client, httpx.AsyncClient)
    assert client.timeout is not None
    assert isinstance(client.timeout, httpx.Timeout)


def test_messaging_uses_timeout(monkeypatch):
    """Test that messaging.py uses the timeout helper."""

    # Mock httpx.AsyncClient to capture timeout
    captured_timeout = None

    original_init = httpx.AsyncClient.__init__

    def mock_init(self, *args, **kwargs):
        nonlocal captured_timeout
        captured_timeout = kwargs.get("timeout")
        return original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", mock_init)

    # Import and call the function (it will use create_httpx_client)
    # We need to actually trigger the code path, but in dry-run mode it won't create a client
    # So we'll check the source code instead

    # Read the source file
    messaging_file = (
        Path(__file__).parent.parent / "app" / "services" / "messaging" / "messaging.py"
    )
    content = messaging_file.read_text()

    # Check that it imports or uses the helper
    assert "create_httpx_client" in content or "http_client" in content, (
        "messaging.py should use create_httpx_client() or import from http_client"
    )


def test_whatsapp_window_uses_timeout():
    """Test that whatsapp_window.py uses the timeout helper."""
    # Read the source file with explicit encoding
    window_file = (
        Path(__file__).parent.parent / "app" / "services" / "messaging" / "whatsapp_window.py"
    )
    content = window_file.read_text(encoding="utf-8")

    # Check that it imports or uses the helper
    assert "create_httpx_client" in content or "http_client" in content, (
        "whatsapp_window.py should use create_httpx_client() or import from http_client"
    )


def test_no_direct_httpx_client_creation_in_app():
    """Test that app/ code doesn't create httpx.AsyncClient() without timeout."""
    app_dir = Path(__file__).parent.parent / "app"
    assert app_dir.exists(), "app/ directory not found"

    issues = []

    # Walk through all Python files in app/
    for py_file in app_dir.rglob("*.py"):
        # Skip __pycache__ and .pyc files
        if "__pycache__" in str(py_file):
            continue

        # Skip test files
        if "test" in py_file.name.lower():
            continue

        try:
            content = py_file.read_text(encoding="utf-8")
            lines = content.split("\n")

            for i, line in enumerate(lines, start=1):
                # Look for httpx.AsyncClient() without timeout parameter
                if "httpx.AsyncClient(" in line:
                    # Check if timeout is mentioned in this line or nearby
                    stripped = line.strip()
                    if not stripped.startswith("#"):
                        # Check if timeout is in this line
                        if "timeout" not in line.lower():
                            # Check next few lines for timeout (could be multi-line)
                            context_lines = "\n".join(lines[max(0, i - 2) : min(len(lines), i + 3)])
                            if "timeout" not in context_lines.lower():
                                # But allow if it's using create_httpx_client
                                if "create_httpx_client" not in context_lines:
                                    rel_path = py_file.relative_to(app_dir.parent)
                                    issues.append(f"{rel_path}:{i}: {line.strip()}")
        except Exception:
            # Skip files we can't read
            pass

    if issues:
        error_msg = (
            "Found httpx.AsyncClient() calls without explicit timeout. "
            "Use create_httpx_client() from app.services.integrations.http_client instead:\n\n"
            + "\n".join(f"  - {issue}" for issue in issues)
        )
        raise AssertionError(error_msg)
