# Testing Guide

This document explains how to run tests for the Tattoo Booking Bot project.

## Quick Reference

### Local Testing (Recommended for Development)

**Windows (PowerShell):**
```powershell
# Run all tests
pytest tests/ -v

# Or using PowerShell script
.\scripts\test.ps1

# With coverage
.\scripts\test.ps1 -Coverage
```

**Linux/Mac (Bash):**
```bash
# Run all tests
pytest tests/ -v

# Or using Make
make test
```

### Docker Testing (Isolated Environment)

**Windows (PowerShell):**
```powershell
# Run tests in isolated Docker container
docker compose -f docker-compose.test.yml run --rm test

# Or using PowerShell script
.\scripts\test-docker.ps1
```

**Linux/Mac (Bash):**
```bash
# Run tests in isolated Docker container
docker compose -f docker-compose.test.yml run --rm test

# Or using Make
make test-docker
```

## Detailed Commands

### Local Testing

**Prerequisites:**
- Python 3.11+ installed
- Dependencies installed: `pip install -r requirements.txt` (if you have one) or install manually

**Basic Commands:**

```bash
# Run all tests with verbose output
pytest tests/ -v

# Run all tests (quiet mode)
pytest tests/ -q

# Run specific test file
pytest tests/test_webhooks.py -v

# Run specific test function
pytest tests/test_webhooks.py::test_whatsapp_verify_success -v

# Run tests matching a pattern
pytest tests/ -k "whatsapp" -v

# Run tests with coverage report
pytest tests/ -v --cov=app --cov-report=html --cov-report=term
```

**Using Make (Linux/Mac):**

```bash
make test                    # Run all tests
make test-fast              # Run tests (quiet)
make test-coverage          # Run with coverage
make test-specific FILE=tests/test_webhooks.py  # Run specific file
```

**Using PowerShell Scripts (Windows):**

```powershell
.\scripts\test.ps1                    # Run all tests
.\scripts\test.ps1 -Fast              # Run tests (quiet)
.\scripts\test.ps1 -Coverage          # Run with coverage
.\scripts\test.ps1 -File tests/test_webhooks.py  # Run specific file
.\scripts\test.ps1 -Pattern whatsapp  # Run tests matching pattern
```

### Docker Testing

**Option 1: Isolated Test Container (Recommended)**

This runs tests in a completely isolated environment with test-specific environment variables:

```bash
# Using docker compose directly
docker compose -f docker-compose.test.yml run --rm test

# Using Make
make test-docker

# With coverage
docker compose -f docker-compose.test.yml run --rm test pytest tests/ -v --cov=app --cov-report=term
make test-docker-coverage
```

**Option 2: Test in Running Container**

If you have the main services running (`docker compose up`), you can exec into the API container:

```bash
# Start services first
docker compose up -d

# Run tests in the running container
docker compose exec api pytest tests/ -v

# Or using Make
make test-docker-exec
```

**Option 3: One-off Container**

```bash
# Build and run tests in one command
docker compose -f docker-compose.test.yml build test
docker compose -f docker-compose.test.yml run --rm test
```

## Test Environment

### Local Testing Environment Variables

Tests use in-memory SQLite database by default. Environment variables are set in `tests/conftest.py`:

- `DATABASE_URL`: `sqlite:///:memory:`
- `WHATSAPP_VERIFY_TOKEN`: `test_token`
- `WHATSAPP_ACCESS_TOKEN`: `test_token`
- `WHATSAPP_PHONE_NUMBER_ID`: `test_id`
- `STRIPE_SECRET_KEY`: `sk_test_test`
- `STRIPE_WEBHOOK_SECRET`: `whsec_test`
- `FRESHA_BOOKING_URL`: `https://test.com`

### Docker Test Environment

The `docker-compose.test.yml` file sets the same test environment variables, ensuring consistent test behavior.

## Test Structure

```
tests/
├── conftest.py              # Test fixtures and setup
├── test_admin.py           # Admin endpoint tests
├── test_health.py           # Health check tests
├── test_services.py         # Service layer tests
├── test_webhooks.py         # Basic webhook tests
└── test_webhooks_extended.py # Extended webhook tests (message types, errors)
```

## Running Specific Tests

### By File

```bash
# Local
pytest tests/test_webhooks.py -v
pytest tests/test_services.py -v

# Docker
docker compose -f docker-compose.test.yml run --rm test pytest tests/test_webhooks.py -v
```

### By Test Name Pattern

```bash
# Run all tests containing "whatsapp" in the name
pytest tests/ -k "whatsapp" -v

# Run all tests containing "error" in the name
pytest tests/ -k "error" -v
```

### By Test Function

```bash
# Run specific test function
pytest tests/test_webhooks.py::test_whatsapp_verify_success -v
pytest tests/test_webhooks_extended.py::test_whatsapp_inbound_image_message -v
```

## Coverage Reports

### Generate Coverage Report

```bash
# Local
pytest tests/ -v --cov=app --cov-report=html --cov-report=term

# Docker
docker compose -f docker-compose.test.yml run --rm test pytest tests/ -v --cov=app --cov-report=html --cov-report=term
```

After running, open `htmlcov/index.html` in your browser to see the coverage report.

## Continuous Integration

Tests are automatically run in GitHub Actions on:
- Every push to `main` or `develop` branches
- Every pull request to `main` or `develop` branches

See `.github/workflows/ci.yml` for the CI configuration.

## Troubleshooting

### Tests Fail Locally But Pass in Docker

1. Check Python version: `python --version` (should be 3.11+)
2. Check dependencies: Make sure all packages are installed
3. Check environment variables: Ensure test env vars are set correctly

### Tests Fail in Docker

1. Rebuild the image: `docker compose -f docker-compose.test.yml build test`
2. Check Docker logs: `docker compose -f docker-compose.test.yml logs test`
3. Run interactively: `docker compose -f docker-compose.test.yml run --rm test bash` then run `pytest` manually

### Database Connection Issues

Tests use in-memory SQLite, so database connection issues usually indicate:
- Missing SQLAlchemy dependency
- Incorrect database URL format
- Issues with test fixtures in `conftest.py`

## Best Practices

1. **Run tests locally before committing** - Use `make test` or `pytest tests/ -v`
2. **Run tests in Docker before pushing** - Use `make test-docker` to ensure consistency
3. **Write tests for new features** - Follow the existing test patterns
4. **Keep tests fast** - Use in-memory SQLite for speed
5. **Test edge cases** - See `test_webhooks_extended.py` for examples
