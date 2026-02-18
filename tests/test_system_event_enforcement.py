"""
Enforce that SystemEvent is only instantiated via the log_event helper.

SystemEvent(...) must only appear in:
- app/db/models.py (model definition)
- app/services/system_event_service.py (the single creation path)

All other code must use log_event, info, warn, or error from system_event_service.
"""

from pathlib import Path

import pytest

# Files allowed to contain SystemEvent( instantiation
ALLOWED_FILES = {
    "app/db/models.py",
    "app/services/system_event_service.py",
}


def _collect_violations() -> list[tuple[str, int, str]]:
    """Return list of (filepath, line_no, line) for disallowed SystemEvent( usage."""
    root = Path(__file__).resolve().parent.parent
    violations = []
    for py_path in root.rglob("*.py"):
        rel = py_path.relative_to(root)
        rel_str = str(rel).replace("\\", "/")
        if rel_str in ALLOWED_FILES:
            continue
        if "test_" in rel_str and "test_system_event" in rel_str:
            # test_system_event_enforcement.py itself may reference SystemEvent in docstring
            continue
        try:
            text = py_path.read_text(encoding="utf-8")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            code_part = line.split("#")[0]
            if "SystemEvent(" not in code_part:
                continue
            # Exclude comments
            if line.strip().startswith("#"):
                continue
            # Exclude imports and type hints
            stripped = line.strip()
            if stripped.startswith("from ") or stripped.startswith("import "):
                continue
            if "SystemEvent" in line and ":" in line and "SystemEvent" in line.split(":")[0]:
                continue
            violations.append((rel_str, i, line.strip()))
    return violations


def test_no_direct_system_event_creation_outside_allowlist():
    """
    Fail if SystemEvent(...) is used outside app/db/models.py and app/services/system_event_service.py.

    All event logging must go through log_event/info/warn/error to ensure consistent payload shape.
    """
    violations = _collect_violations()
    if violations:
        msg_lines = [
            "SystemEvent(...) must only be used in app/db/models.py and app/services/system_event_service.py.",
            "Use log_event, info, warn, or error from app.services.system_event_service instead.",
            "",
            "Violations:",
        ]
        for path, line_no, line in violations:
            msg_lines.append(f"  {path}:{line_no}: {line[:80]}")
        pytest.fail("\n".join(msg_lines))
