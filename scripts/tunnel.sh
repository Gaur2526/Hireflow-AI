#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# scripts/tunnel.sh - expose the local backend on a public HTTPS URL so Hunar
# webhooks can reach your laptop.
#
# Runs `cloudflared tunnel --url http://localhost:8000` (a "quick tunnel" - no
# Cloudflare account, no login, no config), scrapes the generated
# https://<random>.trycloudflare.com URL out of its output, and writes it into
# backend/.env as PUBLIC_BASE_URL - replacing any existing line rather than
# appending a duplicate. Then it keeps the tunnel in the foreground; Ctrl-C
# stops it.
#
#   ./scripts/tunnel.sh              # tunnels port 8000
#   ./scripts/tunnel.sh 8080         # tunnels another port
#
# The URL changes every run, which is why this rewrites .env each time.
# -----------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/backend/.env"
PORT="${1:-${BACKEND_PORT:-8000}}"
# Explicit template: GNU mktemp rejects "-t <prefix>", which is BSD-only.
LOG="$(mktemp "${TMPDIR:-/tmp}/cloudflared-tunnel.XXXXXX")"

die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
info() { printf '\033[36m==>\033[0m %s\n' "$*"; }

# --- preflight ---------------------------------------------------------------
if ! command -v cloudflared >/dev/null 2>&1; then
  die "cloudflared is not installed.

  macOS:   brew install cloudflared
  Linux:   see https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/

  No Cloudflare account is needed for a quick tunnel."
fi

TUNNEL_PID=""
cleanup() {
  trap - INT TERM EXIT
  if [ -n "$TUNNEL_PID" ]; then
    kill -TERM "$TUNNEL_PID" 2>/dev/null || true
    # Give it a moment, then stop being polite - never hang on Ctrl-C.
    for _ in 1 2 3 4 5; do
      kill -0 "$TUNNEL_PID" 2>/dev/null || break
      sleep 1
    done
    kill -KILL "$TUNNEL_PID" 2>/dev/null || true
  fi
  rm -f "$LOG"
  info "tunnel closed. PUBLIC_BASE_URL in backend/.env now points at a dead URL - rerun this script before testing webhooks again."
}
trap cleanup INT TERM EXIT

info "starting cloudflared quick tunnel for http://localhost:${PORT} ..."
cloudflared tunnel --url "http://localhost:${PORT}" --no-autoupdate >"$LOG" 2>&1 &
TUNNEL_PID=$!

# --- wait for the URL to appear ----------------------------------------------
PUBLIC_URL=""
for _ in $(seq 1 60); do
  if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
    printf '%s\n' "--- cloudflared output ---" >&2
    cat "$LOG" >&2
    die "cloudflared exited before printing a URL (see output above)."
  fi
  PUBLIC_URL="$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -n 1 || true)"
  [ -n "$PUBLIC_URL" ] && break
  sleep 1
done

[ -n "$PUBLIC_URL" ] || { cat "$LOG" >&2; die "timed out after 60s waiting for a trycloudflare.com URL."; }

info "public URL: ${PUBLIC_URL}"

# --- write PUBLIC_BASE_URL into backend/.env ---------------------------------
mkdir -p "$(dirname "$ENV_FILE")"
[ -f "$ENV_FILE" ] || { : > "$ENV_FILE"; chmod 600 "$ENV_FILE"; info "created $ENV_FILE"; }

TMP="$(mktemp "${TMPDIR:-/tmp}/backend-env.XXXXXX")"
# Drop every existing PUBLIC_BASE_URL line (commented ones are left alone), then
# append exactly one. This is why the script can be rerun without duplicating.
grep -v -E '^[[:space:]]*PUBLIC_BASE_URL[[:space:]]*=' "$ENV_FILE" > "$TMP" || true
# Guarantee a trailing newline before appending.
[ -s "$TMP" ] && [ "$(tail -c 1 "$TMP" | wc -l)" -eq 0 ] && printf '\n' >> "$TMP"
printf 'PUBLIC_BASE_URL=%s\n' "$PUBLIC_URL" >> "$TMP"
cat "$TMP" > "$ENV_FILE"
rm -f "$TMP"

cat <<MSG

  PUBLIC_BASE_URL=${PUBLIC_URL}
  written to backend/.env

  NEXT STEP: restart the backend so it picks up the new value.
    - running ./scripts/dev.sh or 'make dev'? Ctrl-C it and start it again.
      (uvicorn --reload watches code, NOT .env, so a restart is required.)
    - webhooks Hunar will call: ${PUBLIC_URL}/api/webhooks/hunar/{status,recording,result,summary}
    - sanity check: curl ${PUBLIC_URL}/healthz

  Leave this terminal open - closing it kills the tunnel.

MSG

wait "$TUNNEL_PID" 2>/dev/null || true
