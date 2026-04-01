# Spindrel

Self-hosted AI agent server with persistent channels, composable expertise, workspace-driven memory, scheduled automation, and a pluggable integration framework.

> **Early Access** — Spindrel is under active development and in daily use by the maintainer. Core features are stable, but APIs, configuration formats, and database schemas may change between releases. Bug reports, feature requests, and contributions are welcome.

## Why Spindrel

- **Any LLM provider, mix and match** — OpenAI, Anthropic, Gemini, Ollama, OpenRouter, vLLM, or any OpenAI-compatible endpoint. Assign different providers per bot. Automatic retry with exponential backoff and fallback models.
- **Composable expertise (carapaces)** — Snap-on skillsets that bundle tools, skills, and behavioral instructions. Give a bot `carapaces: [qa, code-review]` and it instantly knows how to test and review code. Carapaces compose via `includes`.
- **Workspace-driven memory** — Bots maintain `MEMORY.md`, daily logs, and reference documents on disk — all indexed for RAG retrieval. No opaque vector-only memory.
- **Channel workspaces** — Per-channel file stores with schema-guided organization. 7 built-in templates (Software Dev, Research, QA, PM Hub, etc.) or custom schemas. Active files auto-inject into context.
- **Heartbeats + task scheduling** — Periodic autonomous check-ins with quiet hours and repetition detection. Schedule one-off or recurring tasks. Bots can self-schedule.
- **Integration framework** — Pluggable integrations with auto-discovery. Shipped: Slack, GitHub, Discord, Frigate, Mission Control, Arr (Sonarr/Radarr), Claude Code, Ingestion. Extend with your own.
- **Usage tracking + cost budgeting** — Per-bot token usage, cost tracking (with LiteLLM pricing data), and configurable budget limits.
- **Smart orchestrator bot** — Ships with an orchestrator that guides you through setup conversationally.
- **Web search** — SearXNG or DuckDuckGo, switchable at runtime from the admin UI.
- **Bot-to-bot delegation** — Orchestrator bots delegate to specialists, synchronously or as background tasks, up to 3 levels deep.

## Quick Start

```bash
git clone https://github.com/mtotho/spindrel.git
cd spindrel
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

## Documentation

| Guide | Description |
|-------|-------------|
| [Setup Guide](docs/setup.md) | Installation, providers, workspaces, integrations |
| [Slack Integration](docs/guides/slack.md) | Slack bot setup and channel config |
| [Discord Integration](docs/guides/discord.md) | Discord bot setup |
| [Gmail Integration](docs/guides/gmail.md) | Gmail integration |
| [Delegation](docs/guides/delegation.md) | Bot-to-bot delegation |
| [Harnesses](docs/guides/harnesses.md) | External CLI tools (Claude Code, Cursor) |
| [Secrets & Redaction](docs/guides/secrets.md) | Secret vault and automatic redaction |
| [Content Ingestion](docs/guides/ingestion.md) | Document ingestion pipeline |
| [Agent Client](docs/guides/clients.md) | Remote voice assistant + local tool executor |
| [Creating Integrations](docs/integrations/index.md) | Build custom integrations |
| [Backup & Restore](docs/backup.md) | Automated Postgres + config backups to S3 |
| [Docker Deployment](docs/docker-deployment.md) | Production Docker setup |

## Development

```bash
pytest tests/ integrations/ -v       # tests (SQLite in-memory, no postgres needed)
cd ui && npx tsc --noEmit            # UI typecheck (required after UI changes)
```

See [CLAUDE.md](CLAUDE.md) for architecture details, key files, and development guidelines.
