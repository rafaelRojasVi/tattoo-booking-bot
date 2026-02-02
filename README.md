# Tattoo Booking Bot

A production-ready WhatsApp-based tattoo booking system with Stripe payments, automated consultation flow, and Google Sheets integration.

[![CI](https://github.com/rafaelRojasVi/tattoo-booking-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/rafaelRojasVi/tattoo-booking-bot/actions/workflows/ci.yml)
[![Quality Checks](https://github.com/rafaelRojasVi/tattoo-booking-bot/actions/workflows/quality.yml/badge.svg)](https://github.com/rafaelRojasVi/tattoo-booking-bot/actions/workflows/quality.yml)

## Features

- **WhatsApp Integration** - Automated consultation flow with guided questions
- **Stripe Payments** - Secure deposit processing with webhook validation
- **Admin API** - Status-locked actions with atomic updates
- **Action Tokens** - Secure, single-use links for admin operations (Mode B)
- **24-Hour Window Handling** - Automatic template message fallback
- **Opt-Out Compliance** - STOP/UNSUBSCRIBE support
- **Idempotency** - Duplicate event protection (WhatsApp, Stripe, reminders)
- **Message Ordering** - Out-of-order message detection and handling
- **Multiple Enquiries** - Smart lead reuse for active enquiries
- **Reminders** - Idempotent reminders for qualifying and booking follow-ups
- **Metrics** - In-memory tracking of system events
- **Google Sheets Integration** - Automated lead logging
- **Google Calendar Integration** - Smart slot suggestions for booking

## Tech Stack

- **FastAPI** - Modern Python web framework
- **PostgreSQL** - Production database
- **SQLAlchemy** - ORM with Alembic migrations
- **Docker** - Containerized deployment
- **Stripe API** - Payment processing
- **WhatsApp Business API** - Messaging
- **Pytest** - Comprehensive test suite (390+ tests)

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.11+ (for local development)
- PostgreSQL (or use Docker Compose)
- WhatsApp Business API credentials
- Stripe account

### Docker Compose (Recommended)

```bash
# Clone the repository
git clone https://github.com/rafaelRojasVi/tattoo-booking-bot.git
cd tattoo-booking-bot

# Copy environment template
cp .env.example .env
# Edit .env with your credentials

# Start services
docker compose up -d

# Run migrations
docker compose exec api alembic upgrade head

# View logs
docker compose logs -f api
```

API available at `http://localhost:8000`

### Local Development

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt  # Includes pytest, pytest-mock, and other dev tools

# Set up environment variables (copy .env.example to .env)
cp .env.example .env
# Edit .env with your credentials

# Run migrations
alembic upgrade head

# Start development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Environment Variables

Create a `.env` file from `.env.example` template. Required variables:

### Required

- `DATABASE_URL` - PostgreSQL connection string
- `WHATSAPP_VERIFY_TOKEN` - Meta WhatsApp webhook verification token
- `WHATSAPP_ACCESS_TOKEN` - Meta WhatsApp API access token
- `WHATSAPP_PHONE_NUMBER_ID` - Meta WhatsApp phone number ID
- `STRIPE_SECRET_KEY` - Stripe secret key (use `sk_test_...` for testing)
- `STRIPE_WEBHOOK_SECRET` - Stripe webhook signing secret
- `FRESHA_BOOKING_URL` - Booking platform URL
- `ADMIN_API_KEY` - Admin API authentication key (required in production)

### Optional

- `WEB_CONCURRENCY` - Number of uvicorn worker processes (default: 2). Tune based on machine size:
  - Small machines: 1-2 workers
  - Medium machines: 2-4 workers
  - Large machines: 4-8 workers
- `OPENAI_API_KEY` - For AI features (if enabled)
- `GOOGLE_SHEETS_*` - Google Sheets integration settings
- `GOOGLE_CALENDAR_*` - Google Calendar integration settings
- Feature flags and other configuration options

See `.env.example` for a complete list of all available environment variables.

## API Endpoints

### Webhooks

- `GET /webhooks/whatsapp` - WhatsApp webhook verification
- `POST /webhooks/whatsapp` - WhatsApp inbound messages
- `POST /webhooks/stripe` - Stripe payment webhooks

### Admin (requires `X-Admin-API-Key` header)

- `GET /admin/leads` - List all leads
- `GET /admin/leads/{id}` - Get lead details
- `POST /admin/leads/{id}/approve` - Approve lead
- `POST /admin/leads/{id}/reject` - Reject lead
- `POST /admin/leads/{id}/send-deposit` - Send deposit link
- `POST /admin/leads/{id}/send-booking-link` - Send booking link
- `POST /admin/leads/{id}/mark-booked` - Mark as booked
- `GET /admin/metrics` - System metrics

### Actions (Mode B)

- `GET /a/{token}` - Action confirmation page
- `POST /a/{token}` - Execute action

### Health & Demo

- `GET /health` - Health check endpoint
- `GET /demo/*` - Demo endpoints (only when `DEMO_MODE=true`)

## Development

### Running Tests

```bash
# Run all tests
pytest -q

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_webhooks.py -v

# Run tests in Docker (isolated environment)
docker compose -f docker-compose.test.yml run --rm test

# Run tests with coverage
pytest --cov=app --cov-report=html
```

The test suite includes 390+ tests covering:
- End-to-end flows
- Webhook handling
- Idempotency
- Message ordering
- Security checks
- Integration tests

### Code Quality

```bash
# Run linter (app code only - tests have relaxed rules)
ruff check app

# Auto-fix issues where possible
ruff check app --fix

# Format code
ruff format .

# Check formatting without changes
ruff format . --check

# Type checking
mypy app

# Security scan
bandit -r app
pip-audit -r requirements.txt
```

**Note:** Ruff is configured to enforce quality in `app/` while allowing flexibility in `tests/`. See `pyproject.toml` for configuration details.

### Database Migrations

```bash
# Apply migrations
docker compose exec api alembic upgrade head

# Create new migration
docker compose exec api alembic revision --autogenerate -m "description"

# View migration history
docker compose exec api alembic history
```

### Pre-commit Setup (Optional)

```bash
# Install pre-commit hooks
pip install pre-commit
pre-commit install
```

## GitHub Actions

The repository includes automated CI/CD workflows:

- **CI** (`ci.yml`) - Runs tests and builds Docker image on every push/PR
- **Quality** (`quality.yml`) - Runs linters, type checks, and security scans
- **Release** (`release.yml`) - Builds and pushes Docker images to GitHub Container Registry on version tags

### Release Process

**Windows:**
```powershell
.\scripts\release.ps1 major  # or minor, patch
```

**Linux/Mac:**
```bash
./scripts/release.sh major  # or minor, patch
```

This will:
1. Bump the version in `VERSION` file
2. Create a git tag (e.g., `v2.1.0`)
3. Push the tag to trigger automated Docker image build
4. Publish to GitHub Container Registry

## Production Deployment

### Deployment Options

#### Render.com (Recommended)

See **[Deployment Guide](docs/DEPLOYMENT_RENDER.md)** for step-by-step instructions.

Quick start:
1. Create `render.yaml` Blueprint (already included in repo)
2. Connect your GitHub repository to Render
3. Render will automatically detect and deploy the services
4. Set environment variables in Render Dashboard
5. Run database migrations

**Key Features:**
- Web Service with health checks (`/health`, `/ready`)
- Managed PostgreSQL database
- Automatic deployments from Git
- Environment variable management
- Built-in HTTPS

#### Docker Deployment

```bash
# Pull latest image
docker pull ghcr.io/rafaelRojasVi/tattoo-booking-bot:latest

# Run with docker-compose.prod.yml
docker compose -f docker-compose.prod.yml up -d
```

### Environment Variables

Set environment variables in your deployment platform (Render Dashboard, Docker Compose, etc.):

**Required:**
- `APP_ENV=production`
- `ADMIN_API_KEY` - Strong random key (server refuses to start if missing in production)
- `DATABASE_URL` - PostgreSQL connection string
- `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`
- `WHATSAPP_APP_SECRET` - Required for webhook signature verification
- `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`
- `FRESHA_BOOKING_URL`

**Production Settings:**
- `DEMO_MODE=false` (required in production)
- `WHATSAPP_DRY_RUN=false` (to enable real message sending)
- `WEB_CONCURRENCY=2` (tune based on instance size: 1-2 for small, 4-8 for large)

**URLs:**
- `ACTION_TOKEN_BASE_URL` - Your production domain (e.g., `https://your-service.onrender.com`)
- `STRIPE_SUCCESS_URL`, `STRIPE_CANCEL_URL` - Payment redirect URLs

**Optional:**
- `RATE_LIMIT_ENABLED=true` (default: enabled)
- `RATE_LIMIT_REQUESTS=10` (requests per window)
- `RATE_LIMIT_WINDOW_SECONDS=60` (time window)

See `.env.example` for complete list of available environment variables.

### Environment Checklist

- [ ] `APP_ENV=production`
- [ ] `ADMIN_API_KEY` set (strong random key)
- [ ] `DEMO_MODE=false`
- [ ] `WHATSAPP_DRY_RUN=false`
- [ ] `WHATSAPP_APP_SECRET` set (for webhook verification)
- [ ] `DATABASE_URL` points to production database
- [ ] `ACTION_TOKEN_BASE_URL` set to production domain
- [ ] `STRIPE_SUCCESS_URL` and `STRIPE_CANCEL_URL` configured
- [ ] Stripe webhook endpoint configured
- [ ] WhatsApp webhook configured
- [ ] Database migrations applied (`alembic upgrade head`)

See **[Deployment Guide](docs/DEPLOYMENT_RENDER.md)** for Render.com deployment or **[Operations Runbook](docs/ops_runbook.md)** for detailed production setup and troubleshooting.

## Security

- **Admin endpoints** require API key in production (server refuses to start if missing)
- **Action tokens** are single-use, time-limited, and status-locked
- **Atomic operations** ensure data consistency with status-locked updates
- **Idempotency keys** prevent duplicate processing of events
- **Stripe webhook signature verification** validates all payment events
- **Checkout session ID validation** prevents wrong lead assignment
- **Environment variables** loaded securely via pydantic-settings
- **No secrets in code** - all sensitive data via environment variables

### Security Best Practices

- Never commit `.env` files or credentials
- Use strong, randomly generated `ADMIN_API_KEY`
- Regularly rotate API keys and tokens
- Enable Stripe webhook signature verification
- Use HTTPS in production
- Review security reports from `bandit` and `pip-audit`

## Project Structure

```
tattoo-booking-bot/
├── app/
│   ├── api/          # API endpoints (webhooks, admin, actions)
│   ├── core/         # Core configuration
│   ├── db/           # Database models and session management
│   ├── schemas/      # Pydantic schemas
│   └── services/     # Business logic services
├── tests/            # Comprehensive test suite
├── migrations/       # Alembic database migrations
├── docs/             # Documentation
├── scripts/          # Utility scripts (release, version bump)
└── docker-compose*.yml  # Docker configurations
```

See [FILE_ORGANIZATION.md](docs/FILE_ORGANIZATION.md) for detailed structure.

## Documentation

- [Operations Runbook](docs/ops_runbook.md) - Production setup and troubleshooting
- [Development Summary](docs/DEVELOPMENT_SUMMARY.md) - Development history and decisions
- [Quality Audit](docs/QUALITY_AUDIT.md) - Code quality assessment
- [File Organization](docs/FILE_ORGANIZATION.md) - Project structure guide

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests (`pytest -v`)
5. Run linter (`ruff check app tests`)
6. Commit your changes (`git commit -m 'Add amazing feature'`)
7. Push to the branch (`git push origin feature/amazing-feature`)
8. Open a Pull Request

## License

See [LICENSE](LICENSE) file.

## Support

For production issues, see the [Operations Runbook](docs/ops_runbook.md) troubleshooting section.

## Status

- ✅ Production-ready with comprehensive test coverage
- ✅ CI/CD pipelines configured
- ✅ Security best practices implemented
- ✅ Docker-based deployment
- ✅ Documentation complete
