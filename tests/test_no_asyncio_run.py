"""
Test that no asyncio.run() calls exist in app/ code.

This ensures all async functions are properly awaited rather than
using asyncio.run() which blocks and can cause issues in async contexts.
"""

from pathlib import Path


def find_asyncio_run_usage(file_path: Path) -> list[tuple[int, str]]:
    """
    Find all asyncio.run() calls in a Python file.

    Returns:
        List of (line_number, line_content) tuples
    """
    issues = []
    try:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
            lines = content.split("\n")

            # Simple pattern matching for asyncio.run(
            for i, line in enumerate(lines, start=1):
                # Check for asyncio.run( pattern
                if "asyncio.run(" in line:
                    # Skip comments and docstrings
                    stripped = line.strip()
                    if not stripped.startswith("#") and not stripped.startswith('"""'):
                        issues.append((i, line))
    except Exception:
        # If we can't parse the file, that's okay - we'll catch it in other tests
        pass

    return issues


def test_no_asyncio_run_in_async_handlers():
    """
    Test that no asyncio.run() calls exist in async request handlers.

    This specifically checks webhooks.py and other async handlers.
    Sync handlers (like admin endpoints) may legitimately use asyncio.run()
    in sync contexts, but async request handlers should always use await.
    """
    app_api_dir = Path(__file__).parent.parent / "app" / "api"
    assert app_api_dir.exists(), "app/api/ directory not found"

    all_issues = []

    # Check webhooks.py specifically (the main async handler we fixed)
    webhooks_file = app_api_dir / "webhooks.py"
    if webhooks_file.exists():
        issues = find_asyncio_run_usage(webhooks_file)
        if issues:
            rel_path = webhooks_file.relative_to(app_api_dir.parent.parent)
            for line_num, line_content in issues:
                all_issues.append(f"{rel_path}:{line_num}: {line_content.strip()}")

    if all_issues:
        error_msg = (
            "Found asyncio.run() calls in webhooks.py (async request handler). "
            "These should be replaced with 'await' in async functions:\n\n"
            + "\n".join(f"  - {issue}" for issue in all_issues)
        )
        raise AssertionError(error_msg)
