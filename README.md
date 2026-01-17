# Tattoo Booking Bot

A WhatsApp-based tattoo booking bot built with FastAPI, integrating with Stripe for payments and Fresha for booking management.

## Features

- WhatsApp webhook integration for receiving messages
- Stripe payment processing for deposits
- AI-powered conversation handling
- PostgreSQL database for data persistence
- Automated CI/CD with GitHub Actions
- Docker image versioning and tagging

## Security Notice

⚠️ **IMPORTANT**: This repository is configured for public use. All sensitive credentials are stored in environment variables and are **NOT** committed to the repository.

- Never commit `.env` files or any files containing secrets
- All API keys, tokens, and passwords are loaded from environment variables
- See `.env.example` for required environment variables

## Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd tattoo-booking-bot
   ```

2. **Create environment file**
   ```bash
   cp .env.example .env
   ```
   Then edit `.env` with your actual credentials.

3. **Run with Docker Compose**
   ```bash
   docker compose up --build
   ```

   The API will be available at `http://localhost:8000`

## Release Process

This project uses **git tags as the single release trigger**. Releases are published automatically when you push a tag.

### Quick Release

**Windows (PowerShell):**
```powershell
.\scripts\release.ps1 patch   # 0.1.0 -> 0.1.1
.\scripts\release.ps1 minor   # 0.1.0 -> 0.2.0
.\scripts\release.ps1 major   # 0.1.0 -> 1.0.0
```

**Linux/Mac (Bash):**
```bash
./scripts/release.sh patch
./scripts/release.sh minor
./scripts/release.sh major
```

That's it! The script will:
1. Bump the `VERSION` file
2. Commit the change
3. Create an annotated git tag `vX.Y.Z`
4. Push to `origin/main` and the tag

### What Happens Next

When you push a tag starting with `v*`:
- ✅ GitHub Actions validates that `VERSION` file matches the tag
- ✅ Builds Docker image with version metadata
- ✅ Pushes to GitHub Container Registry (ghcr.io) with tags:
  - `vX.Y.Z` - Exact version
  - `X.Y` - Major.minor (e.g., `1.2`)
  - `X` - Major version (e.g., `1`)
  - `latest` - Latest release
  - `main-<sha>` - Commit SHA for traceability

### CI/CD Workflow

**On normal pushes/PRs:**
- ✅ Runs tests
- ✅ Builds Docker image (no push)

**On tag push (v*):**
- ✅ Validates version matches tag
- ✅ Builds and pushes Docker images
- ✅ Tags images with multiple version formats

## Docker Images

**Development:**
```bash
docker compose up --build
```

**Production:**
```bash
docker compose -f docker-compose.prod.yml up -d
```

Production uses versioned images from GitHub Container Registry. Update `docker-compose.prod.yml` with your repository path.

## Environment Variables

See `.env.example` for all required environment variables. Key variables include:

- `DATABASE_URL`: PostgreSQL connection string
- `WHATSAPP_VERIFY_TOKEN`: Meta WhatsApp webhook verification token
- `WHATSAPP_ACCESS_TOKEN`: Meta WhatsApp API access token
- `STRIPE_SECRET_KEY`: Stripe secret key
- `STRIPE_WEBHOOK_SECRET`: Stripe webhook signing secret
- `OPENAI_API_KEY`: OpenAI API key (if using OpenAI)

## Development

The application uses:
- FastAPI for the web framework
- SQLAlchemy for database ORM
- PostgreSQL for the database
- Docker Compose for containerization
- Alembic for database migrations

### Common Commands

```bash
# Start services
make up

# View logs
make logs

# Run migrations
make migrate

# Create migration
make migrate-create MSG="add new table"

# Run tests
# Windows (PowerShell):
.\scripts\test.ps1                    # Local tests
.\scripts\test-docker.ps1            # Docker tests (isolated)
.\scripts\test.ps1 -Coverage          # Tests with coverage

# Linux/Mac (Bash):
make test                    # Local tests
make test-docker            # Docker tests (isolated)
make test-coverage          # Tests with coverage report

# Or directly with pytest:
pytest tests/ -v            # Works on all platforms
```

See [TESTING.md](TESTING.md) for detailed testing documentation.

## API Endpoints

- `GET /health` - Health check endpoint
- `GET /webhooks/whatsapp` - WhatsApp webhook verification
- `POST /webhooks/whatsapp` - WhatsApp inbound message handler
