#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Load .env if present — only simple KEY=VALUE lines (skip JSON arrays, parens, etc.)
if [ -f "$REPO_DIR/.env" ]; then
  while IFS='=' read -r key val; do
    # Skip comments, blank lines, and lines where the value contains bash-hostile chars
    [[ -z "$key" || "$key" =~ ^[[:space:]]*# ]] && continue
    key="${key%%[[:space:]]}"
    val="${val#[[:space:]]}"
    # Strip surrounding quotes
    val="${val#\"}" ; val="${val%\"}"
    val="${val#\'}" ; val="${val%\'}"
    export "$key=$val" 2>/dev/null || true
  done < "$REPO_DIR/.env"
fi

# ── Config ──────────────────────────────────────────────────────────────────
BACKUP_DIR="${BACKUP_DIR:-${REPO_DIR}/backups}"
RCLONE_REMOTE="${RCLONE_REMOTE:?Error: RCLONE_REMOTE is not set. Example: export RCLONE_REMOTE=:s3:your-bucket-name}"
LOCAL_KEEP="${LOCAL_KEEP:-7}"

# Encryption: prefer dedicated BACKUP_ENCRYPTION_KEY (if set) to keep backup
# decryption separate from the live ENCRYPTION_KEY; otherwise fall back to
# ENCRYPTION_KEY. ENCRYPTION_STRICT (default true) makes a missing key a
# fatal error instead of silently producing plaintext archives.
BACKUP_KEY="${BACKUP_ENCRYPTION_KEY:-${ENCRYPTION_KEY:-}}"
ENCRYPTION_STRICT="${ENCRYPTION_STRICT:-true}"

STAMP="$(date +%Y%m%d_%H%M%S)"
DUMP_FILE="agentdb_${STAMP}.dump"
ARCHIVE="agent-backup-${STAMP}.tar.gz"
ARCHIVE_ENC="${ARCHIVE}.enc"

mkdir -p "$BACKUP_DIR"

if [[ -z "$BACKUP_KEY" ]]; then
  if [[ "$ENCRYPTION_STRICT" == "true" ]]; then
    echo "[backup] FATAL: no ENCRYPTION_KEY / BACKUP_ENCRYPTION_KEY set and ENCRYPTION_STRICT=true." >&2
    echo "[backup] Backups would contain plaintext .env (with API keys/OAuth tokens) and a Postgres dump" >&2
    echo "[backup] that may include decrypted secrets. Refusing to run." >&2
    echo "[backup] Set BACKUP_ENCRYPTION_KEY (recommended — separate from live key) or ENCRYPTION_KEY," >&2
    echo "[backup] or pass ENCRYPTION_STRICT=false explicitly to opt into plaintext backups (dev only)." >&2
    exit 2
  fi
  echo "[backup] WARNING: no encryption key configured; archive will be PLAINTEXT (ENCRYPTION_STRICT=false)." >&2
fi

# ── 1. Postgres dump via running container ──────────────────────────────────
echo "[backup] Dumping postgres …"
docker compose -f "$REPO_DIR/docker-compose.yml" exec -T postgres \
  pg_dump -U agent -Fc agentdb > "$BACKUP_DIR/$DUMP_FILE"

# ── 2. Bundle dump + config files into a tarball ────────────────────────────
echo "[backup] Creating archive …"
TAR_ARGS=( -C "$BACKUP_DIR" "$DUMP_FILE"
           -C "$REPO_DIR"   .env bots skills tools integrations )

# Include mcp.yaml if it exists
[[ -f "$REPO_DIR/mcp.yaml" ]] && TAR_ARGS+=( -C "$REPO_DIR" mcp.yaml )

# Include workspace data if it exists
# Use WORKSPACE_BASE_DIR from .env, fall back to ~/.spindrel-workspaces
_WS_BASE="${WORKSPACE_BASE_DIR:-${HOME}/.spindrel-workspaces}"
WORKSPACE_DIR="$(eval echo "$_WS_BASE")"   # expand ~ if present
if [[ -d "$WORKSPACE_DIR" ]]; then
  _WS_PARENT="$(dirname "$WORKSPACE_DIR")"
  _WS_NAME="$(basename "$WORKSPACE_DIR")"
  TAR_ARGS+=( -C "$_WS_PARENT" "$_WS_NAME" )
  echo "[backup] Including workspaces from $WORKSPACE_DIR"
fi

tar czf "$BACKUP_DIR/$ARCHIVE" "${TAR_ARGS[@]}"

rm "$BACKUP_DIR/$DUMP_FILE"

# ── 2b. Encrypt the archive (when a key is configured) ────────────────────
# AES-256-CBC with PBKDF2 (100k rounds) + per-archive salt. The key is
# passed via -pass file:<tempfile> so it never appears in argv / process
# listing. The plaintext tarball is removed once the encrypted output is
# verified to exist.
UPLOAD_FILE="$ARCHIVE"
if [[ -n "$BACKUP_KEY" ]]; then
  echo "[backup] Encrypting archive (AES-256-CBC + PBKDF2) …"
  KEY_FILE="$(mktemp)"
  chmod 600 "$KEY_FILE"
  # shellcheck disable=SC2064
  trap "rm -f '$KEY_FILE'" EXIT
  printf '%s' "$BACKUP_KEY" > "$KEY_FILE"
  openssl enc -aes-256-cbc -salt -pbkdf2 -iter 100000 \
    -in "$BACKUP_DIR/$ARCHIVE" \
    -out "$BACKUP_DIR/$ARCHIVE_ENC" \
    -pass "file:$KEY_FILE"
  if [[ ! -s "$BACKUP_DIR/$ARCHIVE_ENC" ]]; then
    echo "[backup] FATAL: encrypted archive missing or empty — aborting." >&2
    rm -f "$BACKUP_DIR/$ARCHIVE_ENC"
    exit 3
  fi
  rm -f "$BACKUP_DIR/$ARCHIVE"
  rm -f "$KEY_FILE"
  trap - EXIT
  UPLOAD_FILE="$ARCHIVE_ENC"
fi

# ── 3. Upload to remote storage ────────────────────────────────────────────
echo "[backup] Uploading to ${RCLONE_REMOTE} …"
rclone copy "$BACKUP_DIR/$UPLOAD_FILE" "$RCLONE_REMOTE/" \
  --s3-provider AWS \
  --s3-access-key-id "$AWS_ACCESS_KEY_ID" \
  --s3-secret-access-key "$AWS_SECRET_ACCESS_KEY" \
  --s3-region "${AWS_REGION:-us-east-1}" \
  --s3-no-check-bucket

# ── 4. Prune old local backups (keep $LOCAL_KEEP most recent) ───────────────
# Encrypted (.tar.gz.enc) and plaintext (.tar.gz) archives are pruned
# together so a transition between modes does not leave an unbounded mix.
# shellcheck disable=SC2012
ls -t "$BACKUP_DIR"/agent-backup-*.tar.gz "$BACKUP_DIR"/agent-backup-*.tar.gz.enc 2>/dev/null \
  | tail -n +$((LOCAL_KEEP + 1)) \
  | xargs rm -f 2>/dev/null || true

echo "[backup] Done — $UPLOAD_FILE uploaded at $(date)"
