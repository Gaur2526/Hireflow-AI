#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# scripts/deploy-render.sh - trigger a non-interactive Render deploy of the
# backend service and print the resulting URL.
#
# Driven entirely by environment variables - no prompts, safe in CI:
#   RENDER_API_KEY      (required)  https://dashboard.render.com/settings#api-keys
#   RENDER_SERVICE_ID   (optional)  srv-xxxxxxxx. If unset, the script looks the
#                                   service up by name via the Render API.
#   RENDER_SERVICE_NAME (optional)  defaults to the name in render.yaml.
#
#   RENDER_API_KEY=rnd_xxx ./scripts/deploy-render.sh
#
# IMPORTANT: the Render CLI cannot apply a Blueprint. The FIRST deploy must be
# done once in the dashboard: New -> Blueprint -> select this repo (it reads
# render.yaml). After that, this script redeploys that service on demand.
# -----------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="${RENDER_SERVICE_NAME:-hireflow-ai-api}"
API="https://api.render.com/v1"

die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
info() { printf '\033[36m==>\033[0m %s\n' "$*"; }

# --- preflight ---------------------------------------------------------------
if [ -z "${RENDER_API_KEY:-}" ]; then
  die "RENDER_API_KEY is not set.

  1. Create a key: https://dashboard.render.com/settings#api-keys
  2. Export it (do NOT commit it):
       export RENDER_API_KEY=rnd_xxxxxxxxxxxxxxxx
  3. Rerun: ./scripts/deploy-render.sh"
fi

command -v curl >/dev/null 2>&1 || die "curl is required but not installed."
command -v python3 >/dev/null 2>&1 || die "python3 is required (used to parse the API's JSON)."

if ! command -v render >/dev/null 2>&1; then
  info "render CLI not found - using the REST API directly (that is fine)."
  info "To install the CLI anyway:  curl -fsSL https://raw.githubusercontent.com/render-oss/cli/refs/heads/main/bin/install.sh | sh"
  info "NOTE: 'brew install render' installs an UNRELATED package - do not use it."
fi

[ -f "$ROOT/render.yaml" ] || die "render.yaml not found at repo root - are you in the right repo?"

api() {
  # api <METHOD> <PATH> [BODY]
  curl -fsS -X "$1" "${API}$2" \
    -H "Authorization: Bearer ${RENDER_API_KEY}" \
    -H "Accept: application/json" \
    -H "Content-Type: application/json" \
    ${3:+-d "$3"}
}

jqp() { python3 -c "import json,sys;$1" ; }

# --- resolve the service id --------------------------------------------------
SERVICE_ID="${RENDER_SERVICE_ID:-}"

if [ -z "$SERVICE_ID" ]; then
  info "looking up service '${SERVICE_NAME}' ..."
  RESP="$(api GET "/services?name=${SERVICE_NAME}&limit=20" || die "Render API call failed - is RENDER_API_KEY valid?")"
  SERVICE_ID="$(printf '%s' "$RESP" | jqp "
d=json.load(sys.stdin)
items=[x.get('service',x) for x in d] if isinstance(d,list) else []
print(next((s['id'] for s in items if s.get('name')=='${SERVICE_NAME}'),''))")"
fi

if [ -z "$SERVICE_ID" ]; then
  die "no Render service named '${SERVICE_NAME}' exists yet.

  Blueprints cannot be applied from the CLI/API, so create it once by hand:
    1. https://dashboard.render.com/select-repo?type=blueprint
    2. Pick this repository - Render reads render.yaml.
    3. Fill in the secrets it prompts for (they are declared sync: false).
    4. Rerun this script for every deploy after that.

  Already created it under another name? Pass it explicitly:
    RENDER_SERVICE_NAME=my-service ./scripts/deploy-render.sh
    RENDER_SERVICE_ID=srv-xxxxxxxx ./scripts/deploy-render.sh"
fi

info "service: ${SERVICE_NAME} (${SERVICE_ID})"

# --- trigger the deploy ------------------------------------------------------
info "triggering deploy ..."
DEPLOY="$(api POST "/services/${SERVICE_ID}/deploys" '{"clearCache":"do_not_clear"}')" \
  || die "deploy request rejected by the Render API."

DEPLOY_ID="$(printf '%s' "$DEPLOY" | jqp "print(json.load(sys.stdin).get('id',''))")"
info "deploy id: ${DEPLOY_ID:-unknown} (build logs stream in the dashboard)"

# --- print the URL -----------------------------------------------------------
SVC="$(api GET "/services/${SERVICE_ID}")"
URL="$(printf '%s' "$SVC" | jqp "
d=json.load(sys.stdin)
d=d.get('service',d)
sd=d.get('serviceDetails') or {}
print(sd.get('url') or 'https://%s.onrender.com' % d.get('name',''))")"

cat <<MSG

  Deploy queued.

  URL:     ${URL}
  Health:  ${URL}/healthz
  Docs:    ${URL}/docs
  Logs:    https://dashboard.render.com/web/${SERVICE_ID}/logs

  Reminders for the free plan:
    * set PUBLIC_BASE_URL=${URL} in the service's env vars (webhooks need it)
    * no persistent disk - point DATABASE_URL at Neon, SQLite will not survive
    * the service sleeps after ~15 min idle; the next request takes ~1 min

MSG
