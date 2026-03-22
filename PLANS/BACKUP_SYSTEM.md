---
status: draft
last_updated: 2026-03-22
owner: mtoth
summary: >
  Scheduled Postgres dumps + app state backups, offloaded to Google Drive or S3.
  Also serves as the migration path for moving the install from localhost to a new server.
---

# Backup System

## Goals

1. **Automated scheduled Postgres dumps** — `pg_dump` on a cron, no manual intervention
2. **Offsite storage** — push dumps + config to Google Drive or S3
3. **Documented restore procedure** — tested, not theoretical
4. **Migration path** — backup on localhost → restore on new server, same stack

---

## What to Back Up

### Must back up

| Asset | Location | Why |
|-------|----------|-----|
| Postgres DB | `pgdata` named volume | All agent state: messages, memories, knowledge, tasks, todos, channels, sessions, sandbox instances, bot personas, tool embeddings, plans |
| `.env` | repo root | Runtime config, API keys, secrets |
| `bots/*.yaml` | repo root | Bot configurations (tracked in git, but may have local-only edits) |
| `skills/*.md` | repo root | Skill definitions (same caveat) |
| `mcp.yaml` | repo root | MCP server config with secrets via `${ENV_VAR}` |
| `config/searxng/settings.yml` | `config/searxng/` | SearXNG customization |

### Can skip (reconstructable)

- **`pgdata` volume itself** — the pg_dump is the backup, not the raw volume files
- **Docker images** — pulled from registries on `docker compose up`
- **`tool_embeddings` table rows** — re-indexed on every startup from tool files
- **`documents` table rows** — re-indexed on startup from `skills/*.md`
- **Python packages / virtualenvs** — reinstalled from `requirements.txt`
- **Playwright container state** — stateless

---

## Offsite Storage: Recommendation

### Recommended: **Google Drive via rclone**

- Already a personal/small-team stack — Google Drive is free up to 15 GB, no billing config needed
- `rclone` supports Google Drive natively, one-time OAuth setup
- Encrypted at rest (rclone crypt or Google-side)
- Simple: `rclone copy ./backups gdrive:agent-backups/`

### Alternative: S3 (or S3-compatible like Backblaze B2)

- Better if the new server is cloud-hosted (AWS/Hetzner with S3-compatible storage)
- More predictable for automation (no OAuth token refresh edge cases)
- Costs ~$0.005/GB/month on B2
- `rclone copy ./backups s3:agent-backups/` — same rclone interface

### Verdict

Start with **Google Drive** for the localhost phase (zero cost, fast setup). Switch to **S3/B2** if moving to a cloud server where IAM credentials are cleaner than OAuth tokens. `rclone` abstracts both — changing backends is a config swap, not a code change.

---

## Implementation Options

### Option A: Backup container in docker-compose

Add a `backup` service that runs `pg_dump` on a schedule and uploads via `rclone`.

```yaml
# docker-compose.yml addition
backup:
  image: postgres:16  # or a custom image with rclone + pg client
  volumes:
    - ./backups:/backups
    - ./rclone.conf:/root/.config/rclone/rclone.conf:ro
    - ./.env:/backup/.env:ro
    - ./bots:/backup/bots:ro
    - ./skills:/backup/skills:ro
    - ./mcp.yaml:/backup/mcp.yaml:ro
    - ./config:/backup/config:ro
  environment:
    PGHOST: postgres
    PGUSER: agent
    PGPASSWORD: agent
    PGDATABASE: agentdb
  entrypoint: ["/bin/sh", "-c"]
  command:
    - |
      apk add --no-cache rclone
      while true; do
        STAMP=$(date +%Y%m%d_%H%M%S)
        pg_dump -Fc > /backups/agentdb_$STAMP.dump
        cp /backup/.env /backup/mcp.yaml /backups/
        cp -r /backup/bots /backup/skills /backup/config /backups/
        tar czf /backups/agent-backup-$STAMP.tar.gz -C /backups agentdb_$STAMP.dump .env mcp.yaml bots skills config
        rm /backups/agentdb_$STAMP.dump /backups/.env /backups/mcp.yaml
        rm -rf /backups/bots /backups/skills /backups/config
        rclone copy /backups/agent-backup-$STAMP.tar.gz gdrive:agent-backups/
        # Keep last 7 local backups
        ls -t /backups/agent-backup-*.tar.gz | tail -n +8 | xargs rm -f
        sleep 86400  # daily
      done
  depends_on:
    postgres:
      condition: service_healthy
  restart: unless-stopped
```

**Pros:** Self-contained, travels with the stack, no host-level config.
**Cons:** `sleep` loop is crude (no exact scheduling), installing rclone on every restart is slow (fix with a custom image), container must stay running.

### Option B: Host-level cron job + script

A shell script on the host, triggered by cron.

```bash
#!/usr/bin/env bash
# scripts/backup.sh
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
STAMP=$(date +%Y%m%d_%H%M%S)
ARCHIVE="agent-backup-${STAMP}.tar.gz"

mkdir -p "$BACKUP_DIR"

# 1. Postgres dump via the running container
docker compose exec -T postgres pg_dump -U agent -Fc agentdb > "$BACKUP_DIR/agentdb_${STAMP}.dump"

# 2. Bundle with config files
tar czf "$BACKUP_DIR/$ARCHIVE" \
  -C "$BACKUP_DIR" "agentdb_${STAMP}.dump" \
  -C "$(pwd)" .env bots skills mcp.yaml config/searxng/settings.yml

rm "$BACKUP_DIR/agentdb_${STAMP}.dump"

# 3. Upload
rclone copy "$BACKUP_DIR/$ARCHIVE" gdrive:agent-backups/

# 4. Prune local (keep 7)
ls -t "$BACKUP_DIR"/agent-backup-*.tar.gz | tail -n +8 | xargs rm -f 2>/dev/null || true

echo "[backup] $ARCHIVE uploaded at $(date)"
```

Cron entry: `0 3 * * * cd /path/to/agent-server && ./scripts/backup.sh >> logs/backup.log 2>&1`

**Pros:** Real cron scheduling, no container overhead, simple to debug.
**Cons:** Requires host-level setup (not portable in docker-compose alone).

### Option C: Agent-triggered backup via scheduled task tool

Use the agent's own task/cron system to call a backup tool.

**Pros:** No host or container config.
**Cons:** Agent must be running for backups to happen — if the agent is down, no backups. Circular dependency (backing up the system that runs the backup). Not suitable for disaster recovery.

### Recommendation: **Option B (host cron + script)**

- Backups must be independent of the thing being backed up (rules out C)
- Real cron is more reliable than a sleep loop in a container (favors B over A)
- The script is simple, testable, and works on both localhost and the new server
- Only host dependency is `rclone` and `docker` CLI — both will be present anyway

Option A is a fine fallback if host cron access is restricted (e.g., NixOS without user crontab), but prefer B.

---

## Restore Procedure

### Prerequisites

- Docker + Docker Compose installed
- `rclone` configured with the same remote
- Repo cloned

### Steps

```bash
# 1. Pull the latest backup
rclone copy gdrive:agent-backups/ ./backups/ --include "agent-backup-*.tar.gz" \
  --max-count 1 --order-by modtime,desc

# 2. Extract
LATEST=$(ls -t ./backups/agent-backup-*.tar.gz | head -1)
mkdir -p ./restore && tar xzf "$LATEST" -C ./restore

# 3. Restore config files
cp ./restore/.env .env
cp ./restore/mcp.yaml mcp.yaml
cp -r ./restore/bots/* bots/
cp -r ./restore/skills/* skills/
cp ./restore/config/searxng/settings.yml config/searxng/settings.yml

# 4. Start postgres only
docker compose up -d postgres
# Wait for healthy
docker compose exec postgres pg_isready -U agent -d agentdb

# 5. Restore the database
docker compose exec -T postgres pg_restore -U agent -d agentdb \
  --clean --if-exists --no-owner < ./restore/agentdb_*.dump

# 6. Start the full stack
docker compose up -d

# 7. Verify
curl -s http://localhost:8000/health  # or whatever the health endpoint is
docker compose logs agent-server --tail 50

# 8. Cleanup
rm -rf ./restore
```

### Partial restore (DB only)

If config files haven't changed and you just need to roll back data:

```bash
docker compose exec -T postgres pg_restore -U agent -d agentdb \
  --clean --if-exists --no-owner < ./backups/agentdb_YYYYMMDD_HHMMSS.dump
docker compose restart agent-server
```

---

## Migration Path: Localhost → New Server

### On the old host (localhost)

1. Run `./scripts/backup.sh` to create a fresh backup
2. Ensure the backup is uploaded to Google Drive / S3
3. (Optional) `docker compose down` to stop services

### On the new host

1. Install Docker, Docker Compose, rclone, git
2. Clone the repo: `git clone <repo-url> && cd agent-server`
3. Configure rclone: `rclone config` (same remote as old host)
4. Follow the **Restore Procedure** above
5. Update `.env` for the new host:
   - `LITELLM_BASE_URL` — if LiteLLM proxy moves or is on a different host
   - `SEARXNG_URL` — typically stays `http://searxng:8080` (internal docker network)
   - `PLAYWRIGHT_URL` — same, stays `http://playwright:3000`
   - `DATABASE_URL` — stays `postgresql://agent:agent@postgres:5432/agentdb` (internal)
   - `SLACK_*` vars — no change needed (tokens are account-level, not host-level)
   - Any host-specific paths (e.g., `TOOL_DIRS`, `DOCKER_SANDBOX_MOUNT_ALLOWLIST`)
6. `docker compose up -d`
7. Set up cron on the new host: `crontab -e`, add the backup cron line
8. Verify the agent responds, memories are intact, bots load correctly
9. Update DNS / Slack event URLs / webhook endpoints to point to the new host IP

### What does NOT need to change

- `docker-compose.yml` — all service names and internal networking are relative
- Database credentials — baked into compose, unchanged
- Bot YAML, skills, MCP config — restored from backup
- Tool registrations — re-discovered on startup

---

## Implementation Steps

### PR 1: Backup script + docs (this plan)

- [x] Write this plan
- [ ] Create `scripts/backup.sh` (the script from Option B above)
- [ ] Create `scripts/restore.sh` (wraps the restore procedure)
- [ ] Add `backups/` to `.gitignore`
- [ ] Add `rclone.conf` to `.gitignore`

### PR 2: rclone setup + first backup

- [ ] Install rclone on localhost, configure Google Drive remote
- [ ] Run `scripts/backup.sh` manually, verify the archive on Google Drive
- [ ] Test `scripts/restore.sh` against a scratch postgres container
- [ ] Set up cron job

### PR 3 (optional): Backup container alternative

- [ ] Build a small Docker image with `pg16-client` + `rclone` + the backup script
- [ ] Add as `backup` service in `docker-compose.yml` with `ofelia` or `supercronic` for in-container cron
- [ ] Only needed if host cron is unavailable on the target server

---

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Backup runs but restore is never tested | You find out backups are broken only during a disaster | **Test restore monthly**: spin up a scratch postgres container, pipe in the dump, verify row counts |
| rclone OAuth token expires (Google Drive) | Uploads silently fail | Monitor backup script exit code in cron; rclone logs to stderr. Consider switching to S3 with static keys for the production server |
| Backup script runs during heavy DB writes | Inconsistent dump (unlikely with `pg_dump -Fc` which is transactional) | `pg_dump` in custom format is MVCC-safe — this is a non-risk for Postgres, but worth stating |
| `.env` contains secrets, uploaded to cloud storage | Credential leak if cloud account is compromised | Use `rclone crypt` to encrypt before upload, or encrypt the tarball with `gpg` / `age` before rclone |
| Backup archive grows too large | Google Drive fills up / costs increase on S3 | Prune to 7 local + 30 remote (add `rclone delete --min-age 30d` to the script) |
| Migration misses a config value in `.env` | Agent starts but some feature is broken on the new host | The restore script should diff old vs template `.env` and warn about host-specific values |
| `pg_restore --clean` drops tables that have new migrations | Schema mismatch between backup and current code | Always restore to the same code version as the backup. If upgrading, restore first, then `alembic upgrade head` |

---

## Storage Backend: AWS S3 (Recommended)

### Why S3 over Google Drive

Google Drive was the original recommendation for the localhost phase (free, fast setup), but S3 is the better choice for production:

- **No OAuth refresh headaches** — Google Drive requires periodic OAuth token renewal. If the token expires silently, backups stop uploading with no obvious error. S3 uses static access key + secret key that don't expire unless you rotate them.
- **Access key + secret** — simple credential pair, easy to store in `.env`, no browser-based auth flow needed on headless servers.
- **Lifecycle rules** — S3 natively supports expiration policies (e.g., delete objects older than 30 days) without scripting. Set it once in the S3 console or via `aws s3api put-bucket-lifecycle-configuration`.
- **Cheap** — S3 Standard is ~$0.023/GB/month. For typical agent-server backups (< 1 GB), this is effectively free. S3 Glacier or Backblaze B2 (~$0.005/GB/month) are even cheaper for cold storage.
- **IAM scoping** — create a dedicated IAM user with write-only access to one bucket. Principle of least privilege, no risk of the credential touching anything else in your AWS account.

### rclone S3 Configuration

Add to `rclone.conf` (or run `rclone config`):

```ini
[s3]
type = s3
provider = AWS
access_key_id = YOUR_ACCESS_KEY_ID
secret_access_key = YOUR_SECRET_ACCESS_KEY
region = us-east-1
```

Create the bucket:

```bash
aws s3 mb s3://thoth-backups --region us-east-1
```

### Updated Default Remote

Update `RCLONE_REMOTE` in `.env` and scripts:

```bash
# .env
RCLONE_REMOTE=s3:thoth-backups
```

The backup and restore scripts use `RCLONE_REMOTE` as the upload/download target. Changing from Google Drive to S3 is a config-only swap:

```bash
# Before (Google Drive)
rclone copy "$BACKUP_DIR/$ARCHIVE" gdrive:agent-backups/

# After (S3)
rclone copy "$BACKUP_DIR/$ARCHIVE" s3:thoth-backups/
```

### S3 Lifecycle Rule (auto-prune remote backups)

```json
{
  "Rules": [
    {
      "ID": "expire-old-backups",
      "Status": "Enabled",
      "Filter": { "Prefix": "" },
      "Expiration": { "Days": 30 }
    }
  ]
}
```

Apply: `aws s3api put-bucket-lifecycle-configuration --bucket thoth-backups --lifecycle-configuration file://lifecycle.json`

### Note on Script Compatibility

The existing `scripts/backup.sh` and `scripts/restore.sh` work unchanged — rclone abstracts the backend. The only change is the remote name in the rclone commands. No code changes are needed, only config.
