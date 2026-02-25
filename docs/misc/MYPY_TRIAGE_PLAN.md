# Mypy Triage Plan

**Current state:** 265 errors in 28 files (as of triage date)

---

## 1. Error Buckets

| Bucket | Count (approx) | Examples |
|--------|----------------|----------|
| **Missing type stubs** | 4 | `yaml` (tone, calendar_rules, message_composer), `pytz` (calendar_rules) |
| **Any / no-any-return** | ~25 | tone:140, calendar_rules, message_composer, sheets, rate_limit, stripe_service, outbox_service |
| **SQLAlchemy DateTime / func.now()** | ~80 | `DateTime` has no `isoformat`/`replace`/`tzinfo`; `func.now()` assignment to `SQLCoreOperations`; `Lead.xxx` where column is `Mapped[datetime]`. Conversation split modules (`conversation`, `conversation_booking`, `conversation_qualifying`) and `state_machine` are in the per-module `disable_error_code = ["assignment"]` override in pyproject.toml. |
| **Lead \| None union-attr** | ~40 | `lead.status`, `lead.id` etc. after `db.get(Lead, id)` without null check |
| **Pydantic Settings** | 7 | config.py:100 – `Settings()` call-arg (loads from env) |
| **Other** | ~15 | template_registry:79 `any` vs `Any`; message_composer dict\|None; safety Select vs Update; whatsapp_window Collection.pop; admin Literal arg |

---

## 2. Minimal Config Changes (reduce noise, no hiding real issues)

### A. Add type stubs

- Add `types-pytz` to `requirements-dev.txt` (PyYAML stubs already present).

### B. Add `ignore_missing_imports` for stub-less modules

```toml
[[tool.mypy.overrides]]
module = ["yaml", "pytz"]
ignore_missing_imports = true
```

(Keeps existing overrides for google, stripe, alembic.)

### C. Add SQLAlchemy plugin

```toml
[tool.mypy]
plugins = ["sqlalchemy.ext.mypy.plugin"]
```

Helps with `Mapped`, `func.now()`, and related column types. Some `DateTime`/`func.now()` issues may persist.

### D. Pydantic Settings (config.py)

Use a single targeted ignore:

```python
settings = Settings()  # type: ignore[call-arg]
```

Pydantic loads from env; mypy doesn’t model that, so a narrow ignore is appropriate.

---

## 3. Recommended: `continue-on-error: true` for mypy

**Recommendation:** Temporarily set `continue-on-error: true` for the mypy step in `quality.yml`.

**Rationale:**
- 265 errors is too large to fix in one pass.
- Quality is advisory-only, so failing every PR is noisy.
- Bandit and pip-audit still run; mypy output remains visible in the logs.
- Keeps PRs mergeable while following the roadmap below.

Add a TODO and tracking reference in the workflow.

---

## 4. quality.yml Diff

```diff
      - name: Run mypy
-        run: mypy app --ignore-missing-imports
+        # TODO: Remove continue-on-error once mypy errors are fixed (track: docs/misc/MYPY_TRIAGE_PLAN.md)
+        run: mypy app --ignore-missing-imports
+        continue-on-error: true
```

---

## 5. pyproject.toml Mypy Diff

```diff
 [tool.mypy]
 python_version = "3.11"
+plugins = ["sqlalchemy.ext.mypy.plugin"]
 warn_return_any = true
 ...

 [[tool.mypy.overrides]]
 module = [
     "google.*",
     "stripe.*",
     "alembic.*",
+    "yaml",
+    "pytz",
 ]
 ignore_missing_imports = true
```

**requirements-dev.txt:**
```diff
 types-pyyaml>=6.0.12
 types-python-dateutil>=2.8.19
+types-pytz>=2024.1.0
```

---

## 6. Top 10 Mypy Errors and Quick Fixes

| # | Error | Location | Quick fix |
|---|-------|----------|-----------|
| 1 | `dict[str, any]` – `any` invalid | template_registry.py:79 | Change to `dict[str, Any]` (capital A) |
| 2 | `Settings()` call-arg | config.py:100 | Add `# type: ignore[call-arg]` |
| 3 | `"DateTime" has no attribute "isoformat"` | handover_packet, admin, webhooks, etc. | Wrap: `(dt.isoformat() if dt else "")` or `getattr(dt, "isoformat", lambda: "")().` Safer: `dt.isoformat() if hasattr(dt, "isoformat") and dt else ""` |
| 4 | `"DateTime" has no attribute "replace"` | action_tokens, whatsapp_window, webhooks | Cast: `from datetime import datetime`; `dt = dt.replace(...) if isinstance(dt, datetime) else dt` or `# type: ignore[attr-defined]` |
| 5 | `func.now()` assignment incompatible | state_machine, admin, actions, etc. | SQLAlchemy plugin should help; else `# type: ignore[assignment]` per line |
| 6 | `Item "None" of "Lead \| None" has no attribute "status"` | admin, webhooks, demo | Add `if lead is None: raise HTTPException(404)` before use |
| 7 | `Argument 2 to "log_lead_to_sheets" has incompatible type "Lead \| None"` | admin.py | Add null check before calling |
| 8 | `Value of type "dict[str, Any] \| None" is not indexable` | message_composer.py:83 | `if d is None: return default` or `d or {}` |
| 9 | `"Collection[str]" has no attribute "pop"` | whatsapp_window.py:380 | Use `list(x)` if a mutable sequence is required |
| 10 | `Returning Any from function declared to return "str"` | tone, message_composer, etc. | Add explicit cast: `return str(x)` or `cast(str, x)` |

---

## 7. Mypy Cleanup Roadmap (step-by-step commits)

1. **config + stub + plugin**
   - Add `types-pytz` to requirements-dev.
   - Add `yaml`, `pytz` mypy overrides.
   - Add SQLAlchemy plugin.
   - Add `# type: ignore[call-arg]` to `Settings()`.

2. **template_registry typo**
   - Change `dict[str, any]` → `dict[str, Any]`.

3. **message_composer null checks**
   - Add `if d is None` / `d or {}` before indexing.

4. **admin / webhooks Lead\|None**
   - Add `if lead is None: raise HTTPException(404)` after `db.get()` in admin and webhooks.

5. **DateTime isoformat / replace**
   - Add helper: `def _to_iso(dt) -> str: return dt.isoformat() if dt and hasattr(dt, "isoformat") else ""` and use it where appropriate.

6. **no-any-return (high-impact)**
   - Add `cast()` or explicit `str(x)` where functions return `str` but implementation returns `Any`.

7. **func.now() assignments**
   - Add `# type: ignore[assignment]` per line or rely on SQLAlchemy plugin if it fixes them.

8. **safety.py Select vs Update**
   - Fix variable reuse; ensure each variable has a single, consistent type.

9. **whatsapp_window Collection.pop**
   - Replace with a pattern that works on `Collection` (e.g. convert to list and pop, or use a different data structure).

10. **Reduce ignores**
    - Re-run mypy; remove `continue-on-error` when error count is acceptable (e.g. &lt; 20).

---

## 8. Sanity Check After Config Changes

```bash
mypy app --ignore-missing-imports
```

Compare error count before vs after plugin + overrides.
