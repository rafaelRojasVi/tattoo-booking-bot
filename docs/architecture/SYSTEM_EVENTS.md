# System Events Documentation

## Overview

The system events feature provides structured logging of key system events and failures to the database. This enables better observability, debugging, and monitoring of production issues.

## Database Schema

### SystemEvent Model

**Table:** `system_events`

**Fields:**
- `id` (Integer, Primary Key) - Auto-incrementing ID
- `created_at` (DateTime, Indexed) - Timestamp when event was created (server default: now())
- `level` (String(10), Indexed) - Event level: `INFO`, `WARN`, or `ERROR`
- `event_type` (String(100), Indexed) - Type of event (e.g., `whatsapp.send_failure`, `template.fallback_used`)
- `lead_id` (Integer, Nullable, Indexed, Foreign Key to `leads.id`) - Optional lead ID associated with the event
- `payload` (JSON, Nullable) - Additional event data as JSON object

**Indexes:**
- Primary key on `id`
- Index on `created_at` (for time-based queries)
- Index on `level` (for filtering by severity)
- Index on `event_type` (for filtering by event type)
- Index on `lead_id` (for filtering by lead)

## Service API

### `app/services/system_event_service.py`

Three helper functions for logging events:

#### `info(db, event_type, lead_id=None, payload=None)`
Log an INFO-level system event.

#### `warn(db, event_type, lead_id=None, payload=None)`
Log a WARN-level system event.

#### `error(db, event_type, lead_id=None, payload=None)`
Log an ERROR-level system event.

**Parameters:**
- `db`: Database session (required)
- `event_type`: String identifier for the event type (required)
- `lead_id`: Optional lead ID (default: None)
- `payload`: Optional dict with additional event data (default: None)

**Returns:** Created `SystemEvent` object

## Event Logging Locations

Events are logged at the following key failure points:

### 1. WhatsApp Send Failure
**Location:** `app/services/whatsapp_window.py` (line ~96-103)
**Event Type:** `whatsapp.send_failure`
**Level:** ERROR
**Payload:**
- `to`: WhatsApp phone number
- `error_type`: Exception type name
- `error`: Error message (truncated to 200 chars)

**When:** Exception raised when sending WhatsApp message fails

### 2. Template Fallback Used
**Location:** `app/services/whatsapp_window.py` (line ~159-168)
**Event Type:** `template.fallback_used`
**Level:** INFO
**Payload:**
- `template_name`: Name of template used
- `window_expires_at`: ISO timestamp when 24h window expires

**When:** Template message is used because 24-hour window is closed

### 3. WhatsApp Signature Verification Failure
**Location:** `app/api/webhooks.py` (line ~48-58)
**Event Type:** `whatsapp.signature_verification_failure`
**Level:** WARN
**Payload:**
- `has_signature_header`: Boolean indicating if signature header was present

**When:** WhatsApp webhook signature verification fails

### 4. Stripe Signature Verification Failure
**Location:** `app/api/webhooks.py` (line ~262-272)
**Event Type:** `stripe.signature_verification_failure`
**Level:** WARN
**Payload:**
- `error`: Error message (truncated to 200 chars)

**When:** Stripe webhook signature verification fails

### 5. Stripe Webhook Failure
**Location:** `app/api/webhooks.py` (line ~390-404)
**Event Type:** `stripe.webhook_failure`
**Level:** ERROR
**Payload:**
- `event_type`: Stripe event type
- `checkout_session_id`: Stripe checkout session ID
- `expected_status`: Expected lead status
- `actual_status`: Actual lead status
- `reason`: Failure reason (e.g., "status_mismatch")

**When:** Stripe webhook processing fails due to status mismatch or other errors

### 6. WhatsApp Webhook Failure
**Location:** `app/api/webhooks.py` (line ~224-241)
**Event Type:** `whatsapp.webhook_failure`
**Level:** ERROR
**Payload:**
- `message_id`: WhatsApp message ID
- `wa_from`: WhatsApp phone number
- `error_type`: Exception type name
- `error`: Error message (truncated to 200 chars)

**When:** Exception raised during WhatsApp webhook conversation handling

### 7. Atomic Update Conflict
**Location:** `app/services/safety.py` (line ~58-75)
**Event Type:** `atomic_update.conflict`
**Level:** WARN
**Payload:**
- `operation`: Operation name (e.g., "update_lead_status")
- `expected_status`: Expected lead status
- `actual_status`: Actual lead status
- `new_status`: New status that was attempted

**When:** Atomic status update fails due to status mismatch (race condition)

### 8. Calendar No-Slots Fallback
**Location:** `app/services/calendar_service.py` (line ~367-378)
**Event Type:** `calendar.no_slots_fallback`
**Level:** INFO
**Payload:**
- `duration_minutes`: Booking duration in minutes
- `category`: Estimated category (SMALL, MEDIUM, LARGE, XL)

**When:** No calendar slots available, fallback to collecting preferred time windows

## Admin API Endpoint

### GET `/admin/events`

Retrieve system events with optional filtering.

**Authentication:** Required (Admin API Key)

**Query Parameters:**
- `limit` (int, optional): Maximum number of events to return (default: 100, max: 1000)
- `lead_id` (int, optional): Filter events by lead ID

**Response:**
```json
[
  {
    "id": 1,
    "created_at": "2026-01-21T10:00:00Z",
    "level": "ERROR",
    "event_type": "whatsapp.send_failure",
    "lead_id": 123,
    "payload": {
      "to": "1234567890",
      "error_type": "HTTPException",
      "error": "Failed to send message"
    }
  },
  ...
]
```

**Example Requests:**
```bash
# Get last 100 events
GET /admin/events

# Get last 50 events
GET /admin/events?limit=50

# Get events for specific lead
GET /admin/events?lead_id=123

# Combined filters
GET /admin/events?limit=200&lead_id=123
```

## Tests

**File:** `tests/test_system_events.py`

**Test Coverage:**
- ✅ System event service functions (info, warn, error)
- ✅ Events with and without lead_id
- ✅ Events with and without payload
- ✅ Admin endpoint authentication
- ✅ Admin endpoint with limit parameter
- ✅ Admin endpoint with lead_id filter
- ✅ Admin endpoint max limit cap (1000)
- ✅ Event ordering (most recent first)

**Run Tests:**
```bash
pytest tests/test_system_events.py -v
```

## Migration

**File:** `migrations/versions/a1b2c3d4e5f7_add_system_events_table.py`

**To Apply:**
```bash
alembic upgrade head
```

**To Rollback:**
```bash
alembic downgrade -1
```

## Usage Examples

### Logging an Event

```python
from app.services.system_event_service import info, warn, error

# Log INFO event
info(
    db=db,
    event_type="custom.event",
    lead_id=lead.id,
    payload={"key": "value"},
)

# Log WARN event
warn(
    db=db,
    event_type="custom.warning",
    lead_id=None,
    payload={"warning": "Something unusual happened"},
)

# Log ERROR event
error(
    db=db,
    event_type="custom.error",
    lead_id=lead.id,
    payload={"error": "Something went wrong"},
)
```

### Querying Events via API

```python
import requests

# Get recent events
response = requests.get(
    "https://api.example.com/admin/events",
    headers={"X-Admin-API-Key": "your-api-key"},
    params={"limit": 50}
)
events = response.json()

# Get events for specific lead
response = requests.get(
    "https://api.example.com/admin/events",
    headers={"X-Admin-API-Key": "your-api-key"},
    params={"lead_id": 123}
)
lead_events = response.json()
```

## Event Type Naming Convention

Event types follow a hierarchical naming pattern:
- `{service}.{action}` - e.g., `whatsapp.send_failure`
- `{service}.{category}.{action}` - e.g., `stripe.webhook_failure`
- `{feature}.{action}` - e.g., `template.fallback_used`

**Common Prefixes:**
- `whatsapp.*` - WhatsApp-related events
- `stripe.*` - Stripe payment-related events
- `template.*` - Template message events
- `atomic_update.*` - Atomic update conflicts
- `calendar.*` - Calendar integration events

## Best Practices

1. **Use appropriate log levels:**
   - `INFO`: Normal operational events (template fallback, no-slots fallback)
   - `WARN`: Recoverable issues (signature verification failures, atomic conflicts)
   - `ERROR`: Critical failures (send failures, webhook failures)

2. **Include relevant context in payload:**
   - Error messages (truncated to 200 chars)
   - IDs (message_id, checkout_session_id, etc.)
   - Status information
   - Operation context

3. **Always include lead_id when available:**
   - Enables filtering and correlation
   - Helps with debugging specific leads

4. **Keep payloads reasonable in size:**
   - Truncate long error messages
   - Don't include full request/response bodies
   - Store only essential debugging information

5. **Use consistent event_type naming:**
   - Follow the hierarchical pattern
   - Use lowercase with dots as separators
   - Be descriptive but concise
