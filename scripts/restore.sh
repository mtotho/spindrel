#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Load .env if present — only simple KEY=VALUE lines (skip JSON arrays, parens, etc.)
if [ -f "$REPO_DIR/.env" ]; then
  while IFS='=' read -r key val; do
    [[ -z "$key" || "$key" =~ ^[[:space:]]*# ]] && continue
    key="${key%%[[:space:]]}"
    val="${val#[[:space:]]}"
    val="${val#\"}" ; val="${val%\"}"
    val="${val#\'}" ; val="${val%\'}"
    export "$key=$val" 2>/dev/null || true
  done < "$REPO_DIR/.env"
fi

# ── Config ──────────────────────────────────────────────────────────────────
BACKUP_DIR="${BACKUP_DIR:-${REPO_DIR}/backups}"
RCLONE_REMOTE="${RCLONE_REMOTE:?Error: RCLONE_REMOTE is not set. Example: export RCLONE_REMOTE=:s3:your-bucket-name}"
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
    --s3-provider AWS \
    --s3-access-key-id "$AWS_ACCESS_KEY_ID" \
    --s3-secret-access-key "$AWS_SECRET_ACCESS_KEY" \
    --s3-region "${AWS_REGION:-us-east-1}" \
    --s3-no-check-bucket \
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
if [[ -d "$RESTORE_DIR/tools" ]] && ls "$RESTORE_DIR/tools/"* &>/dev/null; then
  mkdir -p "$REPO_DIR/tools"
  cp -r "$RESTORE_DIR/tools/"* "$REPO_DIR/tools/"
fi
mkdir -p "$REPO_DIR/config/searxng"
cp "$RESTORE_DIR/config/searxng/settings.yml" "$REPO_DIR/config/searxng/settings.yml"

# Restore workspace data if present in backup — detect the workspace dir name from the archive
_WS_BASE="${WORKSPACE_BASE_DIR:-${HOME}/.spindrel-workspaces}"
_WS_TARGET="$(eval echo "$_WS_BASE")"
# The archive may contain .agent-workspaces, .spindrel-workspaces, or .thoth-workspaces
for _ws_candidate in .agent-workspaces .spindrel-workspaces .thoth-workspaces; do
  if [[ -d "$RESTORE_DIR/$_ws_candidate" ]]; then
    echo "[restore] Restoring workspaces from $_ws_candidate to $_WS_TARGET …"
    mkdir -p "$_WS_TARGET"
    cp -r "$RESTORE_DIR/$_ws_candidate/"* "$_WS_TARGET/"
    break
  fi
done

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

# ── 6. Start backing services (agent server runs natively via systemd) ──────
echo "[restore] Starting backing services …"
docker compose -f "$REPO_DIR/docker-compose.yml" up -d postgres searxng playwright
# Agent server runs natively — use 'spindrel restart' or './scripts/install-service.sh' to set it up.

# ── 7. Cleanup ──────────────────────────────────────────────────────────────
rm -rf "$RESTORE_DIR"

echo "[restore] Done at $(date)"
echo "[restore] Run ./scripts/install-service.sh to install the agent server as a systemd service."
