# Failure Isolation Analysis

## Summary

Your explanation about failure isolation in FastAPI is **correct**. However, your current implementation has some gaps that could be improved to match the robustness described in your explanation.

## Current State Assessment

### ✅ What's Working Well

1. **Error Handling in Webhooks**
   - Both WhatsApp and Stripe webhook handlers have comprehensive try/except blocks
   - Errors are caught, logged, and return appropriate HTTP responses
   - WhatsApp webhook returns success even on errors (to prevent retries) but logs errors properly
   - System events are logged for failures

2. **Auto-Restart Configuration**
   - `docker-compose.prod.yml` has `restart: unless-stopped` ✅
   - This ensures crashed containers restart automatically

3. **Async WhatsApp API Calls**
   - WhatsApp messaging uses `httpx.AsyncClient` properly
   - Non-blocking HTTP calls

4. **Idempotency**
   - Both webhooks check for duplicate events before processing
   - Prevents double-processing on retries

### ⚠️ Issues Found

#### 1. **Single Worker Process** (Critical)

**Current:**
```dockerfile
# Dockerfile
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Problem:** If the single worker process crashes (OOM, segfault, etc.), the entire app goes down until Docker restarts it.

**Impact:** Matches your description of "if you run 1 worker process, and that process dies, the app is down ❌ until restart"

**Recommendation:**
```dockerfile
# Option 1: Multiple uvicorn workers
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]

# Option 2: Gunicorn + uvicorn workers (production-grade)
CMD ["gunicorn", "app.main:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000"]
```

#### 2. **Blocking `asyncio.run()` in Async Context** (Critical)

**Location:** `app/api/webhooks.py` lines 564, 600

**Problem:**
```python
# In async function stripe_webhook()
asyncio.run(
    send_with_window_check(...)
)
```

**Why this is bad:**
- `asyncio.run()` creates a new event loop
- If called from within an async function (which already has an event loop), it will raise `RuntimeError: asyncio.run() cannot be called from a running event loop`
- The code has a workaround (lines 576-589) that uses `ThreadPoolExecutor`, but this is inefficient and can block the worker

**Current workaround:**
```python
except RuntimeError:
    # Event loop already running, use different approach
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(
            asyncio.run,
            send_whatsapp_message(...)
        )
        future.result()  # Blocks thread!
```

**Impact:** 
- Blocks a worker thread during WhatsApp API calls
- If WhatsApp API is slow/hangs, worker is blocked
- Reduces concurrency

**Recommendation:**
```python
# Just await directly - you're already in an async function!
await send_with_window_check(
    db=db,
    lead=lead,
    message=confirmation_message,
    template_name=get_template_for_deposit_confirmation(),
    template_params=get_template_params_deposit_received_next_steps(
        client_name=client_name
    ),
    dry_run=settings.whatsapp_dry_run,
)
```

#### 3. **Synchronous External API Calls in Webhooks**

**Location:** `app/api/webhooks.py` line 536

**Problem:**
```python
# Log to Google Sheets (external call - after commit)
try:
    log_lead_to_sheets(db, lead)  # Synchronous call
except Exception as e:
    logger.error(f"Failed to log lead {lead_id} to Sheets: {e}")
```

**Impact:**
- If Google Sheets API is slow or hangs, the webhook handler blocks
- Stripe webhook response is delayed
- Worker thread is occupied during the call

**Recommendation:**
- Move to background task or job queue
- Or make it truly async (if Sheets API supports it)
- Or use `BackgroundTasks` (though this still runs in same process)

#### 4. **No Timeout on External Calls**

**Problem:** No timeouts configured on:
- WhatsApp API calls (`httpx.AsyncClient`)
- Google Sheets API calls
- Calendar API calls

**Impact:** If external service hangs, worker blocks indefinitely

**Recommendation:**
```python
async with httpx.AsyncClient(timeout=10.0) as client:
    response = await client.post(url, headers=headers, json=payload)
```

## Recommendations by Priority

### Priority 1: Critical (Do Before Production)

1. **Add Multiple Workers**
   ```dockerfile
   CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
   ```

2. **Fix `asyncio.run()` in Async Context**
   - Replace all `asyncio.run()` calls in `webhooks.py` with direct `await`
   - Remove the `RuntimeError` workaround

3. **Add Timeouts to HTTP Calls**
   - Configure timeouts on all `httpx.AsyncClient` instances
   - Default: 10 seconds for webhook responses

### Priority 2: Important (Improve Resilience)

4. **Move Heavy Work to Background Tasks**
   - Use FastAPI `BackgroundTasks` for Sheets logging (quick win)
   - Consider job queue (Celery/RQ) for production scale

5. **Add Request Timeout Middleware**
   - Configure FastAPI to timeout long-running requests
   - Prevents one slow request from blocking others

### Priority 3: Nice to Have (Production Hardening)

6. **Health Check Improvements**
   - Add readiness probe (check DB connection)
   - Add liveness probe (check worker health)

7. **Monitoring & Alerting**
   - Track worker crashes
   - Alert on repeated failures
   - Monitor webhook response times

## Verification Checklist

After implementing fixes, verify:

- [ ] Multiple workers running (`ps aux | grep uvicorn` should show 4+ processes)
- [ ] One worker crash doesn't take down the app (test by killing a worker)
- [ ] No `asyncio.run()` in async functions
- [ ] All HTTP calls have timeouts
- [ ] Webhook handlers respond quickly (< 2 seconds)
- [ ] Heavy work (Sheets, Calendar) doesn't block webhook responses

## Testing Failure Scenarios

1. **Single Message Failure:**
   ```python
   # Should return 500/error, but app continues
   # ✅ Already handled correctly
   ```

2. **Worker Crash:**
   ```bash
   # Kill one worker process
   docker exec <container> kill -9 <worker_pid>
   # ✅ Should restart automatically (Docker)
   # ⚠️ But if only 1 worker, app is down until restart
   ```

3. **External API Hang:**
   ```python
   # Mock WhatsApp API to hang for 60 seconds
   # ⚠️ Currently blocks worker (needs timeout)
   ```

4. **Database Connection Loss:**
   ```python
   # ✅ Already handled with try/except
   ```

## Conclusion

Your understanding of failure isolation is correct. The main gaps are:

1. **Single worker** - Add `--workers 4` to Dockerfile
2. **Blocking async calls** - Fix `asyncio.run()` usage
3. **No timeouts** - Add timeouts to external calls
4. **Synchronous external calls** - Move to background tasks

With these fixes, your app will match the robustness described in your explanation.
