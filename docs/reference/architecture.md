# Architecture

## System Overview

Spindrel is a FastAPI application backed by PostgreSQL with pgvector. It supports multiple LLM provider types: OpenAI-compatible endpoints (OpenAI, Gemini, Ollama, OpenRouter, LiteLLM, vLLM), native Anthropic (direct API and Bedrock), and any custom provider configured via the admin UI. Each bot can use a different provider via `model_provider_id`. The default provider is configured via `LLM_BASE_URL`/`LLM_API_KEY` in `.env` (aliases `LITELLM_BASE_URL`/`LITELLM_API_KEY` also accepted).

## Request Flow

```
run_stream() → assemble_context() → run_agent_tool_loop() → _llm_call() → dispatch_tool_call()
```

The agent loop is iterative: the LLM calls tools until it returns a text response (max `AGENT_MAX_ITERATIONS` iterations). Events stream as JSON lines. LLM calls retry with exponential backoff for transient errors, with optional fallback model.

## Key Components

### Agent Loop (`app/agent/loop.py`)

The core iteration skeleton. Handles stream orchestration, tool call accumulation, and response assembly.

### Context Assembly (`app/agent/context_assembly.py`)

Builds the message array for each LLM call. The pipeline runs in order:

1. **Current time injection** (timezone-aware)
2. **Context pruning** (trim stale tool results from old turns)
3. **Channel-level overrides** (tool/skill override/disabled lists, model overrides)
4. **Workspace DB skills merge** (if bot has `shared_workspace_id`)
5. **Carapace resolution** (merge skills + tools + system prompt fragments from carapaces)
6. **Integration activation injection** (auto-inject carapaces from activated integrations)
7. **Memory scheme setup** (MEMORY.md, daily logs, reference index)
8. **Channel workspace files** (inject active `.md` files + schema)
9. **@mention tag resolution** (`@skill:name`, `@tool:name`, `@bot:name`)
10. **Skills injection** (pinned: full content; RAG: semantic match; on-demand: index + get_skill tool)
11. **Conversation history** (sections index + `read_conversation_history` tool)
12. **Workspace filesystem RAG** (semantic retrieval from indexed workspace files)
13. **Tool retrieval** (cosine similarity matching against tool schema embeddings)
14. **Channel prompt + system preamble**
15. **User message** (text or native audio)

### Tool Dispatch (`app/agent/tool_dispatch.py`)

Routes tool calls to the correct executor:

- **Local tools** — Python functions in `app/tools/local/` and `tools/`, decorated with `@register`
- **MCP tools** — Remote HTTP endpoints configured via Admin UI (or seeded from `mcp.yaml` on first boot)
- **Client tools** — Actions executed on the client side (shell, TTS, etc.)

### LLM Infrastructure (`app/agent/llm.py`)

Retry/backoff, fallback model support, tool result summarization for context management.

## Carapaces

Composable expertise bundles that give bots instant capabilities in specific domains. A carapace bundles:

- **Tools** — function schemas added to the LLM's tool list
- **Skills** — knowledge documents injected into context (pinned, RAG, or on-demand)
- **System prompt fragment** — behavioral instructions always injected into the system prompt

Carapaces compose via `includes` — a carapace can reference others, resolved depth-first with cycle detection (max 5 levels). Source types: `file` (YAML, read-only), `manual` (API/UI), `integration`, `tool`.

**Fragment-as-index pattern:** The system prompt fragment acts as an index to on-demand skills. It must contain concrete trigger phrases ("when the user asks to X, fetch skill Y") — not just topic descriptions. Without clear triggers, the bot won't know when to load deeper skills.

Core logic: `app/agent/carapaces.py`. Bot config: `carapaces: [qa, code-review]`. Channel overrides: `carapaces_extra` (add) and `carapaces_disabled` (remove).

## Integration Activation

Integrations can declare an **activation manifest** in their `setup.py` that specifies which carapaces to inject when the integration is activated on a channel.

```python
# integrations/mission_control/setup.py
"activation": {
    "carapaces": ["mission-control"],
    "requires_workspace": True,
    "compatible_templates": ["mission-control"],
}
```

During context assembly, the system checks each channel's active integrations and auto-injects their declared carapaces. This gives the bot integration-specific tools and skills without any manual bot configuration.

**Template compatibility:** Integrations declare which workspace template tags they work with. The UI highlights compatible templates when an integration is active, guiding users to pick file structures that match the integration's tools.

## Channel Workspaces

Per-channel file stores with schema-guided organization.

- **Storage:** `~/.spindrel-workspaces/{bot_id_or_shared}/channels/{channel_id}/`
- **Active files** (`.md` at root): auto-injected into context every request
- **Archive files** (`archive/`): searchable via tool, not auto-injected
- **Data files** (`data/`): listed but not injected; referenced via search tool

**Schema templates** define file structure (headings, column formats, which files to create). Templates can declare compatibility with specific integrations — e.g., a "Software Dev" template tagged as Mission Control-compatible defines `tasks.md` with the kanban format that MC tools expect.

**Indexing:** Background re-index on every message (content-hash makes it cheap). Searchable via `search_channel_workspace` and `search_channel_archive` tools.

## Workflows

Reusable multi-step automations defined in YAML. Each workflow is a sequence of steps with conditions, approval gates, and cross-bot delegation.

- **Executor:** `app/services/workflow_executor.py` — state machine for advancing runs
- **Execution model:** Workflows create Tasks (task_type="workflow"), the task worker executes them, and a completion hook advances the workflow to the next step
- **Triggers:** API call, bot tool (`manage_workflow`), or heartbeat schedule
- **Session modes:** `shared` (steps share channel context) or `isolated` (fresh context per step)
- **Features:** Conditions, approval gates, scoped secrets, parameter validation

## Configuration Layers

| Layer | Source | Scope |
|-------|--------|-------|
| Environment | `.env` → `app/config.py` | Runtime config |
| Bot Config | `bots/*.yaml` → DB (seed-once) | Per-bot behavior |
| Carapaces | `carapaces/*.yaml` + `integrations/*/carapaces/` | Composable expertise |
| Skills | `skills/*.md` → DB (re-embed on change) | Knowledge injection |
| Workflows | `workflows/*.yaml` + `integrations/*/workflows/` | Multi-step automations |
| MCP Servers | Admin UI (or `mcp.yaml` seed) → DB | Tool endpoints |
| Integrations | `integrations/*/` + `INTEGRATION_DIRS` | External service connections |

## Database

PostgreSQL with pgvector for embedding storage. Key tables:

- `channels` — persistent conversation containers
- `channel_integrations` — per-channel integration bindings with `activated` flag
- `sessions` / `messages` — conversation history
- `bots` — bot configuration (seeded from YAML)
- `carapaces` — composable expertise bundles
- `prompt_templates` — workspace schema templates
- `tasks` — scheduled and on-demand agent execution
- `workflows` / `workflow_runs` — multi-step automation definitions and execution history
- `channel_heartbeats` / `heartbeat_runs` — periodic automated prompts
- `trace_events` — LLM usage tracking (tokens, cost, provider)
- `tool_embeddings` — tool schema RAG index
- `documents` — skill chunk RAG index
- `filesystem_chunks` — workspace file content index

## Background Workers

- **Task worker** — polls every 5s for due tasks, runs agent loop, dispatches results
- **Heartbeat worker** — polls every 30s for due heartbeats, creates tasks, respects quiet hours
- **File watcher** — monitors workspace directories for changes, triggers re-indexing
