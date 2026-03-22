#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

if [ -f "$REPO_DIR/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$REPO_DIR/.env"
  set +a
fi

RADARR_URL="${RADARR_URL:?Error: RADARR_URL is not set}"
RADARR_API_KEY="${RADARR_API_KEY:?Error: RADARR_API_KEY is not set}"

OUT_DIR="$REPO_DIR/data/media"
mkdir -p "$OUT_DIR"

RESPONSE=$(curl -sf --max-time 30 \
  -H "X-Api-Key: $RADARR_API_KEY" \
  "${RADARR_URL}/api/v3/movie?sortKey=dateAdded&sortDirection=descending")

FETCHED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

printf '{"fetched_at":"%s","data":%s}\n' "$FETCHED_AT" "$RESPONSE" > "$OUT_DIR/radarr_recent.json.tmp"
mv "$OUT_DIR/radarr_recent.json.tmp" "$OUT_DIR/radarr_recent.json"
