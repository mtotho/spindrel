# Spindrel

Self-hosted AI agent server with persistent channels, composable expertise (carapaces), workspace-driven memory, scheduled automation, and a pluggable integration framework. Built on FastAPI + PostgreSQL (pgvector).

## Quick Start

```bash
git clone https://github.com/spindrel/agent-server.git
cd agent-server
bash setup.sh          # interactive wizard: deployment mode, LLM provider, auth
docker compose up -d   # or: bash scripts/dev-server.sh for local dev
```

The wizard configures `.env`, starts services, and creates a default bot. Open the web UI and the Orchestrator bot will guide you through setup conversationally.

See [docs/setup.md](docs/setup.md) for manual configuration, provider options, and troubleshooting.

## Screenshots

<!-- TODO: Add screenshots. Suggested captures:
  1. Chat interface with streaming tool calls visible (show a web_search or exec_command in action)
  2. Sidebar with workspace switcher + channels + upcoming heartbeats
  3. Bot editor page showing carapaces, skills, and tool config
  4. Channel workspace tab with file browser and schema editor
  5. Task scheduler (schedule view with recurring tasks)
  6. Mission Control overview dashboard
  Screenshots should be dark theme, ~1200px wide, saved to docs/images/
-->

## Key Features

### Channels & Conversations
Persistent channels with streaming chat (SSE), context compaction, and conversation history. Each channel belongs to a bot and optionally a workspace. Model, tools, and skills can be overridden per-channel.

### Carapaces (Composable Expertise)
Reusable bundles of skills, tools, and behavioral instructions. A bot with `carapaces: [qa, code-review]` gets instant testing and review expertise. Carapaces compose via `includes` — the QA carapace includes code-review, inheriting its tools and adding its own.

```yaml
# carapaces/qa.yaml
id: qa
name: QA Expert
skills: [{id: channel-workspace, mode: on_demand}]
local_tools: [exec_command, file, web_search]
pinned_tools: [exec_command]
includes: [code-review]
system_prompt_fragment: |
  ## QA Expert Mode
  Before writing tests, read the code under test...
```

### Workspace-Driven Memory
File-based memory system (`memory_scheme: workspace-files`). Bots maintain a `MEMORY.md` knowledge base, daily logs, and reference documents — all on disk, all indexed for RAG.

### Channel Workspaces
Per-channel file stores with schema-guided organization. Active `.md` files are auto-injected into context. Choose from 7 built-in templates (Software Dev, Research, QA, Creative, PM Hub, etc.) or write custom schemas.

### Heartbeats
Periodic autonomous check-ins. Configure per-channel schedules, quiet hours, dispatch modes, and repetition detection. The bot can proactively monitor, report, and take action.

### Task Scheduling
Schedule one-off or recurring agent tasks. Bots can self-schedule via the `schedule_task` tool. Results dispatch to Slack, webhooks, or stay in the DB for polling.

```
"Remind me to check the deployment in 20 minutes"
"Every hour, check if the office temperature is above 78°F"
```

### Bot-to-Bot Delegation
Orchestrator bots delegate to specialist bots — synchronously or as background tasks. Chains up to 3 levels deep. Users can @-tag any bot for ephemeral delegation.

### Integration Framework
Pluggable integrations with auto-discovery. Each integration can provide routers, dispatchers, lifecycle hooks, background processes, tools, and skills.

**Shipped integrations:** Slack, GitHub, Frigate (NVR), Mission Control

**External integrations:** Point `INTEGRATION_DIRS` to your own directories.

### Tool System
Three tool types: local Python functions, MCP protocol servers, and client-side actions. Tool RAG surfaces only relevant tools per request. Pin critical tools to always include them.

### Multi-Provider LLM
Connect any combination of LLM providers simultaneously. Supports OpenAI-compatible endpoints (OpenAI, Gemini, Ollama, OpenRouter, vLLM, LiteLLM, etc.) and native Anthropic. Assign providers per-bot. Automatic retry with exponential backoff and fallback models.

When using a LiteLLM proxy, Spindrel can pull model pricing data for accurate cost tracking in the usage dashboard.

## Architecture

```
┌──────────────┐  ┌──────────────┐
│   Web UI     │  │  Integrations│
│ (Expo/React) │  │ (Slack, GH,  │
└──────┬───────┘  │  Frigate)    │
       │          └──────┬───────┘
       │    SSE / REST   │
       └────────┬────────┘
                │
       ┌────────┴─────────────────────────────────┐
       │            Agent Server (FastAPI)         │
       ├──────────────────────────────────────────┤
       │  Context Assembly                         │
       │    skills, memory, workspace, carapaces,  │
       │    tool RAG, conversation history         │
       │  Agent Loop                               │
       │    LLM ↔ tools until text response        │
       │  Task Worker (5s poll)                    │
       │  Heartbeat Worker (30s poll)              │
       │  Dispatchers (Slack, GH, webhook)         │
       └───┬──────────┬──────────┬────────────────┘
           │          │          │
    ┌──────┴───┐ ┌────┴────┐ ┌──┴───────┐
    │ Postgres │ │   LLM   │ │   MCP    │
    │(pgvector)│ │Providers│ │ Servers  │
    └──────────┘ └─────────┘ └──────────┘
                  OpenAI, Anthropic,
                  Gemini, Ollama,
                  OpenRouter, etc.
```

**Web UI** (`ui/`) — The primary interface. React Native/Expo app with chat, admin dashboard, workspace file browser, task management, and Mission Control.

**Integrations** — Slack, GitHub, and Frigate connect via the integration framework. Each provides webhooks, dispatchers, and lifecycle hooks.

**Agent Client** (`client/`) — Planned remote client for devices like a Raspberry Pi or a local workstation. Voice assistant (wake word, STT, TTS) + local tool executor (the server delegates shell commands and file operations to the client's machine). A legacy version exists and works for basic chat; a future rebuild will use the v1 API with full channel, workspace, and carapace support. See [docs/clients.md](docs/clients.md).

**Request flow:** `run_stream()` → `assemble_context()` → `run_agent_tool_loop()` → LLM ↔ tools → final response

## Bot Configuration

Bots are YAML files in `bots/` (gitignored). Seeded on first startup, then managed via the admin UI.

```yaml
id: assistant
name: "Assistant"
model: gemini/gemini-2.5-flash
system_prompt: |
  You are a helpful assistant.
carapaces: [qa, code-review]           # composable expertise bundles
memory_scheme: workspace-files          # file-based memory (MEMORY.md + logs)
history_mode: file                      # file-based conversation history
workspace:
  enabled: true
  type: docker
skills:
  - id: channel-workspace
    mode: on_demand
local_tools: [web_search, file, exec_command, schedule_task]
pinned_tools: [exec_command]
delegate_bots: [researcher]
harness_access: [claude-code]
context_compaction: true
```

See [CLAUDE.md](CLAUDE.md) for the full field reference.

## Upcoming: Workspace-Scoped Channels

Channels will get a direct `workspace_id` FK, enabling:
- **Sidebar workspace switcher** — filter channels, tasks, heartbeats, and usage by workspace
- **Auto-assignment** — new channels inherit their bot's workspace
- **Workspace-grouped analytics** — usage, costs, and activity scoped per workspace
- **Orchestrator stays global** — the Home channel sees everything regardless of filter

See [PLANS/workspace-scoped-channels.md](PLANS/workspace-scoped-channels.md) for the full design.

## Documentation

| Doc | Description |
|-----|-------------|
| [Setup Guide](docs/setup.md) | Installation, providers, workspaces, integrations, troubleshooting |
| [Slack Integration](docs/slack.md) | Slack bot setup, slash commands, channel config |
| [Delegation](docs/delegation.md) | Bot-to-bot delegation (immediate + deferred) |
| [Harnesses](docs/harness.md) | External CLI tools (Claude Code, Cursor) |
| [Integration Framework](docs/integrations/README.md) | Building custom integrations |
| [Backup & Restore](docs/BACKUP.md) | Automated Postgres + config backups to S3 |
| [Docker Deployment](docs/docker-deployment.md) | Production Docker setup |
| [Agent Client](docs/clients.md) | Remote voice assistant + local tool executor (Python CLI, Android) |

## Directory Structure

```
app/                Core server code
  agent/            Agent loop, context assembly, bots, carapaces, tasks, dispatchers
  db/               SQLAlchemy models + engine
  routers/          FastAPI endpoints
  services/         Heartbeat, compaction, delegation, channels, sandboxes
  tools/            Tool registry, MCP proxy, local tool implementations
bots/               Bot YAML configs (gitignored — user-created)
skills/             Skill markdown files (gitignored — user-created)
carapaces/          Carapace YAML definitions (shipped examples)
tools/              Drop-in Python tools (gitignored — user-created)
integrations/       Integration packages (auto-discovered)
  slack/            Slack Socket Mode bot
  github/           GitHub webhook handler
  frigate/          Frigate NVR integration
  mission_control/  Dashboard + task board
  example/          Template for new integrations
client/             Agent client (remote voice assistant + local tool executor)
ui/                 React Native/Expo web UI
migrations/         Alembic database migrations
scripts/            Dev, deploy, and ops scripts
docs/               Feature documentation
PLANS/              Multi-session implementation plans
```

## API

The server exposes REST + SSE endpoints. All require `Authorization: Bearer <API_KEY>` except `/health`.

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check |
| `/api/v1/chat/stream` | POST | Streaming chat (SSE) |
| `/api/v1/chat` | POST | Non-streaming chat |
| `/api/v1/channels` | GET | List channels |
| `/api/v1/sessions` | GET | List sessions |
| `/api/v1/tasks/{id}` | GET | Poll task status |
| `/api/v1/admin/*` | Various | Admin endpoints (bots, channels, tasks, usage, etc.) |

## Backup & Restore

```bash
./scripts/backup.sh              # dump DB + configs → S3
./scripts/restore.sh             # pull latest from S3 and restore
```

See [docs/BACKUP.md](docs/BACKUP.md) for setup and cron scheduling.

## Development

```bash
# Run tests (SQLite in-memory, no postgres needed)
pytest tests/ integrations/ -v

# Or via Docker
docker build -f Dockerfile.test -t agent-server-test . && docker run --rm agent-server-test

# UI typecheck (required after UI changes)
cd ui && npx tsc --noEmit
```

See [CLAUDE.md](CLAUDE.md) for architecture details, key files, and development guidelines.
