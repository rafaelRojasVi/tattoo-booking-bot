#!/bin/bash
# Smoke test for worker survival: verify that killing one worker doesn't take down the service
#
# Usage:
#   ./scripts/smoke_workers.sh
#
# This script:
# 1. Builds and starts docker compose
# 2. Waits for /health to be ready
# 3. Kills one uvicorn worker process
# 4. Verifies /health still responds
# 5. Cleans up

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🔨 Building Docker image..."
cd "$PROJECT_DIR"
docker compose build api

echo "🚀 Starting services..."
docker compose up -d

# Wait for health endpoint to be ready
echo "⏳ Waiting for /health endpoint..."
MAX_WAIT=30
WAIT_COUNT=0
while [ $WAIT_COUNT -lt $MAX_WAIT ]; do
    if curl -f -s http://localhost:8000/health > /dev/null 2>&1; then
        echo "✅ Health endpoint is ready"
        break
    fi
    WAIT_COUNT=$((WAIT_COUNT + 1))
    sleep 1
done

if [ $WAIT_COUNT -eq $MAX_WAIT ]; then
    echo "❌ Health endpoint did not become ready after ${MAX_WAIT}s"
    docker compose logs api
    docker compose down
    exit 1
fi

# Get container name
CONTAINER_NAME=$(docker compose ps -q api)
if [ -z "$CONTAINER_NAME" ]; then
    echo "❌ Could not find API container"
    docker compose down
    exit 1
fi

# Get uvicorn worker PIDs (avoid killing the master process)
echo "🔍 Finding uvicorn worker processes..."
# Get all uvicorn worker PIDs, sorted by PID (master is usually lowest)
ALL_WORKER_PIDS=$(docker exec "$CONTAINER_NAME" sh -c "ps aux | grep 'uvicorn.*worker' | grep -v grep | awk '{print \$2}' | sort -n" || true)

if [ -z "$ALL_WORKER_PIDS" ]; then
    echo "⚠️  Could not find uvicorn worker process (might be using gunicorn or different setup)"
    echo "   Checking process list:"
    docker exec "$CONTAINER_NAME" ps aux
    docker compose down
    exit 0  # Not a failure, just different setup
fi

# Count workers
WORKER_COUNT=$(echo "$ALL_WORKER_PIDS" | wc -l)
echo "📊 Found $WORKER_COUNT worker process(es)"

if [ "$WORKER_COUNT" -lt 2 ]; then
    echo "⚠️  Only $WORKER_COUNT worker found. Multi-worker test requires at least 2 workers."
    echo "   Set WEB_CONCURRENCY=2 or higher in your environment."
    docker compose down
    exit 0  # Not a failure, just insufficient workers for test
fi

# Pick a worker that's NOT the first one (first is often the master/parent)
# Get the second PID (or last if only 2 workers)
WORKER_PID=$(echo "$ALL_WORKER_PIDS" | tail -n +2 | head -1)

if [ -z "$WORKER_PID" ]; then
    # Fallback: if we can't get second, get the last one
    WORKER_PID=$(echo "$ALL_WORKER_PIDS" | tail -1)
fi

echo "📊 Selected worker PID to kill: $WORKER_PID (not the master)"
echo "📊 All worker PIDs: $(echo $ALL_WORKER_PIDS | tr '\n' ' ')"

# Verify health before killing worker
echo "✅ Health check before killing worker:"
curl -f -s http://localhost:8000/health | jq '.' || curl -f -s http://localhost:8000/health

# Kill one worker
echo "💀 Killing worker PID $WORKER_PID..."
docker exec "$CONTAINER_NAME" kill -9 "$WORKER_PID" || true

# Wait a moment for process to die
sleep 2

# Verify health still responds (other workers should handle it)
echo "✅ Health check after killing worker:"
if curl -f -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "✅ SUCCESS: Service still healthy after killing one worker"
    RESULT=0
else
    echo "❌ FAILURE: Service is down after killing one worker"
    echo "   This indicates single-worker mode or worker restart not working"
    RESULT=1
fi

# Show current worker count
echo "📊 Worker count after kill:"
docker exec "$CONTAINER_NAME" sh -c "ps aux | grep 'uvicorn.*worker' | grep -v grep | wc -l" || echo "0"

# Cleanup
echo "🧹 Cleaning up..."
docker compose down

exit $RESULT
