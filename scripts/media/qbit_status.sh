#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

if [ -f "$REPO_DIR/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$REPO_DIR/.env"
  set +a
fi

QBIT_URL="${QBIT_URL:?Error: QBIT_URL is not set}"
QBIT_USERNAME="${QBIT_USERNAME:?Error: QBIT_USERNAME is not set}"
QBIT_PASSWORD="${QBIT_PASSWORD:?Error: QBIT_PASSWORD is not set}"

OUT_DIR="$REPO_DIR/data/media"
mkdir -p "$OUT_DIR"

COOKIE_JAR=$(mktemp)
trap 'rm -f "$COOKIE_JAR"' EXIT

# Authenticate (cookie-based)
curl -sf --max-time 10 \
  -c "$COOKIE_JAR" \
  -d "username=${QBIT_USERNAME}&password=${QBIT_PASSWORD}" \
  "${QBIT_URL}/api/v2/auth/login" > /dev/null

# Fetch all torrents
RESPONSE=$(curl -sf --max-time 30 \
  -b "$COOKIE_JAR" \
  "${QBIT_URL}/api/v2/torrents/info")

FETCHED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

printf '{"fetched_at":"%s","data":%s}\n' "$FETCHED_AT" "$RESPONSE" > "$OUT_DIR/qbit_status.json.tmp"
mv "$OUT_DIR/qbit_status.json.tmp" "$OUT_DIR/qbit_status.json"
