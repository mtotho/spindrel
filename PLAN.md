# Agent Server — Implementation Plan

## Overview

A self-hosted FastAPI agent server on a local network. Provides a text chat interface to a configurable LLM backend (LiteLLM). Supports multiple named bots, persistent session management, always-on RAG (stubbed initially), and a hybrid tool system combining upstream MCP tools (via LiteLLM) and locally-defined Python tools.

Clients are thin. STT and TTS happen client-side. The server is text-in, text-out. A `/voice` endpoint is out of scope for now — all clients hit `/chat`.

---

## Tech Stack

| Component        | Choice                                  |
|------------------|-----------------------------------------|
| Runtime          | Python 3.12+                            |
| Framework        | FastAPI (async)                         |
| Database         | PostgreSQL 16 with pgvector extension   |
| ORM              | SQLAlchemy 2.x (async) + Alembic       |
| LLM Backend      | LiteLLM proxy (OpenAI-compatible)       |
| HTTP Client      | httpx (async)                           |
| Containerization | Docker Compose                          |

---

## Project Structure

```
agent-server/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app, lifespan, route registration
│   ├── config.py                # Settings from env vars (pydantic-settings)
│   ├── dependencies.py          # FastAPI deps: db session, auth
│   │
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── chat.py              # POST /chat
│   │   └── sessions.py          # GET/DELETE /sessions endpoints
│   │
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── loop.py              # Core agent loop (tool call iteration)
│   │   ├── bots.py              # Bot registry and config loader
│   │   └── rag.py               # Stub: retrieve_context() returns []
│   │
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── registry.py          # Central tool dispatcher
│   │   ├── mcp.py               # Fetch + proxy MCP tools from LiteLLM
│   │   └── local/               # Custom Python tool implementations
│   │       ├── __init__.py      # Imports all tool modules to trigger registration
│   │       └── example.py       # get_current_time, send_notification
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   └── sessions.py          # Session CRUD, message persistence
│   │
│   └── db/
│       ├── __init__.py
│       ├── engine.py            # Async engine + session factory
│       └── models.py            # SQLAlchemy ORM models
│
├── client/                      # Test client / desktop client (separate package)
│   ├── agent_client/
│   │   ├── __init__.py
│   │   ├── cli.py               # Phase 1: interactive REPL
│   │   ├── client.py            # HTTP client (shared across all phases)
│   │   ├── config.py            # Load settings from config file
│   │   ├── state.py             # Session ID persistence
│   │   ├── audio.py             # Phase 2: recording + STT (optional import)
│   │   └── daemon.py            # Phase 3: background process (future)
│   └── pyproject.toml
│
├── bots/                        # Bot definition files (YAML)
│   └── default.yaml
│
├── migrations/                  # Alembic migration directory
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│
├── docker-compose.yml
├── Dockerfile
├── alembic.ini
├── pyproject.toml
├── .env.example
└── .gitignore
```

---

## Configuration

Environment variables via pydantic-settings (`app/config.py`):

```
# Auth
API_KEY=your-secret-bearer-key

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/agentdb

# LiteLLM
LITELLM_BASE_URL=http://litellm:4000/v1
LITELLM_API_KEY=your-litellm-key
LITELLM_MCP_URL=http://litellm:4000/mcp

# Agent
AGENT_MAX_ITERATIONS=15

# RAG (stubbed — values here for forward-compat)
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=1536
RAG_TOP_K=5
RAG_SIMILARITY_THRESHOLD=0.75
```

Settings class validates and exposes these with defaults. `AGENT_MAX_ITERATIONS` caps the tool-call loop.

---

## Database Schema

Three tables. `documents` is defined but unused until RAG is implemented.

### sessions

| Column      | Type         | Notes                              |
|-------------|--------------|------------------------------------|
| id          | UUID PK      | Client-generated, sent in request  |
| client_id   | TEXT NOT NULL | Device/user identifier             |
| bot_id      | TEXT NOT NULL | Which bot config, default "default"|
| created_at  | TIMESTAMPTZ  | Default now()                      |
| last_active | TIMESTAMPTZ  | Updated on each turn               |
| metadata    | JSONB        | Extensible, default {}             |

### messages

| Column       | Type         | Notes                                    |
|--------------|--------------|------------------------------------------|
| id           | UUID PK      | Server-generated                         |
| session_id   | UUID FK      | References sessions(id) ON DELETE CASCADE|
| role         | TEXT NOT NULL | user / assistant / tool / system         |
| content      | TEXT         | Nullable (assistant tool_calls have none)|
| tool_calls   | JSONB        | Raw tool_calls from model, if present    |
| tool_call_id | TEXT         | For role=tool messages                   |
| created_at   | TIMESTAMPTZ  | Default now()                            |

### documents (RAG — schema only, no app code touches this yet)

| Column    | Type          | Notes                        |
|-----------|---------------|------------------------------|
| id        | UUID PK       | Server-generated             |
| content   | TEXT NOT NULL  | Chunk text                   |
| embedding | VECTOR(1536)  | pgvector                     |
| source    | TEXT          | Filename, URL, label         |
| metadata  | JSONB         | Default {}                   |
| created_at| TIMESTAMPTZ   | Default now()                |

Index: HNSW on `embedding` with `vector_cosine_ops` (preferred over IVFFlat — no data needed to build, better recall).

---

## Session Management

The server owns all session state. Clients are stateless except for persisting their current `session_id` locally.

### Session ID contract

- `session_id` is always a client-generated UUID.
- If the server receives a `session_id` it hasn't seen, it creates a new session row **with that ID**.
- If the server receives a known `session_id`, it loads and continues the conversation.
- If no `session_id` is sent, the server generates one and returns it.
- The response always includes `session_id` so the client can persist it.

### System prompt handling

The system prompt is stored as the first message (role=system) in the messages table when a session is created. On resume, it's loaded from the DB along with the rest of history. This means:
- The system prompt is immutable per session (consistent behavior within a conversation).
- If the bot config changes, new sessions get the new prompt; old sessions keep theirs.

### `load_or_create(db, session_id, client_id, bot_id)` → `(UUID, list[dict])`

1. If `session_id` is provided and exists in DB: load all messages ordered by `created_at`, return them.
2. If `session_id` is provided but doesn't exist: create session row **with that UUID as PK**, insert system prompt as first message, return `[system_msg]`.
3. If `session_id` is None: generate a UUID server-side, create session, insert system prompt, return `[system_msg]`.

### `persist_turn(db, session_id, messages, from_index)`

Persists only messages added during the current turn (from `from_index` onward). Handles conversion from OpenAI SDK message objects to dicts before storing.

Update `sessions.last_active` to now().

---

## Bot Configuration

YAML files in `bots/` directory, loaded at startup into a dict keyed by `id`.

### Schema

```yaml
# bots/default.yaml
id: default
name: "Default Assistant"
model: gpt-4.1-mini              # LiteLLM model alias
system_prompt: |
  You are a helpful assistant.
mcp_servers: []                   # LiteLLM MCP server aliases this bot can use
local_tools: []                   # Local tool names this bot can use
rag: false                        # Whether to inject RAG context
```

### `get_bot(bot_id)` → `BotConfig`

Returns the config for a given bot ID. Raises `HTTPException(404)` if not found. `BotConfig` is a dataclass or Pydantic model with fields: `id`, `name`, `model`, `system_prompt`, `mcp_servers: list[str]`, `local_tools: list[str]`, `rag: bool`.

All YAML files in `bots/` are loaded once at startup. No hot-reload initially.

---

## Tool System

Two categories, unified dispatch.

### Category 1: Local Python Tools

Defined in `app/tools/local/`. Each tool is an async function decorated with `@register(schema)` that populates a module-level registry.

**Registry (`app/tools/registry.py`):**
- `@register(schema)` — decorator that stores the function + OpenAI function schema.
- `get_local_tool_schemas(allowed_names) → list[dict]` — returns schemas for the specified tool names.
- `dispatch(tool_name, arguments, mcp_servers) → str` — routes to local function or MCP. Local takes priority.

**Critical rules:**
- All tool functions must be async.
- Blocking calls (subprocess, file I/O) must use `asyncio.create_subprocess_exec` or `asyncio.to_thread`.
- Tool exceptions are caught in dispatch and returned as `{"error": "..."}` to the model, never crash the loop.
- `app/tools/local/__init__.py` imports all tool modules so decorators fire at import time.

### Category 2: MCP Tools (via LiteLLM)

MCP tools are registered in LiteLLM's config. The agent server fetches their schemas and proxies execution.

**`app/tools/mcp.py`:**
- `fetch_mcp_tools(allowed_servers) → list[dict]` — fetches tool schemas from LiteLLM MCP endpoint, filters by allowed server prefixes, caches with TTL (60s). Uses `asyncio.Lock` to prevent thundering herd on cache miss.
- `call_mcp_tool(tool_name, arguments) → str` — forwards execution to LiteLLM MCP endpoint, returns result as string.

**Tool name convention:** LiteLLM namespaces MCP tools as `{server_alias}_{tool_name}`. The bot config lists allowed `mcp_servers` by alias. Dispatch matches by prefix.

### Unified dispatch flow

```
Model returns tool_call(name, args)
  → Is name in local registry? → Call local function
  → Does name match an allowed MCP server prefix? → Forward to LiteLLM MCP
  → Neither? → Return {"error": "Unknown tool: {name}"}
```

---

## Agent Loop

`app/agent/loop.py` — `run(messages, bot, user_message) → str`

### Flow

1. **RAG injection** (if `bot.rag` is true): call `retrieve_context(user_message)`. If chunks returned, append a system message with the context immediately before the user message. (Currently stubbed to return `[]`.)
2. **Append user message** to messages list.
3. **Assemble tools**: fetch MCP tool schemas + get local tool schemas for this bot.
4. **Enter loop** (max `AGENT_MAX_ITERATIONS` iterations):
   a. Call `client.chat.completions.create(model, messages, tools, tool_choice="auto")`.
   b. Get response message. **Convert to dict** before appending to messages list.
   c. If no `tool_calls` → return `msg.content` (final answer).
   d. For each tool call: dispatch via registry, catch exceptions, append tool result message.
5. **If max iterations exceeded**: append a system message telling the model to respond without tools, make one final call, return whatever it says.

### Key implementation details

- **OpenAI client**: `AsyncOpenAI(base_url=settings.LITELLM_BASE_URL, api_key=settings.LITELLM_API_KEY)`.
- **Message serialization**: The OpenAI SDK returns Pydantic objects. Before appending assistant messages to the list (and before persistence), convert to dict via `msg.model_dump(exclude_none=True)`. Tool result messages are already dicts.
- **Timeouts**: Set `httpx` timeout on the OpenAI client (60s default). This prevents hanging on slow model responses.
- **Empty tool list**: If a bot has no tools, pass `tools=None` and `tool_choice=None` (not an empty list, which some providers reject).

---

## API Endpoints

### `POST /chat`

**Request:**
```json
{
  "message": "turn off the lights",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "client_id": "pi-kitchen",
  "bot_id": "default"
}
```
- `message`: required
- `session_id`: optional UUID. If omitted, server generates one.
- `client_id`: optional, defaults to `"default"`.
- `bot_id`: optional, defaults to `"default"`.

**Response:**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "response": "Done, lights are off."
}
```

**Auth:** Bearer token via `Authorization` header, validated against `API_KEY` env var. Returns 401 if missing/invalid.

**Flow:**
1. Validate auth.
2. `load_or_create` session.
3. Snapshot `len(messages)` as `from_index`.
4. `run(messages, bot, req.message)` — agent loop.
5. `persist_turn(db, session_id, messages, from_index)`.
6. Return response.

### `GET /sessions`

Query params: `client_id` (optional filter).
Returns list of sessions with id, client_id, bot_id, created_at, last_active.

### `GET /sessions/{session_id}`

Returns session metadata + full message history.

### `DELETE /sessions/{session_id}`

Deletes the session and all its messages (CASCADE). Returns 204.

### `GET /health`

No auth. Returns `{"status": "ok"}`. Used by Docker healthcheck and clients.

All endpoints except `/health` require auth.

---

## RAG (Stubbed)

`app/agent/rag.py` contains a single function:

```python
async def retrieve_context(query: str) -> list[str]:
    return []
```

The agent loop checks `bot.rag` and calls this function. The injection block stays in place as a forward-looking placeholder. No embedding generation, document ingestion, similarity search, or pgvector application code until explicitly requested. The `documents` table exists in the schema for future use.

---

## Streaming (Future-proofing)

The initial implementation returns complete responses. However, the router should be structured so that adding SSE streaming later is straightforward:
- The agent loop returns the final text string for now.
- A future `POST /chat/stream` endpoint (or `stream=true` parameter) can wrap the loop to yield tokens via `StreamingResponse`.
- No need to build this now, but avoid design choices that would make it hard (e.g., don't deeply couple response formatting into the loop).

---

## Docker Setup

### docker-compose.yml

Two services:
- `agent-server`: built from Dockerfile, port 8000, depends on postgres healthy.
- `postgres`: `pgvector/pgvector:pg16`, persistent volume, healthcheck via `pg_isready`.

Bot configs mounted as a volume (`./bots:/app/bots`) for easy editing without rebuilds.

LiteLLM is assumed to be running separately (already managed outside this compose file). The agent server connects to it via `LITELLM_BASE_URL`.

### Dockerfile

Python 3.12 slim base. Install dependencies from pyproject.toml. Copy app code. Run with uvicorn.

### Startup sequence

1. Postgres comes up, healthcheck passes.
2. Agent server starts.
3. Alembic migrations run automatically on startup (in `main.py` lifespan).
4. Bot configs loaded from `bots/` directory.
5. Local tool modules imported (triggers `@register` decorators).
6. Uvicorn serves on 0.0.0.0:8000.

---

## Error Handling

| Scenario                        | Behavior                                                   |
|---------------------------------|------------------------------------------------------------|
| Unknown bot_id                  | 404 with message                                           |
| Auth failure                    | 401                                                        |
| Tool function raises exception  | Caught, returned as `{"error": "..."}` tool result to model|
| LiteLLM unreachable             | 502 Bad Gateway with detail                                |
| MCP tool call fails             | Error returned as tool result, model can retry/explain     |
| Agent loop exceeds max iters    | Final forced response without tools                        |
| Invalid session_id format       | 422 (FastAPI validation)                                   |

---

## Build Order

| Phase | What                                      | Testable milestone                                     |
|-------|-------------------------------------------|--------------------------------------------------------|
| 1     | Scaffolding: pyproject.toml, Dockerfile, docker-compose, .gitignore, .env.example, config.py | `docker compose up` starts both containers             |
| 2     | DB: engine, ORM models, Alembic setup + initial migration | Tables exist in postgres                               |
| 3     | Bot config loader                         | Loads `bots/default.yaml` at startup                   |
| 4     | Session service (load/create/persist)     | Unit-testable with a DB session                        |
| 5     | Agent loop (no tools yet)                 | Can send a message and get a response from LiteLLM     |
| 6     | `/chat` endpoint + auth + `/health`       | `curl -X POST /chat` returns a response                |
| 7     | **CLI test client (Phase 1)**             | Interactive REPL can chat with the server              |
| 8     | `/sessions` CRUD endpoints                | Client `/sessions` and `/history` commands work        |
| 9     | Local tool registry + example tools       | Tools show up in completions calls                     |
| 10    | MCP tool integration                      | MCP tools fetched and dispatchable                     |
| 11    | RAG stub wired in                         | `retrieve_context()` called but returns empty          |

Phases 1-6 get the server running. Phase 7 (test client) is the primary development tool from that point forward — everything after it is developed and tested interactively through the client. Phases 8-11 add features iteratively.

---

## Test Client / Desktop Client

A separate Python application that lives in a `client/` directory within this repo. Serves as both the development test harness and the eventual desktop voice assistant. Built incrementally — starts as a CLI, evolves toward a persistent background process.

**This is the primary development tool.** The server is only useful if you can talk to it. Build Phase 1 of the client immediately after the server's `/chat` endpoint works.

Structure is shown in the project tree above under `client/`.

### Config File

`~/.config/agent-client/config.env`

```
AGENT_URL=http://your-server:8000
API_KEY=your-bearer-key
BOT_ID=default
HOTKEY=f9
WHISPER_MODEL=base.en
TTS_ENABLED=false
```

Loaded via a simple parser or pydantic-settings. The client should work with just `AGENT_URL` and `API_KEY` set — everything else has sensible defaults.

### Session State

`~/.config/agent-client/state.json`

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

- On first run: generate a UUID, write to state file, use it.
- On subsequent runs: load from state file and reuse. Conversations survive client restarts.
- `/new` command: generate a fresh UUID, overwrite state file.
- `/session <uuid>` command: switch to a specific session, overwrite state file.
- The client **never** waits for the server to provide a session ID.

### Phase 1 — CLI Test Harness

Interactive REPL loop. This is what we build first.

**Features:**
- Connects to server via `AGENT_URL` with bearer auth.
- Reads input, sends to `POST /chat`, prints response.
- Uses `BOT_ID` from config (overridable via CLI arg).
- Session ID loaded from state file or generated on first run.

**Commands:**
| Command              | Action                                           |
|----------------------|--------------------------------------------------|
| `/new`               | Generate fresh session UUID, overwrite state      |
| `/session <uuid>`    | Switch to a specific session, overwrite state     |
| `/sessions`          | List sessions from server (`GET /sessions`)       |
| `/history`           | Show current session history (`GET /sessions/{id}`)|
| `/bot <bot_id>`      | Switch bot for subsequent messages                |
| `/quit` or Ctrl+C    | Exit                                             |

Anything not starting with `/` is sent as a chat message.

**Implementation notes:**
- Use `httpx` for HTTP calls (same as server, consistent dependency).
- Print responses cleanly — if the response is long, don't mangle formatting.
- Handle connection errors gracefully (server down, timeout, auth failure) with clear messages, don't crash.
- The REPL should show the current session ID (truncated) and bot ID in the prompt, e.g. `[default|a1b2c3] > `.

### Phase 2 — Voice Input (Future)

- Push-to-talk via configurable hotkey (e.g. F9).
- Hold key to record via `sounddevice`, release to stop.
- Audio transcribed locally via `faster-whisper`.
- Transcript sent to `/chat` as normal text.
- Optional TTS playback via `piper` or `edge-tts` — skip gracefully if not available.

**Critical: audio dependencies are optional imports.** The CLI must work on any machine without `sounddevice`, `faster-whisper`, etc. installed. If they're missing, voice features are disabled with a message, not a crash.

```python
try:
    import sounddevice as sd
    import faster_whisper
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False
```

### Phase 3 — Background Daemon (Future)

- Persistent background process on the desktop.
- Wake word detection via `openwakeword` replaces push-to-talk.
- Hyprland/keyd integration for hotkey binding.
- Desktop notifications via `notify-send` for responses.
- Optional clipboard context injection — on trigger, grab clipboard content and prepend to user message so "summarize this" works naturally.

### Client Dependencies

Core (Phase 1 only):
- `httpx`
- `pydantic-settings` (or just manual env parsing — keep it minimal)

Optional (Phase 2):
- `sounddevice`
- `faster-whisper`
- `piper-tts` or `edge-tts`

Optional (Phase 3):
- `openwakeword`

---

## Context Window Management (Future)

Not implemented now, but the schema and session service should not make this harder later. When needed:
- Add a `token_count` integer column to `messages` (estimated at insert time).
- Session service can sum token counts and truncate/summarize when approaching the model's limit.
- Summarization would condense older messages into a single system message, preserving recent turns verbatim.

---

## Dependencies (pyproject.toml)

Core:
- `fastapi`
- `uvicorn[standard]`
- `sqlalchemy[asyncio]`
- `asyncpg`
- `alembic`
- `pydantic-settings`
- `httpx`
- `openai`
- `pyyaml`

Dev:
- `pytest`
- `pytest-asyncio`
