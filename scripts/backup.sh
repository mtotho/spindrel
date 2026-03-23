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
TAR_ARGS=( -C "$BACKUP_DIR" "$DUMP_FILE"
           -C "$REPO_DIR"   .env bots skills mcp.yaml config/searxng/settings.yml )

# Include workspace data if it exists
WORKSPACE_DIR="${HOME}/.agent-workspaces"
if [[ -d "$WORKSPACE_DIR" ]]; then
  TAR_ARGS+=( -C "$HOME" .agent-workspaces )
  echo "[backup] Including workspaces from $WORKSPACE_DIR"
fi

tar czf "$BACKUP_DIR/$ARCHIVE" "${TAR_ARGS[@]}"

rm "$BACKUP_DIR/$DUMP_FILE"

# ── 3. Upload to remote storage ────────────────────────────────────────────
echo "[backup] Uploading to ${RCLONE_REMOTE} …"
rclone copy "$BACKUP_DIR/$ARCHIVE" "$RCLONE_REMOTE/" \
  --s3-provider AWS \
  --s3-access-key-id "$AWS_ACCESS_KEY_ID" \
  --s3-secret-access-key "$AWS_SECRET_ACCESS_KEY" \
  --s3-region "${AWS_REGION:-us-east-1}" \
  --s3-no-check-bucket

# ── 4. Prune old local backups (keep $LOCAL_KEEP most recent) ───────────────
# shellcheck disable=SC2012
ls -t "$BACKUP_DIR"/agent-backup-*.tar.gz 2>/dev/null \
  | tail -n +$((LOCAL_KEEP + 1)) \
  | xargs rm -f 2>/dev/null || true

echo "[backup] Done — $ARCHIVE uploaded at $(date)"
