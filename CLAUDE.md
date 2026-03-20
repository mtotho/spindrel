# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

```bash
# Start all services (postgres, searxng, playwright, agent-server)
docker compose up

# Run server locally (requires postgres running)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Dev server with Slack bot auto-started (if SLACK_* vars set)
python scripts/dev-server.py

# Run migrations manually
alembic upgrade head

# CLI client (separate terminal)
cd client && pip install -e . && agent

# Run tests
pytest
```

## Project Architecture

This is a self-hosted LLM agent server built on FastAPI + PostgreSQL (pgvector). All LLM calls go through a LiteLLM proxy. There are no direct Anthropic/OpenAI SDK calls — the `openai` client is pointed at `LITELLM_BASE_URL`.

### Startup Sequence (app/main.py lifespan)
1. Run Alembic migrations
2. Load bot configs from `bots/*.yaml`
3. Load MCP server config from `mcp.yaml`
4. Discover and load tool files (`tools/` + `TOOL_DIRS`)
5. Import `app/tools/local/` to trigger `@register` decorators
6. Index all tool schemas for retrieval (RAG)
7. Fetch + index MCP tool schemas (warm cache)
8. Load skills from `skills/*.md`

### Request Flow (app/agent/loop.py)
`run_stream()` → RAG retrieval (skills, memory, knowledge) → tool retrieval → `run_agent_tool_loop()` → LLM → tool calls → LLM → ... → final response

The agent loop is iterative: LLM calls tools until it returns a text response (max `AGENT_MAX_ITERATIONS` iterations). Events are streamed as JSON lines.

### Configuration Layers
- **`.env`** → `app/config.py` (Pydantic Settings) — all runtime config
- **`bots/*.yaml`** → `app/agent/bots.py` (BotConfig) — per-bot behavior
- **`mcp.yaml`** — MCP server URLs and auth (supports `${ENV_VAR}` substitution)
- **`skills/*.md`** — Markdown knowledge files (chunked by `## ` headers, embedded)

### Tool System
Three tool types, all passed to the LLM in OpenAI function format:
- **Local tools** (`app/tools/local/`, `tools/`): Python functions decorated with `@register(openai_schema)`. Auto-discovered at startup.
- **MCP tools** (`mcp.yaml`): Remote HTTP endpoints implementing the MCP protocol. Proxied via `app/tools/mcp.py`.
- **Client tools** (`app/tools/client_tools.py`): Actions the client app handles (shell_exec, TTS toggle, etc.), declared to the LLM but executed client-side via a pending request/poll mechanism.

**Tool RAG** (`app/agent/tools.py`): On each request, user query is embedded and cosine-similarity matched against indexed tool schemas. Only top-K relevant tools above threshold are passed to the LLM. `pinned_tools` in bot YAML always bypass filtering. Bot opt-out: `tool_retrieval: false`.

**Adding a new local tool**: Create a `.py` file in `tools/` (or any `TOOL_DIRS` path). Use `@register({...openai schema...})` from `app/tools.registry`. The tool is auto-discovered on next server restart.

### RAG Systems (all use pgvector cosine similarity)
| System | Table | Source | Retrieval trigger |
|--------|-------|--------|------------------|
| Skills | `documents` | `skills/*.md` chunks | Every request (if bot lists skill) |
| Memory | `memories` | Compaction summaries | Every request (if memory enabled) |
| Knowledge | `bot_knowledge` | LLM-written docs | Every request (if knowledge enabled) |
| Tool schemas | `tool_embeddings` | All registered tools | Every request (if tool_retrieval enabled) |

### Key Files
- `app/agent/loop.py` — Core agent loop logic
- `app/agent/bots.py` — BotConfig dataclass and YAML loader
- `app/agent/tools.py` — Tool embedding/retrieval (RAG)
- `app/tools/registry.py` — Local tool registration, `_current_load_source_dir` sentinel for auto-discovery
- `app/tools/loader.py` — importlib-based tool file discovery
- `app/tools/mcp.py` — MCP client (60s cache, background re-index on cache miss)
- `app/services/compaction.py` — Context compaction with optional memory-phase (LLM saves memories before summarizing)
- `app/db/models.py` — All SQLAlchemy ORM models

### Database Notes
- `schema_` is the ORM attribute for the `schema` column in `tool_embeddings` (PostgreSQL reserved word)
- When using `sqlalchemy.dialects.postgresql.insert` (Core-level), use `**{"schema": value}` — Core doesn't translate ORM attribute names
- `EMBEDDING_DIMENSIONS` must match the vector dimensions in the DB; changing it requires re-embedding everything (no migration path)
- Alembic migrations run automatically on startup and are in `migrations/versions/`

### Bot YAML Fields
```yaml
id: my_bot
name: "My Bot"
model: gemini/gemini-2.5-flash      # LiteLLM model alias
system_prompt: |
  ...
local_tools: [web_search, save_memory]
mcp_servers: [homeassistant]
client_tools: [shell_exec]
skills: [arch_linux]
pinned_tools: [homeassistant_call_service]  # bypass tool retrieval
tool_retrieval: true                 # default true; false = always pass all tools
tool_similarity_threshold: 0.35      # override TOOL_RETRIEVAL_THRESHOLD
audio_input: transcribe              # or "native" (Gemini audio models)
context_compaction: true
compaction_interval: 10              # turns between compactions
compaction_keep_turns: 4
memory:
  enabled: true
  cross_session: true
knowledge:
  enabled: true
persona: true
docker_sandbox_profiles: [python-scratch]  # subset of sandbox_bot_access rows; omit = all
```

### Docker Sandboxes

Long-lived containers (OpenClaw-style) with `docker exec`. Scope modes: `session` (default), `client`, `agent`, `shared`. Enable with `DOCKER_SANDBOX_ENABLED=true`.

- **Design**: [DOCKER_SANDBOX_PLAN.md](DOCKER_SANDBOX_PLAN.md)
- **Service**: `app/services/sandbox.py` — `SandboxService` (ensure, exec, stop, remove, lock enforcement)
- **Tools**: `app/tools/local/sandbox.py` — `list_sandbox_profiles`, `ensure_sandbox`, `exec_sandbox`, `stop_sandbox`, `remove_sandbox`
- **Tables**: `sandbox_profiles`, `sandbox_bot_access`, `sandbox_instances` (migration 014)
- **Config**: `DOCKER_SANDBOX_ENABLED`, `DOCKER_SANDBOX_MOUNT_ALLOWLIST`, `DOCKER_SANDBOX_DEFAULT_TIMEOUT`, `DOCKER_SANDBOX_MAX_CONCURRENT`
- **Bot access**: grant via `sandbox_bot_access` DB rows; bot YAML `docker_sandbox_profiles` can further restrict the subset
- **Admin locking**: `locked_operations` JSONB on each instance — prevents bots from calling `stop`/`remove`/`ensure`/`exec` on that container
