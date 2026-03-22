#!/usr/bin/env bash
set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────────────
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-${REPO_DIR}/backups}"
RCLONE_REMOTE="${RCLONE_REMOTE:-s3:thoth-server-backups}"
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
