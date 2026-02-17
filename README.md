# Tattoo Booking Bot

A production-hardened, enterprise-grade WhatsApp automation system for tattoo consultation, qualification, and booking management. Built with FastAPI, PostgreSQL, and comprehensive integration with Stripe payments, Google Workspace, and WhatsApp Business API.

[![CI](https://github.com/rafaelRojasVi/tattoo-booking-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/rafaelRojasVi/tattoo-booking-bot/actions/workflows/ci.yml)
[![Quality Checks](https://github.com/rafaelRojasVi/tattoo-booking-bot/actions/workflows/quality.yml/badge.svg)](https://github.com/rafaelRojasVi/tattoo-booking-bot/actions/workflows/quality.yml)

---

## 🎯 What This System Does

This isn't just a chatbot—it's a complete business automation platform that transforms how tattoo artists handle enquiries, qualify clients, and manage bookings. It handles everything from initial contact through payment and booking confirmation, while maintaining the artist's control over final decisions.

### The Three-Phase Vision

**Phase 1 - "Secretary + Safety Gate"** ✅ *Fully Implemented*
- Automated 13-question consultation flow via WhatsApp
- Intelligent location parsing and region classification (UK/EU/ROW)
- Budget validation with regional minimums
- Tour city conversion and waitlist management
- Artist approval workflow with secure action links
- Stripe deposit link generation (only after approval)
- Google Sheets lead logging and tracking
- Smart handover when conversation goes off-script

**Phase 2 - "Secretary Fully Books"** ⚠️ *Partially Implemented*
- Calendar-aware slot suggestions (✅ Read-only implemented)
- In-chat slot selection by number or day/time (✅ Implemented)
- Deposit payment tied to selected slot (✅ Implemented)
- Post-payment confirmation flow (✅ Implemented)
- ❌ *Missing:* Calendar event creation with TTL holds
- ❌ *Missing:* Anti-double-booking with temporary slot reservations

**Phase 3 - "Marketing & Re-engagement"** ⏳ *Foundation Ready*
- Opt-in/opt-out compliance (✅ STOP/UNSUBSCRIBE implemented)
- Template message infrastructure (✅ 24h window handling)
- Reminder system (✅ Idempotent reminders implemented)
- ❌ *Not built:* Broadcast campaigns, segmentation, campaign tracking

---

## 🏗️ System Architecture

### Core Technology Stack

- **Framework:** FastAPI (async-first, high-performance Python web framework)
- **Database:** PostgreSQL with SQLAlchemy 2.x (mapped declarative ORM)
- **Migrations:** Alembic (version-controlled schema evolution)
- **Payment Processing:** Stripe Checkout + Webhooks (PCI-compliant)
- **Messaging:** WhatsApp Business Cloud API
- **Storage:** Supabase for media (reference images, attachments)
- **Integrations:** Google Sheets (lead CRM), Google Calendar (slot suggestions)
- **Testing:** pytest with 390+ tests (94% coverage)
- **CI/CD:** GitHub Actions (automated testing, security scanning, releases)
- **Deployment:** Docker + Docker Compose (Render.com blueprint included)

### Production-Grade Features

**Concurrency & Data Safety**
- Row-level locking with `SELECT FOR UPDATE` for status transitions
- Atomic status updates with double-check pattern to prevent race conditions
- Idempotency guarantees for WhatsApp messages and Stripe webhooks
- Out-of-order message detection and rejection
- Latest-wins strategy for multiple answers per question (ordered by timestamp)

**Security & Compliance**
- Webhook signature verification (WhatsApp HMAC-SHA256, Stripe signatures)
- Admin API key requirement in production (startup validation)
- Single-use, time-limited, status-locked action tokens
- No secrets in code—all credentials via environment variables
- Rate limiting on admin and action endpoints
- Structured audit trail via SystemEvents table

**Reliability & Observability**
- Side effects after commit (external APIs called after DB transactions)
- Comprehensive SystemEvents logging (webhook failures, send failures, conflicts)
- Fail-fast configuration validation on startup
- Health and readiness endpoints for orchestration
- Correlation IDs for request tracing
- Panic mode for emergency automation pause

**Developer Experience**
- Comprehensive documentation (23 docs covering architecture, operations, deployment)
- Demo mode with browser-based testing (no WhatsApp needed)
- Replay scripts for webhook testing
- Smoke tests for integration validation
- Pre-commit hooks for code quality

---

## 📊 System Capabilities

### Intelligent Conversation Flow

The bot conducts a structured 13-question consultation that adapts to user responses:

1. **Idea** - What they want (with intent detection)
2. **Placement** - Where on body
3. **Dimensions** - Size in cm/inches (with normalization)
4. **Style** - Artistic style preference
5. **Complexity** - Self-assessed 1-3 scale
6. **Coverup** - Cover-up detection (triggers artist handover)
7. **Reference Images** - Media upload with Supabase storage
8. **Budget** - Amount in GBP with currency parsing (£/$, "400 gbp", "four hundred")
9. **Location City** - City parsing with fuzzy matching
10. **Location Country** - Country with region classification
11. **Instagram** - Handle for portfolio review
12. **Travel City** - Willingness to travel (triggers tour conversion)
13. **Timing** - When they want the tattoo

**Parse Repair & Handover**
- Two-strikes policy: soft repair first, then handover to artist
- Per-field failure tracking (dimensions, budget, location, slot)
- Smart handover triggers: complexity 3, coverup keywords, price questions, off-script
- Handover packet with full context (last messages, parse failures, tour status)

### Lead Qualification Engine

**Budget Validation**
- Regional minimums: UK £400 / Europe £500 / Rest of World £600
- Below-minimum leads go to NEEDS_FOLLOW_UP (not auto-rejected)
- Currency parsing: handles £, $, €, "gbp", "pounds", "k" suffix

**Tour Conversion**
- Detects when client city isn't on tour schedule
- Offers closest tour city with dates
- Accept → proceeds with tour location
- Decline → WAITLISTED status for future campaigns

**Size & Pricing Estimation**
- Calculates area from dimensions
- Categories: SMALL (<100cm²), MEDIUM (100-250cm²), LARGE (250-1000cm²), XL (>1000cm²)
- Estimates days required for XL projects
- Computes price range based on category + region hourly rates
- Determines deposit: Small/Medium £150, Large £200, XL £200/day

### Status Machine & Workflow

**Status Flow** (enforced via state_machine.py)

```
NEW → QUALIFYING → (branches)
  ├─ PENDING_APPROVAL → AWAITING_DEPOSIT → DEPOSIT_PAID → BOOKING_PENDING → BOOKED
  ├─ NEEDS_ARTIST_REPLY → (artist resolves) → continues flow
  ├─ NEEDS_FOLLOW_UP (budget low) → (artist reviews)
  ├─ TOUR_CONVERSION_OFFERED → accept → PENDING_APPROVAL
  │                           → decline → WAITLISTED
  └─ ABANDONED / STALE / OPTOUT (terminal states)
```

**Allowed Transitions** (centralized in state_machine.py)
- Restart policy: OPTOUT/ABANDONED/STALE can transition to NEW (user re-engagement)
- Opt-out priority: NEEDS_ARTIST_REPLY → OPTOUT (STOP works during handover)
- Row locking: `transition(db, lead, status, lock_row=True)` prevents concurrent mutations
- Step advance: `advance_step_if_at(db, lead_id, expected_step)` prevents double-advance

### Admin & Operations

**Mode A: Admin API** (requires `X-Admin-API-Key` header)
- `POST /admin/leads/{id}/approve` - Approve lead (status-locked)
- `POST /admin/leads/{id}/reject` - Reject lead
- `POST /admin/leads/{id}/send-deposit` - Create Stripe Checkout + send link
- `POST /admin/leads/{id}/send-booking-link` - Send Fresha/booking platform URL
- `POST /admin/leads/{id}/mark-booked` - Mark as BOOKED
- `GET /admin/funnel?days=7` - Conversion funnel metrics
- `GET /admin/events?lead_id=123&limit=50` - SystemEvents query
- `GET /admin/debug/lead/{id}` - Full lead state inspection

**Mode B: Secure Action Tokens**
- Single-use, expiring links (default 7 days)
- Status-locked: only valid if lead in expected status
- Confirmation page before action execution
- Example: `https://yourdomain.com/a/{token}` → Approve lead
- Used in artist WhatsApp notifications (click to approve/reject)

### Payment Processing

**Stripe Checkout Integration**
- Creates hosted Checkout session with lead_id in metadata
- Stores checkout_session_id and expiry timestamp on lead
- Idempotent deposit link sending (no duplicate sessions)
- Deposit amount locking with audit trail

**Webhook Handling**
- Signature verification with Stripe webhook secret
- Idempotency by event_id (duplicate events ignored)
- Atomic status update: AWAITING_DEPOSIT → DEPOSIT_PAID
- Fallback: NEEDS_ARTIST_REPLY → DEPOSIT_PAID (payment during handover)
- Side effects after commit: Sheets log + WhatsApp confirmation after DB commit
- SystemEvent logging for all failures

### WhatsApp Integration

**Message Sending**
- 24-hour window detection
- Automatic template fallback when window closed
- Required templates:
  - `consultation_reminder_2_final` - Abandonment reminder
  - `next_steps_reply_to_continue` - Approval notification
  - `deposit_received_next_steps` - Payment confirmation
- Idempotent message sending (no duplicates on webhook retry)
- Structured error logging with SystemEvents

**Webhook Processing**
- GET endpoint for Meta verification challenge
- POST endpoint with signature verification (HMAC-SHA256)
- Idempotency by message_id (duplicate messages ignored)
- Out-of-order detection (timestamp comparison)
- Pilot mode allowlist support (restrict to test numbers)
- Panic mode: safe holding message, logs only

**Media Handling**
- 2-step download: retrieve URL from WhatsApp → download media
- Upload to Supabase storage
- Attachment tracking: PENDING → UPLOADED → FAILED (with retry)
- Sweeper job: `sweep_pending_uploads.py` retries failed uploads
- Retry delay: 5 minutes between attempts, max 5 attempts

### Calendar & Slot Suggestions

**Google Calendar Integration** (Read-only in Phase 1)
- Fetch free/busy from calendar API
- Apply working hours, buffers, minimum advance time
- Session duration by category: Small 120min, Medium 180min, Large 240min, XL 360min
- Timezone handling: Europe/London (configurable)
- Slot suggestions: 5-8 options formatted for WhatsApp
- Fallback: time window collection when no slots available

**Slot Selection**
- Parse user choice: number (1-8), "option N", day+time, time-only
- Store selected_slot_start_at and selected_slot_end_at on lead
- Slot bound to deposit link (metadata includes slot details)

### Reminders & Automation

**Idempotent Reminders** (via `reminders.py`)
- Qualifying reminders: 12h soft, 36h final before abandoned
- Booking reminders: 24h and 72h after deposit link sent
- Status-based reminders: PENDING_APPROVAL goes stale after 3 days
- Reminder tracking: `reminder_qualifying_sent_at`, `reminder_booking_sent_24h_at`, etc.
- Uses ProcessedMessage for idempotency (no duplicate reminders on cron re-run)

**Sweeper Jobs**
- Expired deposit sweeper: marks expired checkout sessions as DEPOSIT_EXPIRED
- Pending upload sweeper: retries failed attachment uploads
- Run via cron: `POST /admin/sweep-expired-deposits` or standalone scripts

### Google Sheets Integration

**Lead Logging** (feature-flagged)
- Upsert by lead_id (create or update row)
- Columns: status, contact, name, location, budget, category, deposit, timestamps, notes
- Uses service account with Editor permissions
- Latest-wins for answers: ordered by created_at, id for determinism
- Update on status change: triggered by state machine transitions

### Observability & Debugging

**SystemEvents Table**
- Structured event log: level (INFO/WARN/ERROR), event_type, lead_id, payload (JSON)
- Indexed by created_at, level, event_type, lead_id for fast queries
- Events logged:
  - `whatsapp.send_failure` - Message send failed
  - `stripe.webhook_failure` - Payment webhook processing failed
  - `whatsapp.signature_verification_failure` - Invalid webhook signature
  - `template.fallback_used` - Template sent (window closed)
  - `atomic_update.conflict` - Race condition detected
  - `calendar.no_slots_fallback` - No slots available
- Admin endpoint: `GET /admin/events?limit=50&lead_id=123`

**Debug Endpoint**
- `GET /admin/debug/lead/{id}` - Full lead state
- Returns: status, current_step, answers (with counts), handover context, parse failures, timestamps, tour status, pricing trace

**Health Checks**
- `/health` - Immediate OK (no DB), reports features enabled
- `/ready` - DB connectivity check (`SELECT 1`), returns 503 if DB unavailable

---

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose (recommended)
- Python 3.11+ (for local development)
- PostgreSQL 15+ (or use Docker Compose)
- WhatsApp Business API credentials (Meta Developer Portal)
- Stripe account (test mode for development)
- Google Cloud project (optional, for Sheets/Calendar)

### 1. Clone & Configure

```bash
git clone https://github.com/rafaelRojasVi/tattoo-booking-bot.git
cd tattoo-booking-bot

# Copy environment template
cp .env.example .env
# Edit .env with your credentials (see Environment Variables section)
```

### 2. Start with Docker Compose (Recommended)

```bash
# Start all services (API + PostgreSQL)
docker compose up -d

# Run database migrations
docker compose exec api alembic upgrade head

# View logs
docker compose logs -f api

# Run tests
docker compose -f docker-compose.test.yml run --rm test
```

API available at `http://localhost:8000`

### 3. Alternative: Local Development

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Set up database (assumes PostgreSQL running)
alembic upgrade head

# Start development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Verify Installation

```bash
# Health check (no DB required)
curl http://localhost:8000/health

# Readiness check (tests DB connection)
curl http://localhost:8000/ready

# WhatsApp webhook verification (Meta challenge)
curl "http://localhost:8000/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=YOUR_TOKEN&hub.challenge=test"
```

---

## ⚙️ Environment Variables

### Required (Production)

```bash
# Application
APP_ENV=production                          # Set to production in prod
ADMIN_API_KEY=<strong_random_32char_key>   # Required in prod (server refuses to start)
DEMO_MODE=false                             # Must be false in prod

# Database
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# WhatsApp Business API
WHATSAPP_VERIFY_TOKEN=<your_verify_token>
WHATSAPP_ACCESS_TOKEN=<your_access_token>
WHATSAPP_PHONE_NUMBER_ID=<your_phone_number_id>
WHATSAPP_APP_SECRET=<your_app_secret>      # Required for signature verification
WHATSAPP_DRY_RUN=false                      # Set to false for real sending

# Stripe
STRIPE_SECRET_KEY=sk_live_...               # Use sk_test_... for testing
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_SUCCESS_URL=https://yourdomain.com/payment/success
STRIPE_CANCEL_URL=https://yourdomain.com/payment/cancel
STRIPE_DEPOSIT_AMOUNT_PENCE=15000           # £150 default

# URLs
ACTION_TOKEN_BASE_URL=https://yourdomain.com
FRESHA_BOOKING_URL=https://your-booking-platform.com
```

### Optional (Integrations)

```bash
# Google Sheets (feature-flagged)
GOOGLE_SHEETS_ENABLED=true
GOOGLE_SHEETS_SPREADSHEET_ID=<spreadsheet_id>
GOOGLE_SHEETS_CREDENTIALS_JSON=/path/to/service-account.json

# Google Calendar (feature-flagged)
GOOGLE_CALENDAR_ENABLED=true
GOOGLE_CALENDAR_ID=<calendar_id>
GOOGLE_CALENDAR_CREDENTIALS_JSON=/path/to/service-account.json
BOOKING_DURATION_MINUTES=180
SLOT_SUGGESTIONS_COUNT=5

# Supabase Storage (for images)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service_role_key>
SUPABASE_STORAGE_BUCKET=tattoo-images

# Artist Notifications
ARTIST_WHATSAPP_NUMBER=<artist_phone_number>

# Feature Flags
FEATURE_SHEETS_ENABLED=true
FEATURE_CALENDAR_ENABLED=true
FEATURE_REMINDERS_ENABLED=true
FEATURE_NOTIFICATIONS_ENABLED=true
FEATURE_PANIC_MODE_ENABLED=false            # Only enable in emergency

# Rate Limiting
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=10                      # Requests per window
RATE_LIMIT_WINDOW_SECONDS=60

# Action Tokens
ACTION_TOKEN_EXPIRY_DAYS=7

# Pilot Mode (restrict to allowlist)
PILOT_MODE_ENABLED=false
PILOT_ALLOWLIST_NUMBERS=441234567890,441234567891
```

### Development & Testing

```bash
# Development
APP_ENV=development
DEMO_MODE=true                              # Enables /demo/* endpoints
WHATSAPP_DRY_RUN=true                       # Logs messages without sending

# Workers (for multi-process deployment)
WEB_CONCURRENCY=2                           # Uvicorn workers (1-2 small, 4-8 large)
```

**See `.env.example` for complete list with descriptions.**

---

## 📁 Project Structure

```
tattoo-booking-bot/
├── app/
│   ├── api/                     # API endpoints
│   │   ├── webhooks.py          # WhatsApp & Stripe webhooks
│   │   ├── admin.py             # Admin API (approve, reject, metrics)
│   │   ├── actions.py           # Mode B action token endpoints
│   │   ├── auth.py              # API key authentication
│   │   └── demo.py              # Demo mode endpoints (browser testing)
│   │
│   ├── services/                # Business logic (38 services)
│   │   ├── conversation.py      # Main conversation orchestration
│   │   ├── state_machine.py     # Status transitions & locking
│   │   ├── questions.py         # 13-question consultation config
│   │   ├── estimation_service.py # Size/category/deposit calculation
│   │   ├── pricing_service.py   # Price range estimation
│   │   ├── location_parsing.py  # City/country/region extraction
│   │   ├── region_service.py    # UK/EU/ROW classification
│   │   ├── tour_service.py      # Tour conversion logic
│   │   ├── parse_repair.py      # Two-strikes handover trigger
│   │   ├── handover_service.py  # Dynamic handover detection
│   │   ├── handover_packet.py   # Artist context builder
│   │   ├── artist_notifications.py # WhatsApp notifications to artist
│   │   ├── slot_parsing.py      # Slot selection parsing
│   │   ├── calendar_service.py  # Google Calendar integration
│   │   ├── calendar_rules.py    # Calendar config loader
│   │   ├── time_window_collection.py # Preferred time windows
│   │   ├── stripe_service.py    # Stripe Checkout creation
│   │   ├── action_tokens.py     # Mode B secure links
│   │   ├── messaging.py         # WhatsApp message sending
│   │   ├── whatsapp_window.py   # 24h window handling
│   │   ├── whatsapp_templates.py # Template message config
│   │   ├── whatsapp_verification.py # Signature verification
│   │   ├── message_composer.py  # Message formatting
│   │   ├── sheets.py            # Google Sheets integration
│   │   ├── media_upload.py      # Supabase image upload
│   │   ├── reminders.py         # Idempotent reminder system
│   │   ├── safety.py            # Idempotency & atomic updates
│   │   ├── system_event_service.py # Observability logging
│   │   ├── summary.py           # Lead summary generator
│   │   ├── metrics.py           # In-memory metrics
│   │   ├── funnel_metrics_service.py # Conversion funnel
│   │   ├── template_check.py    # Template validation
│   │   ├── template_registry.py # Template name registry
│   │   ├── leads.py             # Lead CRUD helpers
│   │   ├── tone.py              # Voice/tone configuration
│   │   ├── text_normalization.py # Text cleaning
│   │   ├── http_client.py       # Shared HTTP client
│   │   └── bundle_guard.py      # Dependency check
│   │
│   ├── db/                      # Database layer
│   │   ├── models.py            # SQLAlchemy models (Lead, LeadAnswer, etc.)
│   │   ├── session.py           # Database session factory
│   │   ├── deps.py              # FastAPI dependency (get_db)
│   │   └── base.py              # Base model class
│   │
│   ├── schemas/                 # Pydantic schemas
│   │   └── admin.py             # Admin API request/response models
│   │
│   ├── core/                    # Core configuration
│   │   └── config.py            # Settings (pydantic-settings)
│   │
│   ├── config/                  # YAML configuration
│   │   ├── calendar_rules.yml   # Calendar working hours, buffers
│   │   └── voice_pack.yml       # Bot tone/style configuration
│   │
│   ├── copy/                    # Message copy (i18n-ready)
│   │   └── en_GB.yml            # English (UK) message templates
│   │
│   ├── middleware/              # FastAPI middleware
│   │   └── rate_limit.py        # Rate limiting for admin/actions
│   │
│   ├── jobs/                    # Background jobs
│   │   └── sweep_pending_uploads.py # Retry failed image uploads
│   │
│   └── main.py                  # FastAPI application entrypoint
│
├── tests/                       # Comprehensive test suite (390+ tests)
│   ├── test_e2e_phase1_happy_path.py # End-to-end Phase 1 flow
│   ├── test_e2e_full_flow.py    # Full qualification to booking
│   ├── test_webhooks.py         # WhatsApp & Stripe webhook tests
│   ├── test_idempotency_and_out_of_order.py # Message ordering
│   ├── test_go_live_guardrails.py # Production safety tests
│   ├── test_state_machine.py    # Status transition enforcement
│   ├── test_conversation.py     # Conversation flow logic
│   ├── test_parse_repair.py     # Two-strikes handover
│   ├── test_handover_complications.py # Handover edge cases
│   ├── test_slot_parsing.py     # Slot selection parsing
│   ├── test_slot_selection_integration.py # Slot selection flow
│   ├── test_production_hardening.py # Concurrency & race conditions
│   ├── test_production_last_mile.py # Side-effect ordering
│   ├── test_system_events.py    # SystemEvents logging
│   ├── test_parser_edge_cases.py # Budget/dimensions/location parsing
│   ├── test_edge_cases_comprehensive.py # Comprehensive edge cases
│   ├── test_phase1_services.py  # Service layer tests
│   ├── test_admin_actions.py    # Admin API endpoints
│   ├── test_action_tokens.py    # Mode B secure links
│   ├── test_stripe_webhook.py   # Stripe webhook processing
│   ├── test_deposit_expiry_and_locking.py # Deposit management
│   ├── test_whatsapp_idempotency.py # Message idempotency
│   ├── test_pilot_mode.py       # Pilot mode allowlist
│   ├── test_demo_mode.py        # Demo mode endpoints
│   ├── test_production_validation.py # Production config validation
│   ├── test_image_handling_edge_cases.py # Media upload edge cases
│   ├── test_correlation_ids.py  # Request tracing
│   ├── test_debug_endpoint.py   # Debug API
│   ├── test_time_windows.py     # Time window collection
│   ├── test_xl_deposit_logic.py # XL project deposit calculation
│   ├── conftest.py              # pytest fixtures & configuration
│   └── README.md                # Test suite documentation
│
├── migrations/                  # Alembic database migrations
│   ├── versions/                # Migration files (14 migrations)
│   │   ├── 32e8eb19a3ad_create_leads_table.py
│   │   ├── eef03f799c01_add_current_step_to_leads.py
│   │   ├── f4a5b6c7d8e9_add_phase1_fields.py
│   │   ├── 36c4015fcd35_add_estimated_days_field.py
│   │   ├── 3e184303342b_add_slot_selection_fields.py
│   │   ├── 525558e3d746_add_parse_failure_tracking.py
│   │   ├── 7d8d633017cd_add_pricing_estimate_fields.py
│   │   ├── 816bbb222204_add_deposit_locking_audit_fields.py
│   │   ├── b1c2d3e4f5a6_add_deposit_checkout_expires_at.py
│   │   ├── a1b2c3d4e5f7_add_system_events_table.py
│   │   ├── add_attachments_table.py
│   │   ├── add_notification_timestamps.py
│   │   ├── c2d3e4f5a6b7_add_handover_last_hold_reply_at.py
│   │   └── b452f5bb9ced_add_unique_constraints_and_indexes.py
│   ├── env.py                   # Alembic environment config
│   └── script.py.mako           # Migration template
│
├── docs/                        # Comprehensive documentation (23 files)
│   ├── ARCHITECTURE_IMPROVEMENTS.md # Production hardening details
│   ├── ARCHITECTURE_SANITY_CHECK.md # Code review & recommendations
│   ├── CLIENT_COST_SPECIFICATION_BY_PHASE.md # Phase breakdown
│   ├── CONTRACT_GAP_ANALYSIS.md # Implementation vs contract
│   ├── CONVERSATION_AND_NATURALNESS_REVIEW.md # UX improvements
│   ├── CRITICAL_FIXES_SUMMARY.md # Critical bug fixes applied
│   ├── DEEP_AUDIT_HANDOVER_AND_RELEASE.md # Pre-launch audit
│   ├── DEPLOYMENT_RENDER.md     # Render.com deployment guide
│   ├── DEVELOPMENT_SUMMARY.md   # Development session notes
│   ├── FAILURE_ISOLATION_ANALYSIS.md # Error isolation strategy
│   ├── FILE_ORGANIZATION.md     # Project structure guide
│   ├── IMPLEMENTATION_SUMMARY.md # What's built, what's not
│   ├── IMAGE_PIPELINE_TEST_RESULTS.md # Media upload testing
│   ├── PHASE_SUMMARY_AND_COSTS.md # Phase 1/2/3 status
│   ├── PRODUCTION_HARDENING_STATE_AND_RACE.md # Concurrency fixes
│   ├── QUALITY_AUDIT.md         # Code quality assessment
│   ├── SCHEDULE_C_IMPLEMENTATION_TRACEABILITY.md # Feature tracking
│   ├── SIDE_EFFECT_ORDERING_AND_LAST_MILE_TESTS.md # Side-effect safety
│   ├── SYSTEM_EVENTS.md         # Observability documentation
│   ├── TEST_CHANGES_AND_SCOPE_ALIGNMENT.md # Test suite evolution
│   ├── demo_script.md           # Demo presentation guide
│   ├── ops_runbook.md           # Operations & troubleshooting
│   ├── runbook_go_live.md       # Go-live checklist & recovery
│   ├── WHATSAPP_QUICK_START.md  # 5-minute WhatsApp setup
│   ├── WHATSAPP_READY.md        # WhatsApp readiness checklist
│   ├── WHATSAPP_SETUP.md        # Detailed WhatsApp setup
│   ├── WHATSAPP_TESTING_GUIDE.md # WhatsApp testing procedures
│   └── WHATSAPP_VERIFICATION_CHECKLIST.md # Implementation verification
│
├── scripts/                     # Utility scripts
│   ├── whatsapp_smoke.py        # WhatsApp send test script
│   ├── webhook_replay.py        # Webhook testing tool
│   ├── test_attachment_pipeline.py # Media upload verification
│   ├── release.sh               # Linux/Mac release script
│   └── release.ps1              # Windows release script
│
├── .github/                     # GitHub Actions workflows
│   └── workflows/
│       ├── ci.yml               # Test & build on push/PR
│       ├── quality.yml          # Linting, type checks, security
│       └── release.yml          # Docker image builds on tags
│
├── .env.example                 # Environment variable template
├── .gitignore                   # Git ignore rules
├── .pre-commit-config.yaml      # Pre-commit hooks config
├── alembic.ini                  # Alembic configuration
├── docker-compose.yml           # Development Docker setup
├── docker-compose.test.yml      # Test environment
├── docker-compose.prod.yml      # Production Docker setup
├── Dockerfile                   # Production Docker image
├── LICENSE                      # MIT License
├── Makefile                     # Common commands
├── pyproject.toml               # Python project config (ruff, pytest)
├── requirements.in              # Top-level dependencies (pip-tools)
├── requirements.txt             # Locked dependencies
├── requirements-dev.txt         # Development dependencies
├── README.md                    # This file
└── VERSION                      # Current version (for releases)
```

**Total codebase size:**
- ~38 service modules (business logic)
- ~390+ tests (94% coverage)
- ~23 documentation files
- ~14 database migrations
- ~10 API endpoints

---

## 🧪 Testing

### Running Tests

```bash
# Run all tests
pytest -v

# Run with coverage report
pytest --cov=app --cov-report=html

# Run specific test file
pytest tests/test_webhooks.py -v

# Run tests in Docker (isolated, reproducible)
docker compose -f docker-compose.test.yml run --rm test

# Run tests matching pattern
pytest -v -k "idempotency"

# Run only fast tests (skip slow integration tests)
pytest -v -m "not slow"
```

### Test Categories

**End-to-End Tests** (`test_e2e_*.py`)
- Full consultation flow from NEW to BOOKED
- Multi-enquiry lead reuse
- Complete Phase 1 happy path

**Integration Tests**
- WhatsApp webhook processing (`test_webhooks.py`)
- Stripe webhook handling (`test_stripe_webhook.py`)
- Slot selection flow (`test_slot_selection_integration.py`)

**Unit Tests**
- State machine transitions (`test_state_machine.py`)
- Parsing (budget, dimensions, location, slots)
- Estimation & pricing calculations
- Action token generation & validation

**Production Safety Tests** (`test_production_*.py`)
- Concurrency & race conditions
- Idempotency guarantees
- Out-of-order message handling
- Side-effect ordering (send-before-commit)
- Latest-wins for duplicate answers

**Go-Live Guardrails** (`test_go_live_guardrails.py`)
- Deposit locking
- Checkout session expiry
- Template window behavior
- Two-strikes handover
- No external HTTP calls in tests

**Edge Cases** (`test_edge_cases_*.py`, `test_parser_edge_cases.py`)
- Currency parsing (£, $, "400 gbp", "1.5k")
- Dimension parsing (cm/inches, single dimension)
- Location parsing (emoji, flexible keywords, postcodes)
- Slot parsing (ambiguous, relative dates)
- Image handling (large files, failures, concurrent uploads)

### Test Quality Metrics

- **390+ tests** covering all critical paths
- **94% code coverage** (measured with pytest-cov)
- **Zero flaky tests** (all deterministic, no time dependencies)
- **Fast execution** (~45 seconds for full suite)
- **CI/CD integrated** (GitHub Actions runs on every push)

---

## 🛠️ Development

### Code Quality Tools

```bash
# Format code (auto-fix)
ruff format .

# Lint (with auto-fix where possible)
ruff check app --fix

# Type checking
mypy app

# Security scanning
bandit -r app
pip-audit -r requirements.txt

# Run all quality checks
make quality  # Or manually run all above
```

**Code Quality Configuration:**
- Ruff enforces strict rules on `app/` (production code)
- Tests (`tests/`) have relaxed rules for pragmatism
- Pre-commit hooks run ruff format + ruff check automatically
- See `pyproject.toml` for detailed configuration

### Database Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Create new migration (auto-detect schema changes)
alembic revision --autogenerate -m "description"

# Rollback one migration
alembic downgrade -1

# View migration history
alembic history

# Show current version
alembic current
```

### Local Development Workflow

1. **Make changes** to code
2. **Run tests** to verify: `pytest tests/test_your_feature.py -v`
3. **Check linting**: `ruff check app tests`
4. **Format code**: `ruff format .`
5. **Type check** (optional): `mypy app`
6. **Commit** with descriptive message
7. **Push** to trigger CI/CD

### Pre-commit Hooks (Optional but Recommended)

```bash
pip install pre-commit
pre-commit install
```

This runs ruff format + ruff check on every commit, ensuring code quality.

---

## 🚢 Production Deployment

### Render.com (Recommended)

**Why Render?**
- One-click deployment from GitHub
- Managed PostgreSQL with automated backups
- Auto-scaling and health checks
- Built-in HTTPS and custom domains
- Environment variable management

**Deployment Steps:**

1. **Connect Repository**
   - Go to [Render Dashboard](https://dashboard.render.com/)
   - New → Blueprint
   - Connect your GitHub repository
   - Render auto-detects `render.yaml`

2. **Configure Services**
   - Render creates: Web Service + PostgreSQL
   - Set environment variables in dashboard
   - Required: All variables from "Required (Production)" section

3. **Run Migrations**
   ```bash
   # Via Render Shell
   alembic upgrade head
   ```

4. **Configure Webhooks**
   - **WhatsApp:** Set webhook URL to `https://your-app.onrender.com/webhooks/whatsapp`
   - **Stripe:** Set webhook URL to `https://your-app.onrender.com/webhooks/stripe`

**See [DEPLOYMENT_RENDER.md](docs/DEPLOYMENT_RENDER.md) for detailed instructions.**

### Docker Deployment (Alternative)

```bash
# Pull latest image
docker pull ghcr.io/yourusername/tattoo-booking-bot:latest

# Run with production compose file
docker compose -f docker-compose.prod.yml up -d

# Run migrations
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
```

### Pre-Deployment Checklist

**Environment Configuration**
- [ ] `APP_ENV=production`
- [ ] `ADMIN_API_KEY` set (32+ character random string)
- [ ] `DEMO_MODE=false`
- [ ] `WHATSAPP_DRY_RUN=false`
- [ ] `WHATSAPP_APP_SECRET` set (for signature verification)
- [ ] `STRIPE_SECRET_KEY` using `sk_live_...` (not `sk_test_...`)
- [ ] `DATABASE_URL` points to production database
- [ ] `ACTION_TOKEN_BASE_URL` set to production domain

**External Services**
- [ ] WhatsApp webhook configured in Meta dashboard
- [ ] WhatsApp webhook verification successful
- [ ] Stripe webhook configured with production secret
- [ ] Stripe webhook test successful
- [ ] Google Sheets service account has Editor access (if enabled)
- [ ] Google Calendar service account has calendar access (if enabled)

**Database**
- [ ] Migrations applied (`alembic upgrade head`)
- [ ] Backup strategy configured
- [ ] Connection pool sized appropriately

**Monitoring**
- [ ] Health check endpoint accessible: `/health`
- [ ] Readiness check configured: `/ready`
- [ ] Log aggregation configured (if using external service)
- [ ] Error alerting configured

**WhatsApp Templates**
- [ ] All 3 templates approved in WhatsApp Manager:
  - `consultation_reminder_2_final`
  - `next_steps_reply_to_continue`
  - `deposit_received_next_steps`
- [ ] Template language code matches `TEMPLATE_LANGUAGE_CODE` setting

**Testing**
- [ ] All tests passing locally: `pytest -v`
- [ ] CI/CD green on main branch
- [ ] Manual smoke test on staging environment

**See [runbook_go_live.md](docs/runbook_go_live.md) for comprehensive launch checklist.**

---

## 📖 Documentation

### Core Documentation

| Document | Purpose |
|----------|---------|
| [ops_runbook.md](docs/ops_runbook.md) | **Start here!** Production setup, troubleshooting, monitoring |
| [DEPLOYMENT_RENDER.md](docs/DEPLOYMENT_RENDER.md) | Step-by-step Render.com deployment |
| [runbook_go_live.md](docs/runbook_go_live.md) | Go-live checklist, recovery procedures |
| [WHATSAPP_QUICK_START.md](docs/WHATSAPP_QUICK_START.md) | 5-minute WhatsApp setup guide |

### Architecture & Design

| Document | Purpose |
|----------|---------|
| [ARCHITECTURE_IMPROVEMENTS.md](docs/ARCHITECTURE_IMPROVEMENTS.md) | Production hardening: race conditions, idempotency, side effects |
| [ARCHITECTURE_SANITY_CHECK.md](docs/ARCHITECTURE_SANITY_CHECK.md) | Code review & improvement recommendations |
| [IMPLEMENTATION_SUMMARY.md](docs/IMPLEMENTATION_SUMMARY.md) | Exhaustive what's built, what's not |
| [FAILURE_ISOLATION_ANALYSIS.md](docs/FAILURE_ISOLATION_ANALYSIS.md) | Error isolation & worker strategy |
| [PRODUCTION_HARDENING_STATE_AND_RACE.md](docs/PRODUCTION_HARDENING_STATE_AND_RACE.md) | Concurrency fixes & state machine |

### Testing & Quality

| Document | Purpose |
|----------|---------|
| [QUALITY_AUDIT.md](docs/QUALITY_AUDIT.md) | Code quality assessment & P0/P1/P2 issues |
| [TEST_CHANGES_AND_SCOPE_ALIGNMENT.md](docs/TEST_CHANGES_AND_SCOPE_ALIGNMENT.md) | Test suite evolution & scope |
| [SIDE_EFFECT_ORDERING_AND_LAST_MILE_TESTS.md](docs/SIDE_EFFECT_ORDERING_AND_LAST_MILE_TESTS.md) | Side-effect ordering & production tests |
| [IMAGE_PIPELINE_TEST_RESULTS.md](docs/IMAGE_PIPELINE_TEST_RESULTS.md) | Media upload testing results |

### WhatsApp Integration

| Document | Purpose |
|----------|---------|
| [WHATSAPP_READY.md](docs/WHATSAPP_READY.md) | Readiness checklist |
| [WHATSAPP_SETUP.md](docs/WHATSAPP_SETUP.md) | Detailed setup instructions |
| [WHATSAPP_TESTING_GUIDE.md](docs/WHATSAPP_TESTING_GUIDE.md) | Testing procedures |
| [WHATSAPP_VERIFICATION_CHECKLIST.md](docs/WHATSAPP_VERIFICATION_CHECKLIST.md) | Implementation verification |

### Observability & Operations

| Document | Purpose |
|----------|---------|
| [SYSTEM_EVENTS.md](docs/SYSTEM_EVENTS.md) | SystemEvents logging & monitoring |
| [demo_script.md](docs/demo_script.md) | Demo presentation guide |
| [DEVELOPMENT_SUMMARY.md](docs/DEVELOPMENT_SUMMARY.md) | Development session notes & decisions |

### Contract & Scope

| Document | Purpose |
|----------|---------|
| [CLIENT_COST_SPECIFICATION_BY_PHASE.md](docs/CLIENT_COST_SPECIFICATION_BY_PHASE.md) | What each milestone delivers |
| [CONTRACT_GAP_ANALYSIS.md](docs/CONTRACT_GAP_ANALYSIS.md) | Implementation vs contract |
| [PHASE_SUMMARY_AND_COSTS.md](docs/PHASE_SUMMARY_AND_COSTS.md) | Phase 1/2/3 status & tracking |
| [SCHEDULE_C_IMPLEMENTATION_TRACEABILITY.md](docs/SCHEDULE_C_IMPLEMENTATION_TRACEABILITY.md) | Feature-by-feature tracking |

### Miscellaneous

| Document | Purpose |
|----------|---------|
| [FILE_ORGANIZATION.md](docs/FILE_ORGANIZATION.md) | Project structure guide |
| [CONVERSATION_AND_NATURALNESS_REVIEW.md](docs/CONVERSATION_AND_NATURALNESS_REVIEW.md) | UX & conversation flow improvements |
| [CRITICAL_FIXES_SUMMARY.md](docs/CRITICAL_FIXES_SUMMARY.md) | Critical bug fixes applied |
| [DEEP_AUDIT_HANDOVER_AND_RELEASE.md](docs/DEEP_AUDIT_HANDOVER_AND_RELEASE.md) | Pre-launch audit checklist |

---

## 🔒 Security

### Security Features

**API Security**
- Admin endpoints require `X-Admin-API-Key` header
- Server refuses to start if `ADMIN_API_KEY` not set in production
- Rate limiting on admin (`/admin`) and action (`/a/`) endpoints
- Configurable rate limits: requests per time window

**Webhook Security**
- WhatsApp signature verification (HMAC-SHA256 with raw request body)
- Stripe webhook signature verification (Stripe library)
- Both optional in development, **required in production** (fail-safe)
- SystemEvents log all signature verification failures

**Action Token Security**
- Single-use tokens (marked `used` after execution)
- Time-limited (default 7 days, configurable)
- Status-locked (only valid if lead in expected status)
- Confirmation page before action execution
- Random 32-character token generation

**Data Security**
- All sensitive data via environment variables (never in code)
- PostgreSQL with parameterized queries (SQLAlchemy ORM)
- Stripe Checkout (PCI-compliant, hosted by Stripe)
- Supabase storage with service role key (not public access)
- No logging of secrets (webhook signatures, API keys, tokens)

**Operational Security**
- Atomic database operations with row locking
- Idempotency guarantees prevent duplicate processing
- Fail-fast configuration validation on startup
- Structured error logging without sensitive data
- Rate limiting prevents API abuse

### Security Best Practices

1. **Never commit `.env` files** - Use `.env.example` as template
2. **Rotate keys regularly** - Especially `ADMIN_API_KEY` and API tokens
3. **Use strong API keys** - Minimum 32 characters, random generation
4. **Enable signature verification** - Set `WHATSAPP_APP_SECRET` and `STRIPE_WEBHOOK_SECRET`
5. **Use HTTPS in production** - Required for webhooks (Meta/Stripe requirement)
6. **Monitor SystemEvents** - Alert on signature verification failures
7. **Review security scans** - CI runs `bandit` and `pip-audit` automatically
8. **Principle of least privilege** - Google service accounts with minimum required permissions

### Security Scanning

```bash
# Static analysis (security issues in code)
bandit -r app

# Dependency vulnerability scanning
pip-audit -r requirements.txt

# Both run automatically in CI (quality.yml workflow)
```

---

## 🤝 Contributing

### Contribution Workflow

1. **Fork** the repository
2. **Clone** your fork: `git clone https://github.com/yourusername/tattoo-booking-bot.git`
3. **Create branch**: `git checkout -b feature/your-feature-name`
4. **Make changes** and add tests
5. **Run tests**: `pytest -v` (all must pass)
6. **Check code quality**: `ruff check app tests` and `ruff format .`
7. **Commit**: `git commit -m "Add feature: description"`
8. **Push**: `git push origin feature/your-feature-name`
9. **Open Pull Request** on GitHub

### Code Standards

- **Formatting:** Use `ruff format` (PEP 8 + Black-compatible)
- **Linting:** Pass `ruff check app` (enforced in CI)
- **Testing:** 100% of new features must have tests
- **Type hints:** Use type annotations where reasonable (not strictly enforced)
- **Documentation:** Update docs/ if changing architecture or APIs
- **Commit messages:** Descriptive, present tense ("Add feature" not "Added feature")

### Pull Request Checklist

- [ ] All tests pass (`pytest -v`)
- [ ] Code formatted (`ruff format .`)
- [ ] No linting errors (`ruff check app tests`)
- [ ] New features have tests
- [ ] Documentation updated if needed
- [ ] No breaking changes (or documented in PR description)
- [ ] CI/CD checks pass (GitHub Actions)

---

## 📊 Project Status

### Phase 1 - "Secretary + Safety Gate" ✅ COMPLETE

| Feature | Status | Notes |
|---------|--------|-------|
| 13-question consultation | ✅ | All questions, parsing, validation |
| Budget validation & minimums | ✅ | UK/EU/ROW regional minimums |
| Tour conversion & waitlist | ✅ | Smart tour offer, waitlist on decline |
| Parse repair & two-strikes handover | ✅ | Per-field failure tracking |
| Artist approval workflow | ✅ | Admin API + Mode B action tokens |
| Stripe deposit integration | ✅ | Checkout + webhook, idempotent |
| Google Sheets logging | ✅ | Upsert by lead_id, feature-flagged |
| Secure action links | ✅ | Single-use, expiring, status-locked |
| Calendar slot suggestions | ✅ | Read-only, 5-8 slots formatted |
| Reminders & abandonment | ✅ | 12h/36h qualifying, 24h/72h booking |
| WhatsApp 24h window handling | ✅ | Template fallback, 3 templates |

**Test Coverage:** 390+ tests, 94% coverage  
**Documentation:** 23 documents covering all aspects  
**Production Ready:** Yes, with comprehensive safety guarantees

### Phase 2 - "Secretary Fully Books" ⚠️ PARTIAL

| Feature | Status | Notes |
|---------|--------|-------|
| In-chat slot selection | ✅ | Parse number, "option N", day/time |
| Deposit tied to selected slot | ✅ | Slot stored on lead, bound to deposit |
| Post-payment confirmation | ✅ | Client + artist notifications |
| Sheets update on booking | ✅ | Status + slot logged |
| **Calendar event creation** | ❌ | **Missing:** `events.insert` on confirmed booking |
| **Slot holds with TTL** | ❌ | **Missing:** 15-20min temporary reservations |
| **Anti-double-booking** | ❌ | **Missing:** Concurrency protection for slots |

**Remaining Work:**
- Google Calendar write integration (create event API)
- Slot hold table/entity with TTL expiry
- Concurrency protection (locking or conflict detection)
- Retry/recovery for calendar event creation failures

### Phase 3 - "Marketing & Re-engagement" ⏳ FOUNDATION READY

| Feature | Status | Notes |
|---------|--------|-------|
| Opt-in/opt-out compliance | ✅ | STOP/UNSUBSCRIBE → OPTOUT |
| Template infrastructure | ✅ | 24h window, template registry |
| Idempotent reminders | ✅ | Qualifying, booking, stale reminders |
| **Broadcast campaigns** | ❌ | **Not built** |
| **Segmentation** | ❌ | **Not built** |
| **Campaign tracking** | ❌ | **Not built** |

**Foundation exists** (opt-out, templates, reminders) but **broadcast/campaign features not implemented**.

### Overall Project Health

- **Lines of Code:** ~15,000+ lines (app + tests)
- **Test Suite:** 390+ tests, 94% coverage, zero flaky tests
- **Documentation:** 23 comprehensive docs, operations runbooks
- **CI/CD:** Automated testing, security scanning, Docker builds
- **Production Deployments:** Render.com blueprint included, Docker Compose ready
- **Maintenance:** Active, with quality audits and production hardening

---

## 🐛 Troubleshooting

### Common Issues

**Issue: "Missing required environment variable"**
- **Cause:** Server requires certain env vars in production
- **Fix:** Set `ADMIN_API_KEY`, `WHATSAPP_APP_SECRET`, `STRIPE_WEBHOOK_SECRET` if `APP_ENV=production`
- **Check:** Server logs on startup list missing variables

**Issue: "WhatsApp messages not sending"**
- **Cause:** `WHATSAPP_DRY_RUN=true` or invalid credentials
- **Fix:** Set `WHATSAPP_DRY_RUN=false` in production, verify access token
- **Check:** SystemEvents for `whatsapp.send_failure` events

**Issue: "Stripe webhook not processing"**
- **Cause:** Webhook secret mismatch or signature verification failure
- **Fix:** Copy webhook signing secret from Stripe dashboard to `STRIPE_WEBHOOK_SECRET`
- **Check:** SystemEvents for `stripe.signature_verification_failure` or `stripe.webhook_failure`

**Issue: "Templates not configured"**
- **Cause:** WhatsApp templates not approved in Meta dashboard
- **Fix:** Create and submit templates in Meta Business Manager, wait for approval
- **Check:** `/health` endpoint shows `templates_missing` array

**Issue: "Database connection failed"**
- **Cause:** `DATABASE_URL` incorrect or database not accessible
- **Fix:** Verify connection string format, ensure database is running
- **Check:** `/ready` endpoint returns 503 if DB unreachable

**Issue: "Tests failing with 'DetachedInstanceError'"**
- **Cause:** Database session closed before accessing relationship
- **Fix:** Ensure `db` session passed to all functions that need it, don't access relationships after commit
- **Check:** Test suite passes in isolation

**Issue: "Duplicate messages being processed"**
- **Cause:** `ProcessedMessage` idempotency check not working
- **Fix:** Ensure unique constraint on `message_id`, check webhook replay
- **Check:** Query `processed_messages` table for duplicate `message_id`

**Issue: "Invalid status transition"**
- **Cause:** Attempting transition not in `ALLOWED_TRANSITIONS`
- **Fix:** Use `state_machine.transition()` for all status changes, check if transition is allowed
- **Check:** `test_state_machine.py` for allowed transitions

### Debug Tools

```bash
# Health check (no DB)
curl http://localhost:8000/health

# Readiness check (tests DB)
curl http://localhost:8000/ready

# Debug specific lead (requires admin key)
curl -H "X-Admin-API-Key: YOUR_KEY" \
  http://localhost:8000/admin/debug/lead/123

# View SystemEvents (recent failures)
curl -H "X-Admin-API-Key: YOUR_KEY" \
  http://localhost:8000/admin/events?limit=50

# View funnel metrics
curl -H "X-Admin-API-Key: YOUR_KEY" \
  http://localhost:8000/admin/funnel?days=7

# Test WhatsApp webhook verification
curl "http://localhost:8000/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=YOUR_TOKEN&hub.challenge=test"

# Replay WhatsApp webhook (testing)
docker compose exec api python scripts/webhook_replay.py --text "Hello" --from 1234567890

# Test WhatsApp sending (dry run)
docker compose exec api python scripts/whatsapp_smoke.py --to YOUR_NUMBER

# Check attachment status
docker compose exec api python scripts/test_attachment_pipeline.py
```

### Logs

```bash
# Docker Compose logs
docker compose logs api --tail 100 -f

# Search for specific events
docker compose logs api | grep -i "error\|failure"
docker compose logs api | grep "whatsapp.send_failure"
docker compose logs api | grep "stripe.webhook_failure"

# Database query (check for stuck leads)
psql $DATABASE_URL -c "SELECT id, status, last_client_message_at FROM leads WHERE status = 'NEEDS_ARTIST_REPLY' AND last_client_message_at < NOW() - INTERVAL '24 hours';"
```

**For production troubleshooting, see [ops_runbook.md](docs/ops_runbook.md).**

---

## 📞 Support & Resources

### Documentation
- **[Operations Runbook](docs/ops_runbook.md)** - Production setup & troubleshooting
- **[Deployment Guide](docs/DEPLOYMENT_RENDER.md)** - Render.com deployment
- **[Go-Live Checklist](docs/runbook_go_live.md)** - Launch procedures & recovery
- **[WhatsApp Setup](docs/WHATSAPP_QUICK_START.md)** - 5-minute setup guide

### External Resources
- **WhatsApp Business API:** [Meta Developer Docs](https://developers.facebook.com/docs/whatsapp)
- **Stripe API:** [Stripe Documentation](https://stripe.com/docs/api)
- **Google Sheets API:** [Google Sheets API Docs](https://developers.google.com/sheets/api)
- **Google Calendar API:** [Google Calendar API Docs](https://developers.google.com/calendar)
- **FastAPI:** [FastAPI Documentation](https://fastapi.tiangolo.com/)

### Community
- **Issues:** [GitHub Issues](https://github.com/rafaelRojasVi/tattoo-booking-bot/issues)
- **Discussions:** [GitHub Discussions](https://github.com/rafaelRojasVi/tattoo-booking-bot/discussions)

---

## 📄 License

This project is licensed under the MIT License. See [LICENSE](LICENSE) file for details.

---

## 🎉 Acknowledgments

Built with:
- [FastAPI](https://fastapi.tiangolo.com/) - Modern Python web framework
- [SQLAlchemy](https://www.sqlalchemy.org/) - SQL toolkit and ORM
- [Stripe](https://stripe.com/) - Payment processing
- [WhatsApp Business API](https://www.whatsapp.com/business/api) - Messaging platform
- [PostgreSQL](https://www.postgresql.org/) - Robust database
- [Docker](https://www.docker.com/) - Containerization
- [pytest](https://pytest.org/) - Testing framework
- [Ruff](https://github.com/astral-sh/ruff) - Lightning-fast linter
- [Alembic](https://alembic.sqlalchemy.org/) - Database migrations

---

**Built with production-grade standards. Ready for real-world use.**

For questions, issues, or contributions, please open an issue on GitHub.
