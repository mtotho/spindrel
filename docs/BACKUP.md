# Backup & Restore

Automated Postgres dumps + config file backups, uploaded to S3 (or any rclone-supported remote like Google Drive).

## Prerequisites

- Docker & Docker Compose (already required by the project)
- [rclone](https://rclone.org/install/) — `sudo pacman -S rclone` (Arch) or `curl https://rclone.org/install.sh | sudo bash`

## Setup

### 1a. Configure rclone with S3 (recommended)

Add to `~/.config/rclone/rclone.conf` (or run `rclone config`):

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

Verify it works:

```bash
rclone lsd s3:
```

### 1b. Alternative: Configure rclone with Google Drive

```bash
rclone config
```

Follow the interactive setup:
- **n** (new remote)
- Name: `gdrive`
- Storage: `drive` (Google Drive)
- Leave client_id/secret blank (uses rclone's defaults)
- Scope: `drive` (full access) or `drive.file` (only rclone-created files)
- Complete the OAuth flow in your browser

Then set the remote override:

```bash
export RCLONE_REMOTE=gdrive:agent-backups
```

Verify it works:

```bash
rclone lsd gdrive:
```

### 2. Run a manual backup

```bash
./scripts/backup.sh
```

This will:
1. `pg_dump` the database via `docker compose exec`
2. Bundle the dump with `.env`, `bots/`, `skills/`, `mcp.yaml`, and `config/searxng/settings.yml`
3. Upload the tarball to the rclone remote (default: `s3:thoth-backups`)
4. Prune local backups to the most recent 7

### 3. Set up cron (daily at 2 AM)

```bash
crontab -e
```

Add:

```cron
0 2 * * * /path/to/scripts/backup.sh >> /var/log/thoth-backup.log 2>&1
```

## Restore

### From the latest remote backup

```bash
./scripts/restore.sh
```

This pulls the latest archive from the rclone remote, extracts config files, restores the database, and restarts the stack.

### From a specific local archive

```bash
./scripts/restore.sh ./backups/agent-backup-20260322_030000.tar.gz
```

### Database-only restore

If config files haven't changed and you only need to roll back data:

```bash
docker compose exec -T postgres pg_restore -U agent -d agentdb \
  --clean --if-exists --no-owner < ./backups/agentdb_YYYYMMDD_HHMMSS.dump
docker compose restart agent-server
```

## Configuration

Both scripts support environment variable overrides:

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKUP_DIR` | `./backups` | Local directory for backup archives |
| `RCLONE_REMOTE` | `s3:thoth-backups` | rclone remote and path |
| `LOCAL_KEEP` | `7` | Number of local backups to retain (backup.sh only) |

To use Google Drive instead of S3, configure a gdrive remote in rclone and set:

```bash
RCLONE_REMOTE=gdrive:agent-backups ./scripts/backup.sh
```

## What's backed up

| Asset | Why |
|-------|-----|
| Postgres database (`pg_dump -Fc`) | All agent state: messages, memories, knowledge, sessions, etc. |
| `.env` | Runtime config and API keys |
| `bots/*.yaml` | Bot configurations |
| `skills/*.md` | Skill definitions |
| `mcp.yaml` | MCP server config |
| `config/searxng/settings.yml` | SearXNG customization |

## Migration to a new server

1. On old host: `./scripts/backup.sh`
2. On new host: clone repo, install Docker + rclone, configure the same rclone remote
3. Run `./scripts/restore.sh`
4. Review `.env` for host-specific values (`LITELLM_BASE_URL`, paths, etc.)
5. Set up cron on the new host
6. Update DNS / webhook URLs to point to the new host
