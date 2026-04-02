# Architecture

## System Overview

Spindrel is a FastAPI application backed by PostgreSQL with pgvector. It supports multiple LLM provider types: OpenAI-compatible endpoints (OpenAI, Gemini, Ollama, OpenRouter, LiteLLM, vLLM), native Anthropic (direct API and Bedrock), and any custom provider configured via the admin UI. Each bot can use a different provider via `model_provider_id`. The default provider is configured via `LITELLM_BASE_URL`/`LITELLM_API_KEY` in `.env`.

## Request Flow

```
run_stream() → assemble_context() → run_agent_tool_loop() → _llm_call() → dispatch_tool_call()
```

The agent loop is iterative: the LLM calls tools until it returns a text response (max `AGENT_MAX_ITERATIONS` iterations). Events stream as JSON lines. LLM calls retry with exponential backoff for transient errors, with optional fallback model.

## Key Components

### Agent Loop (`app/agent/loop.py`)

The core iteration skeleton. Handles stream orchestration, tool call accumulation, and response assembly.

### Context Assembly (`app/agent/context_assembly.py`)

Builds the message array for each LLM call. Injects:

- System prompt (bot config + channel overrides)
- Workspace skills (pinned, RAG, on-demand)
- Conversation history (from file or DB)
- Tool schemas (via RAG or pinned)
- Channel workspace prompt and schema

### Tool Dispatch (`app/agent/tool_dispatch.py`)

Routes tool calls to the correct executor:

- **Local tools** — Python functions in `app/tools/local/` and `tools/`, decorated with `@register`
- **MCP tools** — Remote HTTP endpoints defined in `mcp.yaml`
- **Client tools** — Actions executed on the client side (shell, TTS, etc.)

### LLM Infrastructure (`app/agent/llm.py`)

Retry/backoff, fallback model support, tool result summarization for context management.

## Configuration Layers

| Layer | Source | Scope |
|-------|--------|-------|
| Environment | `.env` → `app/config.py` | Runtime config |
| Bot Config | `bots/*.yaml` → DB (seed-once) | Per-bot behavior |
| Skills | `skills/*.md` → DB (re-embed on change) | Knowledge injection |
| MCP Servers | `mcp.yaml` | Tool endpoints |
| Integrations | `integrations/*/` + `INTEGRATION_DIRS` | External service connections |

## Database

PostgreSQL with pgvector for embedding storage. Key tables:

- `channels` — persistent conversation containers
- `sessions` / `messages` — conversation history
- `bots` — bot configuration (seeded from YAML)
- `shared_workspaces` / `shared_workspace_bots` — Docker workspace environments
- `tasks` — scheduled and on-demand agent execution
- `channel_heartbeats` — periodic automated prompts
- `trace_events` — LLM usage tracking (tokens, cost, provider)
- `tool_embeddings` — tool schema RAG index
- `documents` — skill chunk RAG index

## Background Workers

- **Task worker** — polls every 5s for due tasks, runs agent loop, dispatches results
- **Heartbeat worker** — polls every 30s for due heartbeats, creates tasks, respects quiet hours
