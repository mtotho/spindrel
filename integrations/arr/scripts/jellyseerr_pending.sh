#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"

if [ -f "$REPO_DIR/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$REPO_DIR/.env"
  set +a
fi

JELLYSEERR_URL="${JELLYSEERR_URL:?Error: JELLYSEERR_URL is not set}"
JELLYSEERR_API_KEY="${JELLYSEERR_API_KEY:?Error: JELLYSEERR_API_KEY is not set}"

OUT_DIR="$REPO_DIR/data/media"
mkdir -p "$OUT_DIR"

RESPONSE=$(curl -sf --max-time 30 \
  -H "X-Api-Key: $JELLYSEERR_API_KEY" \
  "${JELLYSEERR_URL}/api/v1/request?filter=pending&take=20&sort=added")

FETCHED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

printf '{"fetched_at":"%s","data":%s}\n' "$FETCHED_AT" "$RESPONSE" > "$OUT_DIR/jellyseerr_pending.json.tmp"
mv "$OUT_DIR/jellyseerr_pending.json.tmp" "$OUT_DIR/jellyseerr_pending.json"
