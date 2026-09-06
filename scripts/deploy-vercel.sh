#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# scripts/deploy-vercel.sh - non-interactive Vercel deploy, driven purely by
# environment variables (no login prompt, safe in CI), printing the URL it got.
#
#   VERCEL_TOKEN        (required)  https://vercel.com/account/tokens
#   VERCEL_ORG_ID       (optional)  needed in CI / on a clean checkout
#   VERCEL_PROJECT_ID   (optional)  ditto - both are in .vercel/project.json
#                                   after the first local `vercel link`
#   VERCEL_SCOPE        (optional)  team slug
#   TARGET              (optional)  production (default) | preview
#
#   VERCEL_TOKEN=xxx ./scripts/deploy-vercel.sh              # frontend (default)
#   VERCEL_TOKEN=xxx ./scripts/deploy-vercel.sh backend      # FastAPI backend
#
# Reminder: Vercel's filesystem is ephemeral. A backend deployed here MUST use
# Postgres (Neon) - SQLite is wiped between invocations - and should run with
# ENABLE_CALL_POLLER=false, because serverless functions have no long-lived
# background loop; rely on Hunar webhooks instead.
# -----------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WHAT="${1:-frontend}"
TARGET="${TARGET:-production}"

die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
info() { printf '\033[36m==>\033[0m %s\n' "$*"; }

case "$WHAT" in
  frontend) DIR="$ROOT/frontend" ;;
  backend)  DIR="$ROOT/backend" ;;
  *) die "unknown target '$WHAT' - use 'frontend' or 'backend'." ;;
esac

# --- preflight ---------------------------------------------------------------
if [ -z "${VERCEL_TOKEN:-}" ]; then
  die "VERCEL_TOKEN is not set.

  1. Create a token: https://vercel.com/account/tokens
  2. Export it (never commit it):
       export VERCEL_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxx
  3. Rerun: ./scripts/deploy-vercel.sh ${WHAT}"
fi

if ! command -v vercel >/dev/null 2>&1; then
  die "the Vercel CLI is not installed.

  Install it with:
    npm i -g vercel

  (or run it without installing:  npx vercel --version)"
fi

[ -f "$DIR/vercel.json" ] || die "$DIR/vercel.json is missing - nothing to deploy."

if [ "$WHAT" = "backend" ] && [ ! -d "$ROOT/backend/.vercel" ] \
   && { [ -z "${VERCEL_ORG_ID:-}" ] || [ -z "${VERCEL_PROJECT_ID:-}" ]; }; then
  die "this checkout is not linked to a Vercel project yet.

  Either link it once, interactively:
    cd backend && vercel link

  or export the ids from an existing project (found in .vercel/project.json):
    export VERCEL_ORG_ID=team_xxx VERCEL_PROJECT_ID=prj_xxx"
fi

# The CLI reads VERCEL_TOKEN from the environment: passing --token would put the
# secret in argv, where any other process on the machine can read it off `ps`.
ARGS=(--yes)
[ -n "${VERCEL_SCOPE:-}" ] && ARGS+=(--scope "$VERCEL_SCOPE")
[ "$TARGET" = "production" ] && ARGS+=(--prod)

info "deploying ${WHAT} (${DIR}) to ${TARGET} ..."

# --prod prints the deployment URL on stdout and progress on stderr, so the last
# stdout line is the URL.
OUT="$(cd "$DIR" && vercel deploy "${ARGS[@]}")" || die "vercel deploy failed (see output above)."
URL="$(printf '%s\n' "$OUT" | grep -Eo 'https://[^[:space:]]+' | tail -n 1)"

[ -n "$URL" ] || die "deploy finished but no URL was found in the CLI output:
$OUT"

cat <<MSG

  Deployed ${WHAT} -> ${URL}

MSG

if [ "$WHAT" = "frontend" ]; then
  cat <<MSG
  Set this in the Vercel project (Settings -> Environment Variables), then redeploy:
    NEXT_PUBLIC_API_BASE_URL = https://<your-backend>.onrender.com

  And add ${URL} to CORS_ORIGINS on the backend.

MSG
else
  cat <<MSG
  Set these in the Vercel project (Settings -> Environment Variables):
    DATABASE_URL         postgresql+psycopg://...neon.tech/neondb?sslmode=require
    HUNAR_API_KEY        (secret)
    PUBLIC_BASE_URL      ${URL}
    CORS_ORIGINS         https://<your-frontend>.vercel.app
    ENABLE_CALL_POLLER   false      # serverless: no background loop, use webhooks

  Health check: ${URL}/healthz

MSG
fi
