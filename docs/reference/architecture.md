# Architecture

For the canonical document covering runtime context policy, replay/compaction behavior, history modes, context profiles, and prompt-budget reporting, see [Context Management](../guides/context-management.md).

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

For the exact runtime admission/replay policy, treat [Context Management](../guides/context-management.md) as the source of truth; this page stays at the system-overview level.

1. **Current time injection** (timezone-aware)
2. **Context pruning** (trim stale tool results from old turns)
3. **Channel-level overrides** (tool availability, enrolled skills, model overrides)
4. **Integration activation injection** (channel-activated integrations contribute declared tools)
5. **Memory scheme setup** (MEMORY.md, daily logs, reference index)
6. **Channel workspace files** (inject active `.md` files + schema)
7. **@mention tag resolution** (`@skill:name`, `@tool:name`, `@bot:name`)
8. **Skills injection** (per-bot working set + on-demand `get_skill` tool)
9. **Conversation history** (sections index + `read_conversation_history` tool)
10. **Workspace filesystem RAG** (semantic retrieval from indexed workspace files)
11. **Tool retrieval** (cosine similarity matching against tool schema embeddings)
12. **Channel prompt + system preamble**
13. **User message** (text or native audio)

### Tool Dispatch (`app/agent/tool_dispatch.py`)

Routes tool calls to the correct executor:

- **Local tools** — Python functions in `app/tools/local/` and `tools/`, decorated with `@register`
- **MCP tools** — Remote HTTP endpoints configured via Admin UI (or seeded from `mcp.yaml` on first boot)
- **Client tools** — Actions executed on the client side (shell, TTS, etc.)

### LLM Infrastructure (`app/agent/llm.py`)

Retry/backoff, fallback model support, and the LLM-call plumbing that consumes the context assembled upstream. Context-management policy itself is documented canonically in [Context Management](../guides/context-management.md).

## Skills + Tool Enrollment

Spindrel now relies on the existing skill and tool systems directly rather than a separate
capability layer.

- **Skills** are markdown documents loaded from `skills/`, `bots/*/skills/`, and integration skill folders.
- **Tools** are registered call surfaces from local tools, integrations, MCP servers, and client tools.
- **Enrollment** controls which skills are persistently available to a bot or channel.

Foldered skills are still just skills. A folder such as `skills/shared/orchestrator/` can
provide a root skill (`index.md`) plus child skills addressable by path ID.

## Integration Activation

Integrations can declare an **activation manifest** in their `setup.py` that specifies which tools to expose when the integration is activated on a channel.

```python
# integrations/mission_control/setup.py
"activation": {
    "tools": ["create_task_card", "move_task_card"],
    "requires_workspace": True,
}
```

During context assembly, the system checks each channel's active integrations and makes their
declared tools available on that channel. Integration-shipped skills remain normal skills and
can be enrolled or fetched through the regular skill system.

**Workspace file organization:** integration guidance should live in normal skills and prompt
templates. Templates are optional and remain available for more structured workspace layouts.

## Channel Workspaces

Per-channel file stores with schema-guided organization.

- **Storage:** `~/.spindrel-workspaces/{bot_id_or_shared}/channels/{channel_id}/`
- **Active files** (`.md` at root): auto-injected into context every request
- **Archive files** (`archive/`): searchable via tool, not auto-injected
- **Data files** (`data/`): listed but not injected; referenced via search tool

**Schema templates** define file structure (headings, column formats, which files to create). Templates can declare compatibility with specific integrations — e.g., a "Software Dev" template can define `tasks.md`, `status.md`, and other project files expected by the active toolset.

**Indexing:** Background re-index on every message (content-hash makes it cheap). Searchable via `search_channel_workspace` and `search_channel_archive` tools.

## Task Pipelines + Sub-Sessions

Reusable multi-step automations are modeled as `Task` rows running in pipeline mode, not as a
separate workflow system. Pipelines support `exec`, `tool`, `agent`, `user_prompt`, and
`foreach` steps with conditions, approval gates, params, and cross-bot delegation.

- **Executor:** task worker + pipeline step engine advance the run through its step list
- **Execution model:** pipeline runs write into a dedicated child `Session`, so every run has a
  full chat-native transcript
- **Triggers:** admin/API launch, bot tools such as `run_pipeline`, heartbeat `pipeline_id`, and
  per-channel subscriptions
- **UI model:** the parent channel gets an anchor card; the run itself renders as a sub-session
  modal or docked transcript
- **Legacy note:** old workflows are deprecated and retained only for historical compatibility

## Configuration Layers

| Layer | Source | Scope |
|-------|--------|-------|
| Environment | `.env` → `app/config.py` | Runtime config |
| Bot Config | `bots/*.yaml` → DB (seed-once) | Per-bot behavior |
| Skills | `skills/*.md` → DB (re-embed on change) | Knowledge injection |
| Tasks / Pipelines | DB `tasks` rows + `app/data/system_pipelines/` | Multi-step automations, scheduled runs, pipeline definitions |
| MCP Servers | Admin UI (or `mcp.yaml` seed) → DB | Tool endpoints |
| Integrations | `integrations/*/` + `INTEGRATION_DIRS` | External service connections |

## Database

PostgreSQL with pgvector for embedding storage. Key tables:

- `channels` — persistent conversation containers
- `channel_integrations` — per-channel integration bindings with `activated` flag
- `sessions` / `messages` — conversation history
- `bots` — bot configuration (seeded from YAML)
- `prompt_templates` — workspace schema templates
- `tasks` — scheduled work, deferred work, and pipeline definitions/runs
- `channel_heartbeats` / `heartbeat_runs` — periodic automated prompts
- `trace_events` — LLM usage tracking (tokens, cost, provider)
- `tool_embeddings` — tool schema RAG index
- `documents` — skill chunk RAG index
- `filesystem_chunks` — workspace file content index

## Background Workers

- **Task worker** — polls every 5s for due tasks, runs agent loop, dispatches results
- **Heartbeat worker** — polls every 30s for due heartbeats, creates tasks, respects quiet hours
- **File watcher** — monitors workspace directories for changes, triggers re-indexing
