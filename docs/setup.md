# Spindrel Setup Guide

## Quick Start

```bash
# Clone and run the interactive setup wizard
git clone https://github.com/mtotho/spindrel.git
cd spindrel
bash setup.sh
```

The wizard will walk you through:
1. Choosing a deployment mode (Docker or local dev)
2. Configuring your LLM provider
3. Selecting a default model
4. Setting up authentication

After setup, start the server:

```bash
# Docker (recommended)
docker compose up -d

# Local development
bash scripts/dev-server.sh
```

Open the UI and the **Orchestrator** bot will greet you in the Home channel. It will walk you through creating your first bot, enabling integrations, and configuring workspaces — all conversationally.

## Manual Setup

If you prefer to configure everything manually:

### 1. Create .env

```bash
cp .env.example .env
```

Edit `.env` with your settings. Required fields:

| Variable | Description |
|----------|-------------|
| `API_KEY` | Bearer token for API authentication |
| `DATABASE_URL` | PostgreSQL connection string |
| `LITELLM_BASE_URL` | LLM API endpoint (LiteLLM proxy, OpenAI, etc.) |
| `LITELLM_API_KEY` | API key for LLM provider |

### 2. Start Services

```bash
docker compose up -d
```

## LLM Provider Configuration

### Default provider (`.env`)

The `.env` variables `LITELLM_BASE_URL` and `LITELLM_API_KEY` configure the default provider.
This uses an OpenAI-compatible client, so any endpoint that speaks the OpenAI chat completions
format works:

| Provider | LITELLM_BASE_URL | Notes |
|----------|-----------------|-------|
| LiteLLM proxy | `http://litellm:4000/v1` | Self-hosted, supports 100+ models |
| OpenAI | `https://api.openai.com/v1` | Direct OpenAI API |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | OpenAI-compatible endpoint |
| OpenRouter | `https://openrouter.ai/api/v1` | Multi-provider (Anthropic, Google, Meta, etc.) |
| Ollama | `http://localhost:11434/v1` | Local models |

### Additional providers (Admin UI)

You can configure multiple LLM providers simultaneously via **Admin UI > Providers**.
Each provider has its own API key, base URL, and rate limits. Supported provider types:

| Type | Description |
|------|-------------|
| `openai` | Direct OpenAI API |
| `openai-compatible` | Any OpenAI-compatible endpoint (Gemini, Ollama, vLLM, etc.) |
| `anthropic` | Direct Anthropic API (native support, no proxy needed) |
| `anthropic-compatible` | Anthropic-compatible proxies (Bedrock, etc.) |
| `litellm` | LiteLLM proxy instance |

Assign providers to individual bots via the `model_provider_id` field. Bots without a
provider ID fall back to the `.env` default.

**Anthropic (Claude) models**: Use OpenRouter as your default provider for the simplest
setup, or add a dedicated Anthropic provider in Admin UI > Providers for direct API access.

## Workspaces

Workspaces provide persistent file storage for bots. Each bot with `workspace.enabled: true` gets a directory for memory files, daily logs, and reference documents.

```bash
# .env
WORKSPACE_BASE_DIR=~/.spindrel-workspaces

# For Docker deployment (sibling container pattern):
WORKSPACE_HOST_DIR=/home/you/.spindrel-workspaces  # host path
WORKSPACE_LOCAL_DIR=/workspace-data                  # container mount
```

### Memory System

The recommended memory system is `workspace-files`:

```yaml
# bots/assistant.yaml
memory_scheme: workspace-files
workspace:
  enabled: true
```

This creates:
- `MEMORY.md` — curated knowledge base (stable facts, preferences)
- `logs/YYYY-MM-DD.md` — daily session logs
- `reference/` — longer guides and documentation

## Integrations

Integrations are discovered from `integrations/*/` directories. Each can provide:
- **Router** — API endpoints
- **Dispatcher** — message delivery
- **Hooks** — event handlers
- **Process** — background service (e.g., Slack bot, MQTT listener)
- **Tools** — bot-callable functions
- **Skills** — knowledge documents

### Enabling an Integration

1. Set required env vars (via `.env` or Admin UI > Integrations)
2. Restart the server

Integration processes (Slack bot, Frigate listener, etc.) auto-start when their required env vars are set. Toggle auto-start in Admin UI > Integrations.

### External Integrations

Add custom integration directories:

```bash
# .env
INTEGRATION_DIRS=/path/to/my-integrations:/another/path
```

## Directory Structure

```
agent-server/
├── app/                    # Core server code
├── bots/                   # Bot YAML configs (gitignored, user-created)
├── skills/                 # Skill markdown files (gitignored, user-created)
├── tools/                  # Custom tool scripts (gitignored, user-created)
├── integrations/           # Integration packages
│   ├── slack/             # Slack integration
│   ├── github/            # GitHub webhooks
│   ├── frigate/           # Frigate NVR
│   └── example/           # Template for new integrations
├── migrations/             # Alembic database migrations
├── scripts/                # Dev and setup scripts
├── ui/                     # React Native/Expo admin UI
├── docker-compose.yaml
├── .env                    # Runtime configuration (gitignored)
└── .env.example            # Template
```

## Troubleshooting

### Server won't start

1. Check PostgreSQL is running: `docker compose ps postgres`
2. Check `.env` has required fields: `API_KEY`, `DATABASE_URL`
3. Check logs: `docker compose logs agent-server`

### LLM calls failing

1. Verify `LITELLM_BASE_URL` is reachable from the server container
2. Check `LITELLM_API_KEY` is set correctly
3. Check bot model is available at the provider

### Integration process not starting

1. Check Admin UI > Integrations for status
2. Verify all required env vars are set (green pills)
3. Check server logs for the integration name
4. Try manual start via Admin UI process controls

### Migrations failing

Migrations run automatically on startup. If they fail:
1. Check database connectivity
2. Check `docker compose logs agent-server` for the specific error
3. Try `alembic upgrade head` manually inside the container
