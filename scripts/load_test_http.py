#!/usr/bin/env python3
"""
HTTP load tester: latency percentiles, RPS, error rate.

Uses asyncio + httpx. No new dependencies (httpx in requirements.txt).

Usage (from repo root):
    python scripts/load_test_http.py --url http://localhost:8000/health --concurrency 50 --requests 5000
    python scripts/load_test_http.py --url http://localhost:8000/health --concurrency 50 --requests 2000 --warmup 200 --output docs/perf/latest.json
"""

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

import httpx


def percentile(sorted_values: list[float], p: float) -> float:
    """p in 0..100. Returns value at percentile."""
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * (p / 100)
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_values) else f
    return sorted_values[f] + (k - f) * (sorted_values[c] - sorted_values[f])


async def run_one(
    client: httpx.AsyncClient,
    url: str,
    timeout: float,
    sem: asyncio.Semaphore,
) -> tuple[float, int]:
    """One request. Returns (latency_sec, status_code)."""
    async with sem:
        start = time.perf_counter()
        try:
            r = await client.get(url, timeout=timeout)
            return time.perf_counter() - start, r.status_code
        except Exception:
            return time.perf_counter() - start, 0


async def main_async(
    url: str,
    concurrency: int,
    total_requests: int,
    warmup: int,
    timeout: float,
    output_path: Path | None,
) -> None:
    latencies: list[float] = []
    status_codes: list[int] = []
    sem = asyncio.Semaphore(concurrency)
    completed = 0
    total = warmup + total_requests

    async with httpx.AsyncClient() as client:
        for i in range(total):
            lat, code = await run_one(client, url, timeout, sem)
            if i >= warmup:
                latencies.append(lat)
                status_codes.append(code)
            completed += 1
            if completed % 500 == 0:
                print(f"  {completed}/{total} ...", flush=True)

    ok = sum(1 for c in status_codes if 200 <= c < 400)
    errors = len(status_codes) - ok
    error_rate = (errors / len(status_codes)) * 100 if status_codes else 0
    elapsed = sum(latencies)
    rps = len(latencies) / elapsed if elapsed > 0 else 0
    sorted_lat = sorted(latencies)

    p50 = percentile(sorted_lat, 50)
    p90 = percentile(sorted_lat, 90)
    p95 = percentile(sorted_lat, 95)
    p99 = percentile(sorted_lat, 99)
    avg_lat = statistics.mean(latencies)
    max_lat = max(latencies)

    print()
    print("--- Results ---")
    print(f"  URL:           {url}")
    print(f"  Concurrency:   {concurrency}")
    print(f"  Requests:      {len(latencies)} (warmup {warmup} excluded)")
    print(f"  RPS:          {rps:.1f}")
    print(f"  Error rate:   {error_rate:.2f}% ({errors} errors)")
    print("  Latency (ms):")
    print(f"    avg   {avg_lat * 1000:.2f}")
    print(f"    p50   {p50 * 1000:.2f}")
    print(f"    p90   {p90 * 1000:.2f}")
    print(f"    p95   {p95 * 1000:.2f}")
    print(f"    p99   {p99 * 1000:.2f}")
    print(f"    max   {max_lat * 1000:.2f}")

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        out = {
            "url": url,
            "concurrency": concurrency,
            "requests": len(latencies),
            "warmup": warmup,
            "rps": round(rps, 2),
            "error_rate_pct": round(error_rate, 2),
            "latency_ms": {
                "avg": round(avg_lat * 1000, 2),
                "p50": round(p50 * 1000, 2),
                "p90": round(p90 * 1000, 2),
                "p95": round(p95 * 1000, 2),
                "p99": round(p99 * 1000, 2),
                "max": round(max_lat * 1000, 2),
            },
        }
        output_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"\nWrote {output_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description="HTTP load test")
    ap.add_argument("--url", default="http://localhost:8000/health", help="URL to GET")
    ap.add_argument("--concurrency", type=int, default=50, help="Concurrent requests")
    ap.add_argument("--requests", type=int, default=5000, help="Total requests (after warmup)")
    ap.add_argument("--warmup", type=int, default=200, help="Warmup requests to exclude")
    ap.add_argument("--timeout", type=float, default=5.0, help="Request timeout seconds")
    ap.add_argument(
        "--output",
        type=str,
        default="",
        help="Optional JSON output path e.g. docs/perf/latest.json",
    )
    args = ap.parse_args()
    output_path = Path(args.output) if args.output else None
    asyncio.run(
        main_async(
            url=args.url,
            concurrency=args.concurrency,
            total_requests=args.requests,
            warmup=args.warmup,
            timeout=args.timeout,
            output_path=output_path,
        )
    )


if __name__ == "__main__":
    main()
