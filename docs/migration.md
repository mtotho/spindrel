# Migration Guide

Moving Spindrel from one machine to another, or switching deployment modes (native Python ↔ Docker).

## Overview

A migration has four phases:

1. **Backup** the old machine
2. **Set up** the new machine
3. **Restore** the backup
4. **Re-point** external services (Cloudflare tunnel, webhook URLs)

---

## Phase 1: Backup the Old Machine

### 1a. Run a fresh backup

```bash
./scripts/backup.sh
```

This creates a timestamped archive containing:

| Asset | Description |
|-------|-------------|
| Postgres dump | All sessions, messages, bots (DB state), channels, tasks, etc. |
| `.env` | Runtime config and API keys |
| `bots/*.yaml` | Bot configurations |
| `skills/*.md` | Skill markdown files |
| `tools/` | Custom Python tools |
| `integrations/` | All integration directories |
| `mcp.yaml` | MCP server config |
| `integrations/web_search/config/searxng/settings.yml` | SearXNG customization |
| Workspace files | `~/.spindrel-workspaces/` (MEMORY.md, daily logs, reference docs) |

The archive is uploaded to your S3 bucket (configured via `RCLONE_REMOTE` in `.env`).

### 1b. Verify the backup

```bash
# List the archive contents to make sure everything is there
tar tzf ./backups/agent-backup-*.tar.gz | head -30

# Or check S3 directly
rclone ls "$RCLONE_REMOTE/" --include "agent-backup-*.tar.gz" | tail -3
```

### 1c. Note your current setup

Before leaving the old machine, record:

- [ ] Deployment mode: native (systemd) or Docker?
- [ ] LiteLLM: self-hosted or external? What URL?
- [ ] Cloudflare tunnel name and subdomain
- [ ] Which integrations are active (Slack, GitHub, Frigate, etc.)
- [ ] Any external `INTEGRATION_DIRS` paths
- [ ] Any cron jobs (`crontab -l`)
- [ ] Workspace base directory path (`WORKSPACE_BASE_DIR`)
- [ ] Whether you use Docker sandboxes (`DOCKER_SANDBOX_ENABLED`)

---

## Phase 2: Set Up the New Machine

### Prerequisites

| Requirement | Notes |
|-------------|-------|
| Git | Clone the repo |
| Docker + Docker Compose | Required for all deployment modes |
| rclone | For pulling the backup from S3. `brew install rclone` (macOS) or `sudo pacman -S rclone` (Arch) |
| Python 3.12+ (native mode only) | Not needed if running fully in Docker |

### 2a. Clone the repo

```bash
git clone https://github.com/mtotho/spindrel.git
cd spindrel
```

### 2b. Set up rclone credentials

The restore script needs S3 access. Export these or create a temporary `.env`:

```bash
export AWS_ACCESS_KEY_ID=your-key
export AWS_SECRET_ACCESS_KEY=your-secret
export AWS_REGION=us-east-1
export RCLONE_REMOTE=:s3:your-bucket-name
```

### 2c. Create empty directories

```bash
mkdir -p bots skills tools backups
```

---

## Phase 3: Restore

### 3a. Run the restore script

```bash
./scripts/restore.sh
```

This pulls the latest backup from S3 and:
1. Restores config files (`.env`, `bots/`, `skills/`, `tools/`, `mcp.yaml`, integration configs)
2. Restores workspace files to `WORKSPACE_BASE_DIR`
3. Starts Postgres and restores the database dump
4. Starts backing services (Postgres, SearXNG, Playwright)

Or restore from a specific local archive:

```bash
./scripts/restore.sh ./backups/agent-backup-20260322_030000.tar.gz
```

### 3b. Edit `.env` for the new machine

The restored `.env` will have values from the old machine. Review and update:

```bash
# Open .env in your editor
vim .env
```

**Values that almost always need to change:**

| Variable | Why |
|----------|-----|
| `DATABASE_URL` | Use `postgres` hostname for Docker, `localhost` for native |
| `LLM_BASE_URL` | Update if your LLM provider is on a different host |
| `WORKSPACE_BASE_DIR` | Path may differ on the new machine |
| `WORKSPACE_HOST_DIR` | Required for Docker mode (see below) |
| `WORKSPACE_LOCAL_DIR` | Required for Docker mode (see below) |
| `BASE_URL` | Your public URL (Cloudflare tunnel domain) |

**Docker mode `.env` changes:**

If you're switching from native to Docker, update these:

```bash
# Database — use Docker service name, not localhost
DATABASE_URL=postgresql+asyncpg://agent:agent@postgres:5432/agentdb

# Workspace paths — required for sibling container pattern
WORKSPACE_HOST_DIR=/Users/yourname/.spindrel-workspaces   # real host path
WORKSPACE_LOCAL_DIR=/workspace-data                         # mount path inside container

# SearXNG and Playwright — use container names (managed by web_search integration)
# These are auto-detected when WEB_SEARCH_CONTAINERS=true; only set for external instances.
# SEARXNG_URL=http://spindrel-searxng:8080
# PLAYWRIGHT_WS_URL=ws://spindrel-playwright:3000
```

**Native mode `.env`** (no changes needed for these — localhost works):

```bash
DATABASE_URL=postgresql+asyncpg://agent:agent@localhost:5432/agentdb
# WORKSPACE_HOST_DIR and WORKSPACE_LOCAL_DIR can be empty or omitted
```

### 3c. Start the server

**Docker mode (recommended for Mac Mini):**

```bash
docker compose up -d
```

This starts everything: Postgres, SearXNG, Playwright, the agent server, and the UI.

**Native mode:**

```bash
./scripts/install-service.sh    # sets up systemd service
spindrel start
```

### 3d. Verify

```bash
# Health check
curl http://localhost:8000/health

# Check the UI
open http://localhost:8081

# Check logs
docker compose logs agent-server --tail 50    # Docker mode
journalctl -u spindrel -f                     # Native mode
```

---

## Phase 4: Re-point External Services

### Cloudflare Tunnel

If you use a Cloudflare tunnel to expose the server to the internet (required for GitHub webhooks, external access, etc.), you need to set up a new tunnel connector on the new machine. The tunnel itself and its public hostname stay the same — only the connector moves.

#### Docker mode

The tunnel connector runs on the **host**, not inside Docker. It points at `localhost:8000` because Docker Compose maps port 8000 from the container to the host.

**macOS (Mac Mini):**

1. Go to [Cloudflare dashboard](https://dash.cloudflare.com/) → **Networking → Tunnels**
2. Click your existing tunnel → **Configure** → **Connectors** tab
3. You'll see the old connector (from your Linux VM). It will show as unhealthy once you shut down the old machine.
4. Click **Install another connector** and select **macOS**
5. Cloudflare gives you a command like:

   ```bash
   brew install cloudflare/cloudflare/cloudflared
   sudo cloudflared service install <your-tunnel-token>
   ```

6. Run it on the Mac Mini. The connector starts as a launchd service (auto-starts on boot).
7. Verify the connector shows as **Healthy** in the dashboard.
8. The public hostname config (`agent.yourdomain.com` → `http://localhost:8000`) does NOT need to change — it's the same whether the server is native or Docker.

**Linux:**

Same process, but Cloudflare gives you a systemd install command instead:

```bash
# Cloudflare provides the full command — something like:
sudo cloudflared service install <your-tunnel-token>
sudo systemctl enable --now cloudflared
```

#### Verify the tunnel

```bash
curl https://agent.yourdomain.com/health
```

If you get `{"status":"ok"}`, the tunnel is working end-to-end.

**Important:** You don't need to update any webhook URLs or DNS records. The Cloudflare tunnel hostname stays the same — only the connector endpoint moved.

### GitHub Webhooks

If you use the GitHub integration, **no changes are needed** as long as your Cloudflare tunnel hostname hasn't changed. GitHub sends webhooks to `https://agent.yourdomain.com/integrations/github/webhook` — that URL is tied to the tunnel, not the machine.

Verify by checking GitHub → your repo → **Settings → Webhooks → Recent Deliveries**. If the tunnel is healthy, deliveries should show green checkmarks.

If you changed your public URL (e.g., new domain, new tunnel), update the webhook URL in GitHub:

1. Go to your repo → **Settings → Webhooks**
2. Edit the webhook
3. Update **Payload URL** to `https://new-url/integrations/github/webhook`
4. Keep the same **Secret** (it's in your `.env` as `GITHUB_WEBHOOK_SECRET`)

### Slack

If you use the Slack integration, **no changes are needed**. Slack Socket Mode uses an outbound WebSocket — Slack connects to your bot, not the other way around. As long as `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` are in your `.env`, the bot will reconnect automatically when the server starts.

---

## Deployment Mode Reference

### Native → Docker

Switching from running the server on the host to running it inside Docker.

**Changes:**
1. Add `WORKSPACE_HOST_DIR` and `WORKSPACE_LOCAL_DIR` to `.env`
2. Change `DATABASE_URL` hostname from `localhost` to `postgres`
3. Set `WEB_SEARCH_CONTAINERS=true` if using built-in SearXNG containers
4. Run `docker compose up -d` instead of `spindrel start`
5. Disable the systemd service if it exists: `sudo systemctl disable --now spindrel`

**What stays the same:**
- All bot configs, skills, tools, workspace data
- API keys
- Cloudflare tunnel hostname (just re-point connector to same `localhost:8000`)
- Webhook URLs

### Docker → Native

**Changes:**
1. Remove or comment out `WORKSPACE_HOST_DIR` and `WORKSPACE_LOCAL_DIR`
2. Change `DATABASE_URL` hostname from `postgres` to `localhost`
3. Set up Python venv: `python -m venv .venv && source .venv/bin/activate && pip install -e .`
4. Run `./scripts/install-service.sh`

---

## Gotchas and Troubleshooting

### First startup is slow

The embedding model cache (`fastembed-cache` Docker volume) is not backed up. On first startup after restore, the server downloads the embedding model (~100MB). This adds 30-60 seconds to the first boot. Subsequent starts are fast.

### Workspace path on macOS vs Linux

macOS home directories are `/Users/yourname`, not `/home/yourname`. Update `WORKSPACE_BASE_DIR` and `WORKSPACE_HOST_DIR` accordingly:

```bash
# Linux
WORKSPACE_BASE_DIR=~/.spindrel-workspaces
WORKSPACE_HOST_DIR=/home/yourname/.spindrel-workspaces

# macOS
WORKSPACE_BASE_DIR=~/.spindrel-workspaces
WORKSPACE_HOST_DIR=/Users/yourname/.spindrel-workspaces
```

### Docker socket permissions on macOS

Docker Desktop for Mac handles socket permissions automatically. No `docker` group setup needed (unlike Linux).

### LLM provider location

If your LLM provider was running on the old machine (e.g., Ollama, LiteLLM proxy), you need it accessible from the new one too. Options:
- Run the provider on the new machine (separate Docker Compose or container)
- Point `LLM_BASE_URL` at a cloud provider directly (OpenAI, OpenRouter, Gemini — see [setup.md](setup.md) for URLs)
- Keep the provider on the old machine and update the URL

### Migrations run automatically

On first startup, Alembic migrations run automatically. If your backup is from an older version of the code, the new code may apply new migrations. This is normal and expected.

### Integration processes

Integration background processes (Slack bot, etc.) auto-start when their required env vars are set. Check **Admin UI → Integrations** after startup to verify they're running.

### Cron jobs don't migrate

If you had cron jobs on the old machine (e.g., daily backups), set them up again:

```bash
crontab -e
# Add:
0 2 * * * /path/to/agent-server/scripts/backup.sh >> /var/log/spindrel-backup.log 2>&1
```

On macOS, you can also use launchd instead of cron.
