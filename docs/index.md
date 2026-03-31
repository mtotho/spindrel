---
hide:
  - navigation
---

# Spindrel

**Self-hosted AI agent server** with persistent channels, composable expertise, workspace-driven memory, scheduled automation, and a pluggable integration framework.

Built on FastAPI + PostgreSQL (pgvector). Bring your own API keys — use any LLM provider.

---

<div class="grid cards" markdown>

-   :material-robot-outline:{ .lg .middle } **Multi-Bot Agents**

    ---

    Configure specialist bots with tools, skills, and delegation chains. Orchestrator bots coordinate work across specialists up to 3 levels deep.

-   :material-docker:{ .lg .middle } **Workspace Isolation**

    ---

    Docker-based environments with per-bot file access, skills injection, and workspace-scoped memory. Each bot gets its own persistent workspace.

-   :material-message-text-outline:{ .lg .middle } **Channels & Conversations**

    ---

    Persistent channels with streaming chat (SSE), context compaction, and file-based conversation history. Override model, tools, and skills per channel.

-   :material-puzzle-outline:{ .lg .middle } **Composable Expertise (Carapaces)**

    ---

    Reusable bundles of skills, tools, and behavior. A bot with `carapaces: [qa, code-review]` gets instant testing and review expertise. Carapaces compose via `includes`.

-   :material-heart-pulse:{ .lg .middle } **Heartbeats & Tasks**

    ---

    Periodic autonomous check-ins with quiet hours. Schedule one-off or recurring agent tasks. Bots can self-schedule via `schedule_task`.

-   :material-plug:{ .lg .middle } **Integration Framework**

    ---

    Pluggable integrations with auto-discovery. Shipped: Slack, GitHub, Frigate, Mission Control. Extend with your own via `INTEGRATION_DIRS`.

</div>

---

## Quick Start

```bash
git clone https://github.com/mtotho/spindrel.git
cd spindrel
bash setup.sh          # interactive wizard: deployment, LLM provider, auth
docker compose up -d   # or: bash scripts/dev-server.sh for local dev
```

The setup wizard configures `.env`, starts services, and creates a default bot. The Orchestrator bot guides you through the rest conversationally.

[:octicons-arrow-right-24: Full setup guide](setup.md)

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
```

**Request flow:** `run_stream()` → `assemble_context()` → `run_agent_tool_loop()` → LLM ↔ tools → final response

The agent loop is iterative — the LLM calls tools until it returns a text response. Events stream as JSON lines. LLM calls retry with exponential backoff and optional fallback models.

## Bot Configuration

Bots are YAML files in `bots/` (gitignored — you create your own). Seeded on first startup, then managed via the admin UI.

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

## Multi-Provider LLM

Connect any combination of providers simultaneously. Supports OpenAI-compatible endpoints (OpenAI, Gemini, Ollama, OpenRouter, vLLM, LiteLLM) and native Anthropic. Assign providers per bot or per channel.

Automatic retry with exponential backoff and fallback models. When using a LiteLLM proxy, Spindrel pulls model pricing data for accurate cost tracking.

## Tool System

Three tool types, all passed to the LLM in OpenAI function format:

| Type | Source | How |
|------|--------|-----|
| **Local** | `app/tools/local/`, `tools/` | Python functions with `@register` decorator |
| **MCP** | `mcp.yaml` | Remote HTTP endpoints (Model Context Protocol) |
| **Client** | Declared to LLM, executed client-side | Shell, TTS, file ops on remote devices |

**Tool RAG** surfaces only relevant tools per request via embedding similarity. Pin critical tools to always include them.

## Guides

<div class="grid cards" markdown>

-   [:material-setup: **Setup Guide**](setup.md)

    Installation, providers, workspaces, integrations, troubleshooting.

-   [:material-slack: **Slack Integration**](guides/slack.md)

    Connect Spindrel to Slack via Socket Mode.

-   [:material-directions-fork: **Delegation**](guides/delegation.md)

    Bot-to-bot delegation — immediate and deferred.

-   [:material-console: **Harnesses**](guides/harnesses.md)

    External CLI tools (Claude Code, Cursor) as agent subprocesses.

-   [:material-puzzle-edit-outline: **Creating Integrations**](integrations/index.md)

    Build custom integrations with routers, dispatchers, and hooks.

-   [:material-backup-restore: **Backup & Restore**](backup.md)

    Automated Postgres + config backups to S3.

-   [:material-docker: **Docker Deployment**](docker-deployment.md)

    Production setup with the sibling container pattern.

-   [:material-cellphone-link: **Agent Client**](guides/clients.md)

    Remote voice assistant + local tool executor.

</div>
