#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Start the OSINT Correlation Engine.
# Binds to 0.0.0.0 so it's reachable from outside the container (your phone via
# the preview tunnel). PORT defaults to 8000 (override with PORT=xxxx ./run.sh).
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")"

# Use the project virtualenv if present.
[ -d .venv ] && source .venv/bin/activate

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

echo "▸ OSINT engine on http://${HOST}:${PORT}"
exec uvicorn app.main:app --host "$HOST" --port "$PORT" "$@"
