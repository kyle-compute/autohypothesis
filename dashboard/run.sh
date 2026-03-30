#!/usr/bin/env bash
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB_PATH="$REPO_ROOT/dashboard/runs.db"

# Start dashboard server in background
echo "Starting dashboard server..."
uvicorn dashboard.server:app --host 127.0.0.1 --port 8000 \
  --app-dir "$REPO_ROOT" &
SERVER_PID=$!

# Give server a moment to bind
sleep 1
echo "Dashboard running at http://localhost:8000"
echo ""

# Export for train.py to pick up
export PARENT_RUN_ID=""

# Trap: kill server when script exits
cleanup() { kill "$SERVER_PID" 2>/dev/null || true; }
trap cleanup EXIT

# Agent loop — replace the echo with your actual agent invocation
# e.g.: claude --no-permissions "have a look at program.md and kick off a new experiment"
echo "Start your agent now, or run: uv run train.py"
wait "$SERVER_PID"
