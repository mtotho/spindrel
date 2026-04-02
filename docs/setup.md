# Spindrel Setup Guide

## Quick Start

One command to get started:

```bash
# Clone and run the interactive setup wizard
git clone https://github.com/mtotho/spindrel.git
cd spindrel
bash setup.sh
```

Or as a one-liner (clones the repo for you):

```bash
curl -fsSL https://raw.githubusercontent.com/mtotho/spindrel/master/setup.sh | bash
```

### What the wizard does

### Prerequisites

- **Python 3.12+** with `pip` or `ensurepip` (on Debian/Ubuntu: `apt install python3-pip python3-venv`)
- **Docker** with the Compose v2 plugin
- **git**

The setup wizard is an interactive TUI that checks these prerequisites, then walks you through:

1. **Deployment mode** — Docker (recommended) or local dev
2. **LLM provider** — Pick from presets (OpenAI, OpenRouter, Google Gemini, LiteLLM proxy, Ollama/vLLM) or enter a custom OpenAI-compatible endpoint
3. **Default model** — Provider-specific model list with option for custom model names
4. **Web search backend** — SearXNG (built-in or external), DuckDuckGo, or disabled
5. **API authentication** — Auto-generate a random key or enter your own

The wizard generates `.env` and offers to start the server immediately. The whole process takes about 60 seconds.

### After setup

Open the UI and the **Orchestrator** bot will greet you in the Home channel. It walks you through creating your first bot, enabling integrations, and configuring workspaces — all conversationally.

> **Tip:** You can add more LLM providers later via **Admin UI > Providers** (Anthropic direct, additional OpenAI-compatible endpoints, etc.). The wizard just configures the default.

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

> **Tip:** These `.env` values and all other configured secrets (provider keys, integration tokens, etc.) are automatically redacted from tool results and LLM output. You can also store additional secrets via **Admin > Security > Secrets** — see the [Secrets & Redaction guide](guides/secrets.md).

### 2. Start Services

```bash
docker compose up -d
```

## Web Search

The `web_search` tool backend is controlled by `WEB_SEARCH_MODE` (configurable at runtime in **Settings > Web Search**):

| Mode | Backend | Containers | Description |
|---|---|---|---|
| `searxng` (default) | SearXNG + Playwright | built-in or external | Self-hosted, private, JS rendering |
| `ddgs` | DuckDuckGo + public engines | none | Lightweight, no infrastructure needed |
| `none` | disabled | none | Bring your own search tool in `tools/` |

### SearXNG mode (default)

**Built-in containers** (simplest):

```bash
WEB_SEARCH_MODE=searxng
COMPOSE_PROFILES=web-search
```

**External instances** (bring your own SearXNG/Playwright):

```bash
WEB_SEARCH_MODE=searxng
SEARXNG_URL=http://my-searxng:8080
PLAYWRIGHT_WS_URL=ws://my-playwright:3000   # optional — fetch_url falls back to httpx
```

Both URLs are also configurable at runtime in **Settings > Web Search**. Private — queries never leave your network.

### DuckDuckGo mode

```bash
WEB_SEARCH_MODE=ddgs
```

Uses `ddgs` to search DuckDuckGo, Google, Brave, and other public engines. No containers, no API keys. Good for occasional searches.

### Disabled

```bash
WEB_SEARCH_MODE=none
```

The `web_search` tool returns an error directing bots to ask the admin. Add custom search tools in `tools/`.

You can switch modes at any time via the Settings UI — no restart required. The `fetch_url` tool always works regardless of mode (falls back to httpx when Playwright is unavailable).

> **Upgrading?** If you already use web search, add `COMPOSE_PROFILES=web-search` to your `.env` — without it, SearXNG and Playwright containers won't start after this update.

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

For cost tracking, budget limits, and spend forecasting, see the [Usage & Billing guide](guides/usage-and-billing.md).

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
- **Carapaces** — composable expertise bundles
- **Templates** — workspace schema templates

### Enabling an Integration

1. Set required env vars (via `.env` or Admin UI > Integrations)
2. Restart the server

Integration processes (Slack bot, Frigate listener, etc.) auto-start when their required env vars are set. Toggle auto-start in Admin UI > Integrations.

### Activating on a Channel

Once an integration is enabled, you can **activate** it on individual channels to inject its tools, skills, and behavioral instructions automatically:

1. Open a channel and go to the **Integrations** tab
2. Click **Activate** on the integration
3. The integration's carapace is injected — the bot gains new capabilities for this channel only

For example, activating Mission Control gives the bot task board tools, project management skills, and knowledge of the MC protocol — without manually configuring any of that on the bot.

### Workspace Templates

Integrations can ship workspace templates that define file structures compatible with their tools. After activating an integration:

1. Go to the channel's **Workspace** tab
2. Compatible templates appear under **Suggested schemas** with a green badge
3. Pick one — the bot now knows how to organize workspace files in the right format

See the [Templates & Activation guide](guides/templates-and-activation.md) for the full walkthrough.

### Workspace Integrations

The shared workspace includes an `integrations/` directory that is automatically added to the integration discovery path at startup. Bots can scaffold integrations directly at `/workspace/integrations/` — they're discovered on the next server restart, just like any other integration directory.

This is the easiest way to add custom integrations: ask a bot (or use Claude Code) to write the integration code, then restart the server.

### Custom Tools

Drop a `.py` file in `tools/` with a `@register` decorator and restart — the tool is available to any bot:

```python
# tools/my_tool.py
from app.tools.registry import register

@register({
    "type": "function",
    "function": {
        "name": "my_tool",
        "description": "Does something useful.",
        "parameters": {"type": "object", "properties": {}},
    },
})
async def my_tool() -> str:
    return '{"result": "ok"}'
```

Additional tool directories can be loaded via `TOOL_DIRS`:

```bash
# .env
TOOL_DIRS=/path/to/more/tools
```

### Personal Extensions Repo

Keep your own tools, carapaces, and skills in a separate repo and load everything via `INTEGRATION_DIRS`. Structure your repo with a subdirectory that contains `tools/`, `carapaces/`, and/or `skills/`:

```
my-extensions/              # your repo
└── personal/               # becomes a discoverable extension
    ├── tools/
    │   └── weather.py      # auto-discovered tool
    ├── carapaces/
    │   └── baking/
    │       └── carapace.yaml
    └── skills/
        └── my-skill.md
```

```bash
# .env
INTEGRATION_DIRS=/path/to/my-extensions
```

No `setup.py` or boilerplate needed — the server auto-discovers tools, carapaces, and skills from any subdirectory.

For Docker, mount the directory into the container:

```yaml
# docker-compose.override.yml
services:
  agent-server:
    volumes:
      - /home/you/my-extensions:/app/ext:ro
    environment:
      - INTEGRATION_DIRS=/app/ext
```

See the [Custom Tools & Extensions guide](guides/custom-tools.md) for a full walkthrough with examples.

### External Integrations

For full integrations with webhooks, dispatchers, and background processes:

```bash
# .env
INTEGRATION_DIRS=/path/to/my-integrations:/another/path
```

See [Creating Integrations](integrations/index.md) for the complete guide.

## Directory Structure

```
agent-server/
├── app/                    # Core server code
├── bots/                   # Bot YAML configs (gitignored, user-created)
├── skills/                 # Skill markdown files (gitignored, user-created)
├── tools/                  # Custom tool scripts (gitignored, user-created)
├── carapaces/              # Carapace YAML definitions (composable expertise bundles)
├── integrations/           # Integration packages
│   ├── slack/             # Slack integration
│   ├── github/            # GitHub webhooks
│   ├── discord/           # Discord integration
│   ├── gmail/             # Gmail IMAP polling
│   ├── frigate/           # Frigate NVR
│   ├── mission_control/   # Dashboard + project management
│   ├── arr/               # Sonarr/Radarr media management
│   ├── claude_code/       # Claude Code CLI harness
│   ├── bluebubbles/       # iMessage via BlueBubbles
│   ├── ingestion/         # Document ingestion pipeline
│   └── example/           # Template for new integrations
├── workflows/              # Workflow YAML definitions (multi-step automations)
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

1. Check admin/logs for trace information

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
