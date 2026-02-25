#!/usr/bin/env python3
"""
Run the same Docker build and tests as CI, so you catch failures before pushing.

Uses docker-compose.test.yml (same as .github/workflows/ci.yml):
  1. docker compose -f docker-compose.test.yml build
  2. docker compose -f docker-compose.test.yml run --rm test

Run from repo root:
  python scripts/check_docker.py
  uv run python scripts/check_docker.py

Requires: Docker installed and running.
"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = "docker-compose.test.yml"


def run(cmd: list[str], step: str) -> int:
    print(f"\n--- {step} ---")
    print(" ".join(cmd))
    result = subprocess.run(cmd, cwd=REPO_ROOT)
    if result.returncode != 0:
        print(f"FAIL: {step} (exit code {result.returncode})", file=sys.stderr)
    return result.returncode


def main() -> int:
    if not (REPO_ROOT / COMPOSE_FILE).exists():
        print(f"ERROR: {COMPOSE_FILE} not found in {REPO_ROOT}", file=sys.stderr)
        return 1

    # Same as CI: build then run tests
    compose = ["docker", "compose", "-f", COMPOSE_FILE]
    if run(compose + ["build"], "Docker build (test image)") != 0:
        return 1
    if run(compose + ["run", "--rm", "test"], "Docker run tests (pytest)") != 0:
        return 1
    print("\nOK: Docker build and tests passed (same as CI).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
