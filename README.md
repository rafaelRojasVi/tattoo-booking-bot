# Tattoo Booking Bot

Production-ready WhatsApp-based tattoo booking system with Stripe payments, automated consultation flow, and Google Sheets integration.

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

## Quick Start

### Docker Compose

```bash
docker compose up -d
```

API available at `http://localhost:8000`

### Environment Variables

Required variables (see `.env.example`):

- `DATABASE_URL` - PostgreSQL connection string
- `WHATSAPP_VERIFY_TOKEN` - Meta WhatsApp webhook verification
- `WHATSAPP_ACCESS_TOKEN` - Meta WhatsApp API token
- `WHATSAPP_PHONE_NUMBER_ID` - Meta WhatsApp phone number ID
- `STRIPE_SECRET_KEY` - Stripe secret key
- `STRIPE_WEBHOOK_SECRET` - Stripe webhook signing secret
- `ADMIN_API_KEY` - Admin API authentication key (required in production)
- `APP_ENV` - Environment: `dev` or `production`

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

### Health
- `GET /health` - Health check

## Development

```bash
# Run tests
pytest tests/ -v

# Run tests in Docker
docker compose -f docker-compose.test.yml run --rm test

# Database migrations
docker compose exec api alembic upgrade head
docker compose exec api alembic revision --autogenerate -m "description"
```

## Release

**Windows:**
```powershell
.\scripts\release.ps1 major
```

**Linux/Mac:**
```bash
./scripts/release.sh major
```

Pushes version tag to trigger automated Docker image build and publish.

## Production Deployment

1. Set `APP_ENV=production` and `ADMIN_API_KEY`
2. Configure WhatsApp templates for 24h window fallback
3. Set up Google Sheets integration (currently stub)
4. Configure Stripe webhook endpoint
5. Deploy using versioned Docker images from GitHub Container Registry

## Security

- Admin endpoints require API key in production (server refuses to start if missing)
- Action tokens are single-use, time-limited, and status-locked
- All critical operations use atomic status-locked updates
- Idempotency keys prevent duplicate processing
- Stripe webhook signature verification
- Checkout session ID validation prevents wrong lead assignment

## License

See [LICENSE](LICENSE) file.
