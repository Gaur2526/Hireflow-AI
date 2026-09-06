#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# scripts/dev.sh - run the whole app locally in one terminal.
#
# Starts the FastAPI backend (uvicorn --reload, :8000) and the Next.js dev
# server (:3000) side by side and streams both sets of logs. Ctrl-C (SIGINT)
# tears down both processes and everything they spawned.
#
# Preflight: verifies backend/.venv and frontend/node_modules exist and prints
# the exact command to fix each if not.
#
#   ./scripts/dev.sh                       # defaults 8000 / 3000
#   BACKEND_PORT=8080 ./scripts/dev.sh     # override either port
#
# Written for bash 3.2 (the /bin/bash that ships with macOS) - no `wait -n`.
# -----------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
info() { printf '\033[36m==>\033[0m %s\n' "$*"; }

# --- preflight ---------------------------------------------------------------
if [ ! -x "$BACKEND/.venv/bin/uvicorn" ]; then
  die "backend virtualenv missing or incomplete at backend/.venv

  Fix it with:
    python3.12 -m venv backend/.venv
    backend/.venv/bin/pip install -r backend/requirements-dev.txt

  (or just: make install)"
fi

if [ ! -d "$FRONTEND/node_modules" ]; then
  die "frontend dependencies are not installed (frontend/node_modules missing)

  Fix it with:
    npm --prefix frontend ci

  (or just: make install)"
fi

[ -f "$BACKEND/.env" ] || info "backend/.env not found - running on defaults. \`cp .env.example backend/.env\` to add keys."

# Job control ON so each background job becomes its own process group and we can
# signal the whole tree (next dev forks children) with kill -TERM -PGID.
set -m

BACKEND_PID=""
FRONTEND_PID=""

stop_one() {
  local pid="$1"
  [ -n "$pid" ] || return 0
  kill -TERM "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
}

cleanup() {
  trap - INT TERM EXIT
  info "shutting down..."
  stop_one "$FRONTEND_PID"
  stop_one "$BACKEND_PID"
  wait 2>/dev/null || true
  info "stopped."
}
trap cleanup INT TERM EXIT

# --- backend -----------------------------------------------------------------
info "backend  -> http://localhost:${BACKEND_PORT}   (OpenAPI docs at /docs)"
( cd "$BACKEND" && exec ./.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port "$BACKEND_PORT" ) &
BACKEND_PID=$!

# --- frontend ----------------------------------------------------------------
info "frontend -> http://localhost:${FRONTEND_PORT}"
( cd "$FRONTEND" && exec npm run dev -- --port "$FRONTEND_PORT" ) &
FRONTEND_PID=$!

info "both running. Ctrl-C to stop."

# Poll instead of `wait -n` (bash 3.2). Exit as soon as either side dies so a
# crashed backend does not leave half a stack running.
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 1
done

info "one process exited - tearing down the other."
