#!/usr/bin/env python3
"""
Internal throughput benchmark: handle_inbound_message in a tight loop.

No HTTP, no webhook signature. For dev-only measurement. Requires DB (e.g. docker compose up -d db).
Uses one lead; state changes across iterations (NEW -> QUALIFYING -> ...).

Usage (from repo root, with DB and env set):
    python scripts/bench_handle_inbound.py --iterations 100
"""

import argparse
import asyncio

# Add repo root so app is importable
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal
from app.services.conversation import handle_inbound_message
from app.services.leads import get_or_create_lead


def main() -> None:
    ap = argparse.ArgumentParser(description="Benchmark handle_inbound_message")
    ap.add_argument("--iterations", type=int, default=50, help="Number of calls")
    args = ap.parse_args()
    n = args.iterations

    db = SessionLocal()
    try:
        # One lead for all iterations; state will change over the loop
        lead = get_or_create_lead(db, "bench_wa_load_test")
        message_text = "hello"

        async def run() -> float:
            start = time.perf_counter()
            for _ in range(n):
                await handle_inbound_message(
                    db=db,
                    lead=lead,
                    message_text=message_text,
                    dry_run=True,
                )
            return time.perf_counter() - start

        elapsed = asyncio.run(run())
        rps = n / elapsed if elapsed > 0 else 0
        print(f"handle_inbound_message: {n} iterations in {elapsed:.2f}s -> {rps:.1f} calls/s")
    finally:
        db.close()


if __name__ == "__main__":
    main()
