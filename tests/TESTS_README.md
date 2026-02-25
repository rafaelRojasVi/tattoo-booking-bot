# Tests

## Running the test suite

- **Default (recommended):** Exclude the long end-to-end flow to keep runs fast and avoid external/env requirements:
  ```bash
  pytest tests/ --ignore=tests/test_e2e_full_flow.py
  ```
- **Full suite including long e2e:**
  ```bash
  pytest tests/
  ```

## Why `test_e2e_full_flow.py` is excluded by default

- **Time:** The full-flow e2e test simulates the entire client–artist interaction (qualifying, booking, handover, resume) and is slower than the rest of the suite.
- **Environment / flakiness:** It hits real HTTP endpoints (`/webhooks/whatsapp`, etc.) and database state; running it in CI or minimal envs can be flaky or require extra setup.
- **No extra env vars** are strictly required beyond what the app normally needs (DB, config); the test uses the same test client and DB fixtures as other tests. Run it when you need full flow coverage (e.g. before release or after major conversation changes).

## Running a subset

- Import cycle checks: `pytest tests/test_import_cycles.py`
- Single file: `pytest tests/test_webhooks.py`
- Single test: `pytest tests/test_webhooks.py::test_foo -v`
