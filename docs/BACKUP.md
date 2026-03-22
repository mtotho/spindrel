# Backup & Restore

Automated Postgres dumps + config file backups, uploaded to S3 (or any rclone-supported remote like Google Drive).

## Prerequisites

- Docker & Docker Compose (already required by the project)
- [rclone](https://rclone.org/install/) — `sudo pacman -S rclone` (Arch) or `curl https://rclone.org/install.sh | sudo bash`

## Setup

### 1. Configure S3 credentials

No rclone config file needed — the scripts pass credentials via environment variables. Add these to your `.env` or export them in your shell:

```bash
AWS_ACCESS_KEY_ID=your-key
AWS_SECRET_ACCESS_KEY=your-secret
AWS_REGION=us-east-1
RCLONE_REMOTE=:s3:your-bucket-name
```

> **Note:** The `:s3:` prefix is rclone's [connection string syntax](https://rclone.org/docs/#connection-strings) — it tells rclone to use the S3 backend without a named config entry.

Create the bucket if it doesn't exist:

```bash
aws s3 mb s3://your-bucket-name --region us-east-1
```

Verify it works:

```bash
export AWS_ACCESS_KEY_ID=your-key AWS_SECRET_ACCESS_KEY=your-secret RCLONE_REMOTE=:s3:your-bucket-name
rclone lsd "$RCLONE_REMOTE"
```

### 2. Run a manual backup

```bash
./scripts/backup.sh
```

This will:
1. `pg_dump` the database via `docker compose exec`
2. Bundle the dump with `.env`, `bots/`, `skills/`, `mcp.yaml`, and `config/searxng/settings.yml`
3. Upload the tarball to the rclone remote (`RCLONE_REMOTE`)
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
| `AWS_ACCESS_KEY_ID` | *(required)* | AWS access key for S3 |
| `AWS_SECRET_ACCESS_KEY` | *(required)* | AWS secret key for S3 |
| `AWS_REGION` | `us-east-1` | AWS region |
| `RCLONE_REMOTE` | *(required)* | rclone remote path (e.g. `:s3:your-bucket-name`) |
| `BACKUP_DIR` | `./backups` | Local directory for backup archives |
| `LOCAL_KEEP` | `7` | Number of local backups to retain (backup.sh only) |

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
2. On new host: clone repo, install Docker + rclone, set the same AWS/rclone env vars
3. Run `./scripts/restore.sh`
4. Review `.env` for host-specific values (`LITELLM_BASE_URL`, paths, etc.)
5. Set up cron on the new host
6. Update DNS / webhook URLs to point to the new host
