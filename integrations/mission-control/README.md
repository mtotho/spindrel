# Mission Control

Visual dashboard for agent workspaces — kanban boards, file viewers, activity timelines.

## Architecture

Three layers:

1. **File Protocol** — Structured markdown formats (`tasks.md`, `status.md`) that bots write using the `mission_control` skill and tools
2. **Integration** — Server-side router for overview aggregation and write-back, container launcher
3. **Dashboard App** — React/Vite + Express in Docker, reads workspace files from volume mount + API data

## Quick Start

1. Build the dashboard Docker image:
   ```bash
   cd integrations/mission-control/dashboard
   docker build -t mission-control:latest .
   ```

2. The integration auto-discovers on server startup. The ProcessManager starts the container.

3. Access at `http://localhost:9100` (or configured `MISSION_CONTROL_PORT`).

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `MISSION_CONTROL_PORT` | `9100` | Dashboard port on host |
| `MISSION_CONTROL_IMAGE` | `mission-control:latest` | Docker image |
| `MISSION_CONTROL_CONTAINER_NAME` | `mission-control` | Container name |
| `WORKSPACE_ROOT` | `~/.agent-workspaces` | Host path mounted as `/workspaces` |

## Bot Tools

- `create_task_card` — Create a kanban card in `tasks.md`
- `move_task_card` — Move a card between columns

## Custom Dashboard

Swap `MISSION_CONTROL_IMAGE` to use your own dashboard. The container receives:
- `/workspaces` volume mount (read-only workspace files)
- `AGENT_SERVER_URL` env var (agent server API)
- `AGENT_SERVER_API_KEY` env var (scoped API key)
