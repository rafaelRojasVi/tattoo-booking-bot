# Performance & stress test

How to run HTTP load tests and internal throughput benchmarks locally or with Docker. No external services (WhatsApp/Stripe) are called; use DRY_RUN or local endpoints.

## Tools

- **scripts/load_test_http.py** — HTTP load tester (latency percentiles, RPS, error rate). Uses `httpx` (already in requirements).
- **scripts/bench_handle_inbound.py** — Optional: internal throughput of `handle_inbound_message` in a tight loop (no assertions). Requires DB.

## How to run

### Local (uvicorn)

```bash
# Terminal 1: start API (and DB if needed, e.g. docker compose up -d db)
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Terminal 2: run load test
python scripts/load_test_http.py --url http://localhost:8000/health --concurrency 50 --requests 2000 --warmup 200
```

### Docker Compose

```bash
docker compose up -d --build
python scripts/load_test_http.py --url http://localhost:8000/health --concurrency 50 --requests 2000 --warmup 200
```

Optional: write results to JSON:

```bash
python scripts/load_test_http.py --url http://localhost:8000/health --concurrency 50 --requests 5000 --output docs/perf/latest.json
```

## Scenarios

### A) Baseline: /health and /ready

- **/health**: lightweight; good for baseline latency and max RPS.
- **/ready**: may hit DB; use to compare with /health.

Example:

```bash
python scripts/load_test_http.py --url http://localhost:8000/health --concurrency 50 --requests 5000 --warmup 200
python scripts/load_test_http.py --url http://localhost:8000/ready --concurrency 20 --requests 1000 --warmup 100
```

### B) WhatsApp webhook endpoint (DRY_RUN)

The WhatsApp webhook (`POST /webhooks/whatsapp`) **verifies the request signature** (`X-Hub-Signature-256`). Invalid or missing signature returns **403**. There is **no env flag to bypass** signature verification in the codebase.

- **Implication:** You cannot load-test the real webhook URL with arbitrary payloads without valid signatures.
- **Safe options:**
  1. **Load-test other endpoints** (e.g. /health, /ready) to measure server capacity.
  2. **Internal throughput (scenario C):** Call `handle_inbound_message` directly in a script with a local DB (no HTTP/signature).

**Proposal (documentation only; not implemented):** A **local-only bypass** could be added behind an env flag (e.g. `LOAD_TEST_BYPASS_SIGNATURE=true`) that is **forbidden in production** (explicit check that `APP_ENV != production`). This would allow replaying saved webhook bodies against the same endpoint for load tests. Do not implement unless the team agrees and the flag is strictly disabled in production.

### C) Internal throughput (optional)

**scripts/bench_handle_inbound.py** calls `handle_inbound_message` in a tight loop (with a single lead and DB session). No HTTP, no signature. Use for dev-only measurement of conversation handler throughput.

Requirements: DB available (e.g. `docker compose up -d db`), env pointing at it.

```bash
python scripts/bench_handle_inbound.py --iterations 100
```

Note: Lead state changes across iterations (NEW → QUALIFYING → …), so later iterations exercise different code paths.

---

## Results template

Paste your numbers here (machine specs, p95, RPS).

| Scenario        | Concurrency | Requests | p50 (ms) | p95 (ms) | p99 (ms) | RPS   | Error rate |
|----------------|-------------|----------|----------|----------|----------|-------|------------|
| /health        | 50          | 2000     |          |          |          |       |            |
| /ready         | 20          | 1000     |          |          |          |       |            |

**Machine:** (e.g. Windows 11, 8 CPU, 16 GB RAM, Docker Desktop)

---

## Example results

Smoke run against `/health` with Docker Compose (API in container, load test from host):

```text
--- Results ---
  URL:           http://localhost:8000/health
  Concurrency:   50
  Requests:      2000 (warmup 200 excluded)
  RPS:           752.5
  Error rate:    0.00% (0 errors)
  Latency (ms):
    avg   1.33
    p50   1.24
    p90   1.52
    p95   1.79
    p99   2.42
    max   27.03
```
