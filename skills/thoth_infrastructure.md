---
name: thoth-infrastructure
description: "Load when asked about how the Thoth server is set up, how services are wired together, where to put new tools or scripts, how integrations are structured (first-class vs ad-hoc), backup/restore behavior, or service management. Trigger on: 'how is thoth wired', 'where does this integration go', 'how do I add a tool', 'what gets backed up', 'how do I restart the service'. Do NOT load for general Python, FastAPI, or Docker questions unrelated to Thoth's own architecture."
---

# Thoth Infrastructure

## Core Principle
Thoth is a native Python service, not a Docker container. Docker is exclusively for supporting services. Everything that matters about how Thoth runs lives in this skill.

## Service Architecture

| Service | Type | How it runs | Port |
|---|---|---|---|
| `thoth` | Agent server (FastAPI/uvicorn) | systemd native | 8000 |
| `thoth-slack` | Slack bot (socket mode) | systemd native | none |
| `postgres` | Database (pgvector) | Docker | 5432 |
| `searxng` | Web search | Docker | 8080 |
| `playwright` | Browser automation | Docker | 3000 |

- Repo: `/home/thothbot/agent-server`
- Both systemd services run as user `thothbot`
- `thoth-slack` bound to `thoth` via `BindsTo=` — if thoth stops, slack bot stops
- Environment loaded from `.env`

## Service Management

```
sudo systemctl restart thoth thoth-slack
systemctl is-active thoth thoth-slack
journalctl -u thoth -n 50
journalctl -u thoth-slack -n 50
```

`thothbot` has passwordless sudo for systemctl start/stop/restart thoth/thoth-slack and daemon-reload only.

## Integration Architecture

### First-Class (source-controlled)
Live in `integrations/<name>/`. Self-contained, plug-and-play. Tools register via `@register` decorator, auto-discovered at startup via `discover_and_load_tools()`. Examples: `integrations/slack/`, `integrations/arr/`. Never put domain code in `/app` or `scripts/`.

### Ad-Hoc / Workspace (planned)
Will live in `~/thoth/` — outside repo, backed up automatically. For wiring scripts and experiments not ready for source control. Auto-discovered via `TOOL_DIRS` env var.

## Decision Tree: Where Does New Code Go?

- Reusable integration with external service → `integrations/<name>/`
- Core framework (agent loop, DB, tool dispatch) → `app/`
- Scheduled data fetch → `integrations/<name>/scripts/` + cron
- One-off experiment → `~/thoth/` (planned workspace)

## Backup & Restore

- `backup.sh` — daily 2am, uploads tarball to S3 via rclone
- `restore.sh` — pulls backup, starts postgres, then run `install-service.sh`
- Backed up: `.env`, DB dump, `data/`, config files
- Not backed up: repo (pulled fresh from GitHub), venv (rebuilt)

## Common Gotchas
- Jinja2 pinned to older version — newer versions break template cache
- `thoth-slack` won't start if `thoth` isn't running (BindsTo)
- `HOST_EXEC_ENABLED=true` in `.env` lets bot run host commands directly
- `newgrp docker` required after adding user to docker group
