# Multi-artist prep report

Minimal, safe changes to break import cycles and add an artist config seam. No behavior change for existing single-artist flows.

---

## Part 1 — Cycles removed

### 1A — Conversation cycle (conversation ↔ booking/qualifying)

- **Before:** `conversation.py` imported `conversation_booking` and `conversation_qualifying`; both imported `conversation` (for `send_whatsapp_message`), creating a cycle.
- **Change:** Added **`app/services/conversation_deps.py`** with a single late-bound getter:
  - `get_send_whatsapp_message()` → returns the send callable (imports from `conversation` at call time).
- **Updated:** `conversation_booking.py` and `conversation_qualifying.py` now use `conversation_deps.get_send_whatsapp_message()` instead of importing `conversation` directly.
- **Tests:** Patches on `app.services.conversation.send_whatsapp_message` still work (getter resolves at call time). One test that patched `_get_send_whatsapp` now patches `app.services.conversation_deps.get_send_whatsapp_message`.

### 1B — Template cycle (template_check ↔ template_registry)

- **Before:** `template_check` imported `template_registry`; `template_registry.validate_template_registry()` imported `template_check.REQUIRED_TEMPLATES`.
- **Change:** Added **`app/services/template_core.py`** with shared data only:
  - `MessageType` enum, `TEMPLATE_REGISTRY`, `get_all_required_templates()`, `get_required_templates_app()` (registry + `test_template`).
- **Updated:**
  - `template_registry.py` imports from `template_core` only; `validate_template_registry()` no longer imports `template_check`.
  - `template_check.py` imports `REQUIRED_TEMPLATES` from `template_core` via `get_required_templates_app()` and still uses `template_registry.validate_template_registry()`.

**Why it matters for scale:** Cycles make it harder to add per-artist or per-module overrides, run modules in isolation, and reason about startup order. Breaking them keeps the conversation and template layers acyclic so multi-artist or plugin-style config can be added without tangling imports.

---

## Part 2 — Import guard test

- **Added:** `tests/test_import_cycles.py`
- **Asserts:** Imports succeed (no `ImportError`) for:
  - `app.main`, `app.api.webhooks`, `app.services.conversation`, `app.services.conversation_booking`, `app.services.conversation_qualifying`, `app.services.template_registry`, `app.services.template_check`.

---

## Part 3 — Minimal artist config seam (no behavior change)

- **Lead model:** New column **`artist_id`** (String(64), default `"default"`, nullable=False).
  - **Migration:** `migrations/versions/add_artist_id_to_leads.py` — adds column, backfills existing rows with `'default'`, then sets NOT NULL + server default.
- **New service:** **`app/services/artist_config.py`**
  - `get_artist_config(artist_id: str) -> dict` — returns a static default config (no new external calls).
  - Shape: `artist_id`, `timezone` (e.g. `"Europe/London"`), `min_spend_pence` (None). Extensible later.
- **Usage:** No critical wiring yet; business rules (e.g. conversation_qualifying) still use existing services (e.g. region_service for min budget). One optional next step: have qualifying/booking read `get_artist_config(lead.artist_id)` for timezone or min_spend when you introduce per-artist overrides.
- **Tests:** `tests/test_artist_config.py`
  - `get_artist_config("default")` returns the expected shape.
  - Empty string falls back to default artist id.
  - New lead (no `artist_id` set) has `artist_id == "default"` (model default).

---

## Files touched

| File | Change |
|------|--------|
| `app/services/conversation_deps.py` | **New** — getter for send_whatsapp_message |
| `app/services/conversation_booking.py` | Use conversation_deps.get_send_whatsapp_message |
| `app/services/conversation_qualifying.py` | Use conversation_deps.get_send_whatsapp_message |
| `app/services/template_core.py` | **New** — MessageType, TEMPLATE_REGISTRY, get_all_required_templates, get_required_templates_app |
| `app/services/template_registry.py` | Import from template_core only; validate no longer imports template_check |
| `app/services/template_check.py` | Import REQUIRED_TEMPLATES from template_core |
| `tests/test_import_cycles.py` | **New** — import guard tests |
| `tests/test_production_hardening.py` | Patch conversation_deps.get_send_whatsapp_message |
| `app/db/models.py` | Add artist_id column (default "default") |
| `app/services/artist_config.py` | **New** — get_artist_config(artist_id) |
| `migrations/versions/add_artist_id_to_leads.py` | **New** — add and backfill artist_id |
| `tests/test_artist_config.py` | **New** — artist config and default artist_id tests |

---

## Command outputs

### pytest -q

```
====================== 1034 passed, 2 skipped in 15.55s =======================
```

### ruff format . && ruff check .

```
198 files left unchanged
All checks passed!
```

### mypy app scripts

```
(exit 0; known ORM/DateTime noise not addressed)
```

---

## Summary

- **Cycles removed:** conversation ↔ booking/qualifying (via conversation_deps); template_check ↔ template_registry (via template_core).
- **Scale:** Acyclic conversation and template layers; clear seam for per-artist config.
- **Multi-artist seam:** `artist_id` on Lead (default `"default"`), `get_artist_config(artist_id)` returning a static dict; no behavior change for current flows.
