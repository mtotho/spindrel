#!/usr/bin/env bash
set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────────────
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-${REPO_DIR}/backups}"
RCLONE_REMOTE="${RCLONE_REMOTE:?Error: RCLONE_REMOTE is not set. Example: export RCLONE_REMOTE=s3:your-bucket-name}"
RESTORE_DIR="${REPO_DIR}/restore"

usage() {
  echo "Usage: $0 [path-to-archive.tar.gz]"
  echo ""
  echo "If no archive is given, the latest backup is pulled from the rclone remote."
  exit 1
}

# ── 1. Determine which archive to restore ──────────────────────────────────
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
fi

if [[ -n "${1:-}" ]]; then
  ARCHIVE="$1"
  if [[ ! -f "$ARCHIVE" ]]; then
    echo "[restore] File not found: $ARCHIVE" >&2
    exit 1
  fi
else
  echo "[restore] Pulling latest backup from ${RCLONE_REMOTE} …"
  mkdir -p "$BACKUP_DIR"
  rclone copy "$RCLONE_REMOTE/" "$BACKUP_DIR/" \
    --include "agent-backup-*.tar.gz" \
    --max-depth 1
  # shellcheck disable=SC2012
  ARCHIVE="$(ls -t "$BACKUP_DIR"/agent-backup-*.tar.gz 2>/dev/null | head -1)"
  if [[ -z "$ARCHIVE" ]]; then
    echo "[restore] No backup archives found." >&2
    exit 1
  fi
  echo "[restore] Using $ARCHIVE"
fi

# ── 2. Extract ──────────────────────────────────────────────────────────────
echo "[restore] Extracting …"
rm -rf "$RESTORE_DIR"
mkdir -p "$RESTORE_DIR"
tar xzf "$ARCHIVE" -C "$RESTORE_DIR"

# ── 3. Restore config files ────────────────────────────────────────────────
echo "[restore] Restoring config files …"
cp "$RESTORE_DIR/.env"      "$REPO_DIR/.env"
cp "$RESTORE_DIR/mcp.yaml"  "$REPO_DIR/mcp.yaml"
cp -r "$RESTORE_DIR/bots/"*   "$REPO_DIR/bots/"
cp -r "$RESTORE_DIR/skills/"* "$REPO_DIR/skills/"
mkdir -p "$REPO_DIR/config/searxng"
cp "$RESTORE_DIR/config/searxng/settings.yml" "$REPO_DIR/config/searxng/settings.yml"

# ── 4. Start postgres and wait for healthy ──────────────────────────────────
echo "[restore] Starting postgres …"
docker compose -f "$REPO_DIR/docker-compose.yml" up -d postgres

echo "[restore] Waiting for postgres to be ready …"
for i in $(seq 1 30); do
  if docker compose -f "$REPO_DIR/docker-compose.yml" exec -T postgres \
       pg_isready -U agent -d agentdb > /dev/null 2>&1; then
    break
  fi
  if [[ $i -eq 30 ]]; then
    echo "[restore] Postgres did not become ready in time." >&2
    exit 1
  fi
  sleep 1
done

# ── 5. Restore the database ────────────────────────────────────────────────
echo "[restore] Restoring database …"
# shellcheck disable=SC2086
DUMP_FILE="$(ls "$RESTORE_DIR"/agentdb_*.dump 2>/dev/null | head -1)"
if [[ -z "$DUMP_FILE" ]]; then
  echo "[restore] No dump file found in archive." >&2
  exit 1
fi

docker compose -f "$REPO_DIR/docker-compose.yml" exec -T postgres \
  pg_restore -U agent -d agentdb --clean --if-exists --no-owner < "$DUMP_FILE"

# ── 6. Restart the full stack ───────────────────────────────────────────────
echo "[restore] Starting full stack …"
docker compose -f "$REPO_DIR/docker-compose.yml" up -d

# ── 7. Cleanup ──────────────────────────────────────────────────────────────
rm -rf "$RESTORE_DIR"

echo "[restore] Done at $(date)"
echo "[restore] Verify with: docker compose logs agent-server --tail 50"
