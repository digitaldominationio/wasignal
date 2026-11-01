#!/usr/bin/env bash
# Start the API and the web app together. Ctrl-C stops both.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -x "apps/api/.venv/bin/uvicorn" ]; then
  echo "Missing venv. Run: make api-install" >&2
  exit 1
fi
if [ ! -d "apps/web/node_modules" ]; then
  echo "Missing web deps. Run: make web-install" >&2
  exit 1
fi

cleanup() {
  kill 0 2>/dev/null || true
}
trap cleanup EXIT INT TERM

(cd apps/api && .venv/bin/uvicorn app.main:app --reload --port 8000) &
(cd apps/web && npm run dev) &

wait
