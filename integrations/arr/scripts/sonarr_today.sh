#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"

if [ -f "$REPO_DIR/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$REPO_DIR/.env"
  set +a
fi

SONARR_URL="${SONARR_URL:?Error: SONARR_URL is not set}"
SONARR_API_KEY="${SONARR_API_KEY:?Error: SONARR_API_KEY is not set}"

OUT_DIR="$REPO_DIR/data/media"
mkdir -p "$OUT_DIR"

TODAY="$(date +%Y-%m-%d)"
TOMORROW="$(date -d "+1 day" +%Y-%m-%d 2>/dev/null || date -v+1d +%Y-%m-%d)"

RESPONSE=$(curl -sf --max-time 30 \
  -H "X-Api-Key: $SONARR_API_KEY" \
  "${SONARR_URL}/api/v3/calendar?start=${TODAY}&end=${TOMORROW}")

FETCHED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

printf '{"fetched_at":"%s","data":%s}\n' "$FETCHED_AT" "$RESPONSE" > "$OUT_DIR/sonarr_today.json.tmp"
mv "$OUT_DIR/sonarr_today.json.tmp" "$OUT_DIR/sonarr_today.json"
