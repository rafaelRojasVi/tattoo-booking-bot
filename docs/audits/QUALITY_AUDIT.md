# Code Quality Audit Report

**Date:** 2026-01-18  
**Auditor:** Senior Backend Engineer  
**Scope:** Full codebase quality, security, maintainability, and reproducibility audit

## Executive Summary

This audit was conducted on a "vibe-coded" codebase that has passing tests but requires production hardening. The audit identified **P0 (critical)**, **P1 (high)**, and **P2 (medium/low)** issues across code quality, type safety, security, and operational correctness.

**Key Findings:**
- ✅ **No known dependency vulnerabilities** (pip-audit clean)
- ⚠️ **2 low-severity security findings** (false positives in test mode)
- 🔴 **P0: Config instantiation type safety** - could fail silently in production
- 🟡 **P1: Type annotation gaps** - 40+ mypy errors, mostly fixable
- 🟡 **P1: Import organization** - 100+ ruff style issues (auto-fixable)
- 🟢 **P2: Code formatting** - whitespace, import sorting (auto-fixable)

---

## P0 - Critical Issues (Must Fix Before Production)

### P0-1: Config Instantiation Without Required Fields
**File:** `app/core/config.py:57`  
**Issue:** `Settings()` instantiation without required fields could fail at runtime  
**Risk:** Application startup failure in production if env vars missing  
**Current Code:**
```python
settings = Settings()  # Missing required fields: database_url, whatsapp_verify_token, etc.
```
**Fix:** Add validation or make fields optional with defaults, or use `Settings()` only after env validation  
**Recommendation:** Add `model_config` with `validate_assignment=True` and fail-fast validation on startup

---

### P0-2: Webhook Exception Handling - Potential Data Loss
**File:** `app/api/webhooks.py:43, 134, 246`  
**Issue:** Broad `except Exception` catches all errors, may mask idempotency issues  
**Risk:** Duplicate processing, lost webhooks, inconsistent state  
**Current Pattern:**
```python
try:
    # webhook processing
except Exception:
    # returns error but doesn't log context
```
**Fix:** 
- Use specific exception types
- Ensure idempotency checks happen before processing
- Log full context (lead_id, event_id, error) for debugging
- Add retry logic for transient failures

**Recommendation:** Add structured logging with correlation IDs

---

### P0-3: DB Session Lifecycle - Audit Required (Not Critical)
**File:** `app/db/deps.py:4-9`  
**Issue:** Generator-based session management is standard FastAPI pattern and looks correct  
**Risk:** Low - only real risk is if endpoints bypass `Depends(get_db)`  
**Current Code:**
```python
def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```
**Fix:** Quick audit to ensure all endpoints use `Depends(get_db)` consistently  
**Recommendation:** Add connection pool monitoring for production observability (not blocking)

---

## P1 - High Priority Issues (Fix Soon)

### P1-1: Type Annotation Gaps (40+ mypy errors)
**Files:** Multiple  
**Issues:**
- `app/services/metrics.py:97` - Using `any` instead of `typing.Any`
- `app/services/sheets.py:187-206` - DateTime type issues (SQLAlchemy DateTime vs Python datetime)
- `app/services/tour_service.py:115` - Implicit Optional in function signature
- `app/core/config.py:57` - Missing required field validation
- `app/services/summary.py:45` - Type mismatch in dict.get() calls

**Risk:** Runtime type errors, harder refactoring, IDE support degradation  
**Fix:** Add type stubs, fix return types, use `Optional[X]` explicitly  
**Recommendation:** Fix incrementally, starting with critical paths (webhooks, admin actions)

---

### P1-2: Import Organization (100+ ruff I001 errors)
**Files:** `app/api/actions.py`, `app/api/admin.py`, others  
**Issue:** Unsorted imports, imports not at top level (lazy imports)  
**Risk:** Code readability, potential circular import issues  
**Current Pattern:**
```python
# Imports scattered, some lazy-loaded inside functions
from app.services.x import y
import logging
from fastapi import ...
```
**Fix:** Run `ruff check --fix` to auto-sort, move lazy imports to top with comments  
**Recommendation:** Use `# noqa: PLC0415` for intentional lazy imports (e.g., avoiding circular deps)

---

### P1-3: FastAPI Depends Pattern (B008 warnings) - Tool Noise
**Files:** `app/api/actions.py:47,136`, `app/api/admin.py:49,67,86,101,171,214,341,389`  
**Issue:** `Depends(get_db)` in function defaults triggers ruff B008  
**Risk:** None - this is FastAPI's intended pattern  
**Fix:** Configure ruff to ignore B008 for FastAPI dependency injection patterns  
**Recommendation:** Add to `pyproject.toml`: `[tool.ruff.lint.per-file-ignores]` for `app/api/*.py` with `B008`

---

### P1-4: DateTime Type Confusion
**Files:** `app/services/sheets.py:187-206`, `app/services/action_tokens.py:101`  
**Issue:** SQLAlchemy `DateTime` vs Python `datetime.datetime` type confusion  
**Risk:** Runtime errors when calling `.isoformat()` or `.tzinfo` on SQLAlchemy types  
**Current Code:**
```python
if lead.deposit_paid_at:
    row["deposit_paid_at"] = lead.deposit_paid_at.isoformat()  # mypy error
```
**Fix:** Cast to `datetime.datetime` or use SQLAlchemy's type helpers  
**Recommendation:** Use `from sqlalchemy import DateTime as SA_DateTime` and type: ignore comments, or convert explicitly

---

### P1-5: Unused Imports
**File:** `app/api/admin.py:28`  
**Issue:** `AdminActionResponse` imported but unused  
**Risk:** Code bloat, confusion  
**Fix:** Remove unused import  
**Recommendation:** Run `ruff check --fix` to auto-remove

---

### P1-6: Missing Type Stubs
**Files:** `app/services/tone.py:8`, `app/services/calendar_rules.py:5,10`  
**Issue:** Missing type stubs for `yaml`, `pytz`  
**Risk:** mypy can't type-check these imports  
**Fix:** Add `types-pyyaml`, `types-pytz` to requirements-dev.txt (already added)  
**Recommendation:** Install stubs and re-run mypy

---

## P2 - Medium/Low Priority (Nice to Have)

### P2-1: Code Formatting (100+ W293 whitespace errors)
**Files:** Multiple  
**Issue:** Blank lines contain whitespace  
**Risk:** Git diff noise, inconsistent formatting  
**Fix:** Run `ruff format` to auto-fix  
**Recommendation:** Add pre-commit hook (already configured)

---

### P2-2: Type Annotation Modernization (UP045)
**File:** `app/api/admin.py:213`  
**Issue:** Using `Optional[X]` instead of `X | None`  
**Risk:** None - stylistic  
**Fix:** Run `ruff check --fix --select UP` to auto-upgrade  
**Recommendation:** Modernize incrementally

---

### P2-3: Function Complexity (PLR0911, PLR0915)
**File:** `app/api/actions.py:134`  
**Issue:** Too many return statements (7 > 6), too many statements (63 > 50)  
**Risk:** Harder to test, maintain  
**Fix:** Refactor into smaller functions (low priority, business logic is complex)  
**Recommendation:** Document complexity, add unit tests for each branch

---

## Security Findings

### S-1: Hardcoded Test Credentials (False Positive)
**File:** `app/services/stripe_service.py:48, 113`  
**Issue:** Bandit flags `"sk_test_test"` and `"whsec_test"` as hardcoded passwords  
**Severity:** Low (false positive)  
**Risk:** None - these are explicit test mode checks  
**Fix:** Add `# nosec B105` comments or configure bandit to ignore test mode checks  
**Recommendation:** Keep as-is, add nosec comments for clarity

---

## Operational Correctness

### O-1: Timezone Handling - Mixed Patterns
**Files:** `app/services/calendar_service.py:71,84`, `app/services/calendar_rules.py:87`  
**Issue:** Some code uses `timezone.utc`, some uses `Europe/London`  
**Risk:** Timezone bugs in production (DST transitions, booking times)  
**Current Pattern:**
```python
datetime.now(timezone.utc)  # UTC
# vs
rules.get("timezone", "Europe/London")  # Local timezone
```
**Fix:** Standardize on UTC for storage, convert to local only for display  
**Recommendation:** Document timezone strategy, add timezone conversion helpers

---

### O-2: Logging - No Secret Leakage Found ✅
**Audit:** Grepped for password/secret/token in f-strings  
**Result:** No secrets logged in f-strings  
**Recommendation:** Continue using structured logging, avoid logging request bodies in webhooks

---

### O-3: Feature Flag Checks - Inconsistent
**Files:** Multiple service files  
**Issue:** Some services check feature flags, some don't  
**Risk:** Features may run when disabled if flag check missing  
**Fix:** Audit all external integration entrypoints, ensure flags checked  
**Recommendation:** Add integration test that disables all flags and verifies no external calls

---

## Reproducibility Issues

### R-1: Unpinned Dependencies
**File:** `requirements.txt`  
**Issue:** All dependencies unpinned (no version constraints)  
**Risk:** Non-reproducible builds, breaking changes in minor updates  
**Fix:** Pin major versions at minimum, or use `requirements.txt` with `pip-compile`  
**Recommendation:** 
- Pin production deps: `fastapi==0.128.0`, `sqlalchemy==2.0.45`, etc.
- Use `~=` for patch-level updates: `fastapi~=0.128.0`
- Document upgrade process

---

### R-2: Docker Build - No Version Pinning
**File:** `Dockerfile:1`  
**Issue:** `FROM python:3.11-slim` uses `latest` tag implicitly  
**Risk:** Non-deterministic builds  
**Fix:** Pin to specific digest or version: `FROM python:3.11.14-slim`  
**Recommendation:** Use SHA256 digest for maximum reproducibility

---

### R-3: Environment Variable Validation
**File:** `app/core/config.py`  
**Issue:** Missing fields fail at runtime, not startup  
**Risk:** Application starts but fails on first request  
**Fix:** Add startup validation in `main.py` startup event  
**Recommendation:** Fail fast with clear error messages

---

## Recommendations Summary

### Immediate Actions (Before Production)
1. ✅ **Auto-fix formatting/imports**: `ruff format . && ruff check --fix .` (safe, big win)
2. ✅ **Config validation**: Fail-fast startup with clear error messages (P0-1)
3. ✅ **Webhook exception handling**: Structured logging, idempotency-first, no secret leakage (P0-2)
4. ✅ **Reproducibility**: Pin Docker base image + dependency lock strategy (R-1, R-2)
5. ⚠️ **Test collection errors**: Fix type annotations in tests (blocking test runs)

### Short-term (Next Sprint)
1. Fix critical type annotations incrementally (config, webhooks, action tokens, stripe) (P1-1)
2. Standardize timezone handling - UTC storage, local display (O-1)
3. Add feature flag "no external calls" test (O-3)
4. Mypy incremental pass on hot paths only

### Long-term (Technical Debt)
1. Refactor complex functions (P2-3)
2. Modernize type annotations (P2-2)
3. Add comprehensive integration tests

---

## Quality Gate Status

| Check | Status | Notes |
|-------|--------|-------|
| Ruff lint | ❌ 100+ issues | Auto-fixable |
| Ruff format | ❌ Formatting issues | Auto-fixable |
| Mypy | ❌ 40+ errors | Need type fixes (incremental) |
| Bandit | ⚠️ 2 low (false positives) | Add nosec comments |
| Pip-audit | ✅ Clean | No vulnerabilities |
| Pytest | ⚠️ Collection errors | Fix type annotations in tests first |

---

## Next Steps (Prioritized)

### Step 1: Auto-fix formatting (safe, no behavior change)
```bash
ruff format .
ruff check --fix .
```

### Step 2: Fix config validation (biggest real risk)
- Fail-fast startup validation in `app/main.py`
- Clear error messages listing missing env vars
- Test missing env vars cause startup failure

### Step 3: Harden webhook exception handling
- Idempotency checks before side effects
- Structured logging (event_id, lead_id, no secrets)
- Explicit exception types where possible
- Tests for invalid signature, duplicate events, unexpected errors

### Step 4: Reproducibility pins
- Pin Docker base: `python:3.11.<patch>-slim` or digest
- Introduce `pip-tools` for dependency locking
- Document upgrade process

### Step 5: Mypy incremental (after core fixes)
- Fix hot paths only: config, webhooks, action tokens, stripe
- Use TypedDicts for context objects
- Targeted `# type: ignore[<code>]` only when needed
