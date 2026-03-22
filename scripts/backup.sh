#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Load .env if present and vars not already exported
if [ -f "$REPO_DIR/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$REPO_DIR/.env"
  set +a
fi

# ── Config ──────────────────────────────────────────────────────────────────
BACKUP_DIR="${BACKUP_DIR:-${REPO_DIR}/backups}"
RCLONE_REMOTE="${RCLONE_REMOTE:?Error: RCLONE_REMOTE is not set. Example: export RCLONE_REMOTE=:s3:your-bucket-name}"
LOCAL_KEEP="${LOCAL_KEEP:-7}"

# ── S3 credentials via env vars (no rclone config file needed) ───────────
export RCLONE_S3_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:?Error: AWS_ACCESS_KEY_ID not set}"
export RCLONE_S3_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:?Error: AWS_SECRET_ACCESS_KEY not set}"
export RCLONE_S3_REGION="${AWS_REGION:-us-east-1}"
export RCLONE_S3_PROVIDER="AWS"
export RCLONE_S3_ENV_AUTH="false"
STAMP="$(date +%Y%m%d_%H%M%S)"
DUMP_FILE="agentdb_${STAMP}.dump"
ARCHIVE="agent-backup-${STAMP}.tar.gz"

mkdir -p "$BACKUP_DIR"

# ── 1. Postgres dump via running container ──────────────────────────────────
echo "[backup] Dumping postgres …"
docker compose -f "$REPO_DIR/docker-compose.yml" exec -T postgres \
  pg_dump -U agent -Fc agentdb > "$BACKUP_DIR/$DUMP_FILE"

# ── 2. Bundle dump + config files into a tarball ────────────────────────────
echo "[backup] Creating archive …"
tar czf "$BACKUP_DIR/$ARCHIVE" \
  -C "$BACKUP_DIR" "$DUMP_FILE" \
  -C "$REPO_DIR"   .env bots skills mcp.yaml config/searxng/settings.yml

rm "$BACKUP_DIR/$DUMP_FILE"

# ── 3. Upload to remote storage ────────────────────────────────────────────
echo "[backup] Uploading to ${RCLONE_REMOTE} …"
rclone copy "$BACKUP_DIR/$ARCHIVE" "$RCLONE_REMOTE/"

# ── 4. Prune old local backups (keep $LOCAL_KEEP most recent) ───────────────
# shellcheck disable=SC2012
ls -t "$BACKUP_DIR"/agent-backup-*.tar.gz 2>/dev/null \
  | tail -n +$((LOCAL_KEEP + 1)) \
  | xargs rm -f 2>/dev/null || true

echo "[backup] Done — $ARCHIVE uploaded at $(date)"
