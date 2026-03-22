---
status: active
last_updated: 2026-03-22
owner: mtoth
summary: >
  Thoth is the official name for the agent-server project.
  Phase 1 complete: shell dispatcher (./thoth), systemd unit, install-service.sh.
  Phase 2 (backup wired into CLI) complete. Phase 3 (Python Click rewrite) pending.
---

# Thoth: Production Architecture & CLI

## Architecture

### Recommended: Native App + Docker Backing Services

The production layout runs the Thoth Python app as a **native process on the VM host**, managed by systemd. Backing services remain in Docker Compose:

```
┌─────────────────────────────────────────────┐
│  Ubuntu 24.04 LTS (Proxmox VM)              │
│                                             │
│  systemd: thoth.service                     │
│    └─ uvicorn app.main:app (native Python)  │
│       ├── localhost:5432 ← postgres (Docker) │
│       ├── localhost:8080 ← searxng  (Docker) │
│       └── localhost:3000 ← playwright (Docker)│
│                                             │
│  Docker Compose (backing services only):    │
│    postgres, searxng, playwright            │
└─────────────────────────────────────────────┘
```

**Why native on host:**

- The agent's `delegate_to_exec` tool gets full OS access — install packages, manage files, run arbitrary commands without Docker-in-Docker complexity.
- Direct filesystem access for backups, log rotation, cron, and system administration.
- Simpler debugging — `journalctl`, `strace`, `htop` all work directly.
- No container networking overhead for the app itself.

**Backing services stay in Docker** because they're self-contained, don't need host access, and Docker Compose makes their lifecycle trivial.

### Optional: Full Docker Mode

For users who prefer everything containerized:

- Main app also runs in Docker Compose alongside backing services.
- Accepted limitations:
  - `delegate_to_exec` is confined to the container (no true host OS access).
  - Docker-in-Docker or socket mounting needed for sandbox features.
  - More complex networking and volume management.
- This mode is not the recommended path but will be supported via a `--docker` flag.

### Target VM

- **OS:** Ubuntu 24.04 LTS
- **Host:** Proxmox node (existing infrastructure)
- **Resources:** 2+ vCPU, 4+ GB RAM, 50+ GB disk
- **Network:** Static IP or DHCP reservation, ports 8000 (app), 5432 (postgres, internal only)

---

## Thoth CLI (`thoth` command)

A unified CLI entry point for managing the Thoth installation. Implemented as a Python Click application (installed via `pip install -e .` from the repo root).

### Commands

#### `thoth install`

First-time setup wizard. Interactive prompts with sane defaults.

1. Check system dependencies (Python 3.12+, Docker, docker-compose, git, rclone)
2. Report missing deps with install instructions
3. Create `.env` from `.env.example` — prompt for required values (`LITELLM_BASE_URL`, model keys)
4. Configure rclone S3 remote (bucket name, region, credentials)
5. Run `pip install -r requirements.txt`
6. Start postgres via Docker Compose, run `alembic upgrade head`
7. Register `thoth.service` systemd unit (copy unit file, `systemctl daemon-reload`, `systemctl enable thoth`)
8. Print summary and next steps

#### `thoth start`

Start the full stack:

1. `docker compose up -d` (backing services)
2. Wait for postgres health check
3. `systemctl start thoth` (app service)
4. If `SLACK_*` vars are set, start Slack bot integration
5. Print status

#### `thoth stop`

Graceful shutdown:

1. `systemctl stop thoth`
2. `docker compose down`

#### `thoth restart`

Restart with optional update:

1. `git pull --rebase origin master`
2. `pip install -r requirements.txt` (in case deps changed)
3. `alembic upgrade head` (in case migrations were added)
4. `systemctl restart thoth`
5. Verify health endpoint responds

#### `thoth pull`

Git pull + dependency update + restart. Designed to be callable by the agent itself via `delegate_to_exec` for self-update:

1. `git pull --rebase origin master`
2. `pip install -r requirements.txt`
3. `alembic upgrade head`
4. `systemctl restart thoth`
5. Print diff summary (files changed, migrations applied)

#### `thoth backup`

Run `scripts/backup.sh`:

1. Execute the backup script
2. Print archive name, size, and upload status
3. Exit with the script's exit code

#### `thoth restore [archive]`

Run `scripts/restore.sh`:

- If `archive` is provided, restore that specific file
- If omitted, pull the latest from the S3 remote
- Confirm before overwriting (unless `--yes` flag)

#### `thoth status`

Dashboard view:

```
Thoth Status
─────────────────────────────
App service:    ● active (running) since 2026-03-22 10:00:00
Postgres:       ● healthy
SearXNG:        ● healthy
Playwright:     ● healthy

Last backup:    2026-03-22 03:00:01 (agent-backup-20260322_030001.tar.gz)
DB size:        142 MB
Uptime:         3d 14h 22m

Bot configs:    4 loaded
Skills:         7 indexed
Tools:          23 registered
MCP servers:    2 connected
```

#### `thoth logs [--follow] [--service NAME]`

Tail logs:

- Default: app logs via `journalctl -u thoth`
- `--follow` / `-f`: stream live
- `--service postgres|searxng|playwright`: Docker Compose logs for that service
- No args: last 50 lines of app log

#### `thoth upgrade`

Future command for major version upgrades:

- Check current vs latest version
- Run pre-upgrade checks (disk space, backup freshness)
- Apply migrations, handle schema changes
- Placeholder for now — prints "not yet implemented"

### CLI Implementation

```python
# thoth/cli.py
import click
import subprocess

@click.group()
def cli():
    """Thoth — agent server management CLI."""
    pass

@cli.command()
def install():
    """First-time setup wizard."""
    ...

@cli.command()
def start():
    """Start Thoth and all backing services."""
    ...

# etc.

if __name__ == "__main__":
    cli()
```

Entry point in `pyproject.toml`:

```toml
[project.scripts]
thoth = "thoth.cli:cli"
```

---

## Systemd Service

### Unit File

```ini
# /etc/systemd/system/thoth.service
[Unit]
Description=Thoth Agent Server
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=thoth
Group=thoth
WorkingDirectory=/opt/thoth
EnvironmentFile=/opt/thoth/.env
ExecStartPre=/usr/bin/docker compose up -d postgres searxng playwright
ExecStartPre=/opt/thoth/venv/bin/alembic upgrade head
ExecStart=/opt/thoth/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=thoth

[Install]
WantedBy=multi-user.target
```

### Key Decisions

- **`ExecStartPre`** handles backing service startup and migrations — by the time the app starts, postgres is ready and schema is current.
- **`Restart=on-failure`** — auto-restart on crash, but not on clean shutdown (so `thoth stop` stays stopped).
- **`User=thoth`** — dedicated system user, not root. The user needs Docker group membership for compose commands.
- **Logging** goes to journald — `thoth logs` reads from `journalctl -u thoth`.

### Companion Units (Future)

If integrations (Slack bot, scheduled tasks) need separate processes, they can be managed as:

- `thoth-slack.service` — Slack bot process
- `thoth-backup.timer` + `thoth-backup.service` — systemd timer replacing cron for backups

---

## Install Guide

Step-by-step for a fresh Ubuntu 24.04 LTS VM.

### 1. System Dependencies

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# System dependencies (everything except Docker)
sudo apt install -y git python3.12 python3.12-venv rclone

# Docker — via official script (includes compose plugin)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker

# Verify Docker install
docker --version && docker compose version

# rclone (if not available via apt on your distro)
# curl https://rclone.org/install.sh | sudo bash

# AWS CLI (optional — for S3 bucket management)
# sudo apt install -y awscli
```

### 2. GitHub Auth

```bash
# Authenticate GitHub CLI (one-time — persists across sessions)
gh auth login --with-token <<< "your_github_pat_here"
gh auth setup-git  # makes git use gh for HTTPS auth
```

### 3. Clone Repo

```bash
sudo mkdir -p /opt/thoth
sudo chown $USER:$USER /opt/thoth
git clone <repo-url> /opt/thoth
cd /opt/thoth
```

### 4. Configure rclone & Environment

```bash
# Set up rclone S3 remote for backups
rclone config

# Copy or restore .env
cp .env.example .env
# Edit .env with your values (LITELLM_BASE_URL, model keys, etc.)
```

### 5. Restore (if migrating) or Fresh Setup

```bash
# If migrating from another host:
./scripts/restore.sh

# If fresh install, start postgres and run migrations:
docker compose up -d postgres searxng playwright
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
```

### 6. Install Service

```bash
sudo ./scripts/install-service.sh
```

### 7. Verify

```bash
systemctl status agent-server
curl http://localhost:8000/health
```

---

## Migration from Localhost

### On the Old Host (localhost)

```bash
# Create a fresh backup
./scripts/backup.sh

# Verify it uploaded to S3
rclone ls s3:thoth-backups/ | head -5

# (Optional) Stop services
docker compose down
```

### On the New Host (VM)

```bash
# 1. Follow Install Guide steps 1-3 above

# 2. Restore from S3 backup
thoth restore

# 3. Review and update .env for the new host
#    - LITELLM_BASE_URL (if LiteLLM proxy location changed)
#    - Any host-specific paths (TOOL_DIRS, DOCKER_SANDBOX_MOUNT_ALLOWLIST)
#    - Most values (SLACK_*, DATABASE_URL, SEARXNG_URL) stay the same

# 4. Start and verify
thoth start
thoth status

# 5. Set up backup cron on the new host (or use systemd timer)
# The install wizard handles this, but manually:
echo "0 3 * * * /opt/thoth/venv/bin/thoth backup >> /opt/thoth/logs/backup.log 2>&1" | crontab -

# 6. Cut over
#    - Update DNS records to point to new host IP
#    - Update Slack event subscription URLs
#    - Update any webhook endpoints
```

### Verification Checklist

- [ ] Health endpoint responds
- [ ] Memories and conversation history are intact
- [ ] All bots load correctly (`thoth status`)
- [ ] MCP servers connect
- [ ] Slack bot responds to messages
- [ ] Backup runs successfully on the new host
- [ ] `delegate_to_exec` has full OS access (native mode only)

---

## Implementation Phases

### Phase 1: Shell Dispatcher + Systemd Unit

Minimum viable `thoth` command as a thin shell script dispatching to existing scripts and systemctl:

- `thoth start`, `thoth stop`, `thoth restart`, `thoth status`, `thoth logs`
- Systemd unit file for the app service
- Install via symlink to `/usr/local/bin/thoth`

**Deliverable:** App runs as a systemd service on the VM, manageable via `thoth` commands.

### Phase 2: S3 Backup Wired into CLI

- `thoth backup` and `thoth restore` commands
- S3 as the default remote (per updated BACKUP_SYSTEM.md plan)
- Systemd timer as alternative to cron

**Deliverable:** Backups flow to S3, restorable via CLI.

### Phase 3: Install Wizard

- Rewrite shell dispatcher as Python Click app
- `thoth install` interactive wizard
- Dependency checking, `.env` generation, rclone config, systemd registration
- Entry point via `pyproject.toml`

**Deliverable:** Fresh VM goes from zero to running Thoth with one command.

### Phase 4: Docker Mode (Optional)

- `thoth install --docker` path that generates a full Docker Compose config
- App container with appropriate volume mounts
- Document limitations (no native OS access for agent)

**Deliverable:** Alternative deployment mode for users who prefer full containerization.
