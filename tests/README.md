# Testing Guide

## Quick Start

**Run tests locally:**
```bash
pytest tests/ -v
```

**Run tests in Docker:**
```bash
docker compose -f docker-compose.test.yml run --rm test
```

**Run specific test file:**
```bash
pytest tests/test_webhooks.py -v
```

**Run specific test:**
```bash
pytest tests/test_webhooks.py::test_whatsapp_verify_success -v
```

## Test Structure

- `conftest.py` - Test fixtures (database, client)
- `test_webhooks.py` - WhatsApp webhook tests
- `test_admin.py` - Admin endpoint tests
- `test_health.py` - Health check tests

## Test Database

Tests use an in-memory SQLite database that's created fresh for each test. This makes tests:
- Fast (no real database needed)
- Isolated (each test gets a clean database)
- No cleanup needed (database is destroyed after each test)

## Writing New Tests

1. Create test file: `tests/test_feature.py`
2. Use the `client` fixture for API calls
3. Use the `db` fixture if you need direct database access

Example:
```python
def test_my_endpoint(client, db):
    response = client.get("/my/endpoint")
    assert response.status_code == 200
```
