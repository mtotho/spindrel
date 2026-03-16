I want to build an agent server which I will have hosted on my local network

My ultimate plan is to have small clients (one listening on my desktop, maybe a webui for chatting, maybe another voice assistant in the living room). So the server i need to hit must have some endpoints to hit for chatting/conversations, etc. Either accepting text, voice or both (or clients to text to speach most likely)

The server will contain a rag pipeline, calls configured model to configure open ai ocmpatible backend (litellm). Im gonna add a lot onto this over time so it needs to be a robust architecture

chat session management: not sure if I should have the clients manage the session (i dont want to make them do much work). Or if server should maintain conversations.history/ even store stuff postgress. Then give clients some ability to do new session or existing


AI SUggestions Below:
Stack
FastAPI — async, you know web apps, OpenAPI docs free, plays well with everything you're building on.
PostgreSQL — for sessions, message history, and pgvector for RAG embeddings. One database, two purposes.
Docker Compose — agent server + postgres as a unit, LiteLLM already running separately.

Session management — server owns it
Clients should be maximally thin. A voice Pi should not be storing conversation history. The server owns all state.
Client contract is simple:

No session_id sent → server creates one, returns it in response
session_id sent → server continues that conversation
Client can explicitly request a new session whenever

POST /chat
{
  "session_id": "abc123",   # optional
  "message": "turn off lights",
  "client_id": "pi-kitchen"
}

→ {
  "session_id": "abc123",   # always echoed back
  "response": "Done, lights off"
}
Voice endpoint is identical except it accepts audio and returns audio (or text, client's choice).
Sessions stored in postgres. Message history stored per session. This means:

Conversations survive server restarts
You can build a chat UI later that shows history
You can inspect/debug conversations
You can prune/summarize long sessions server-side without clients knowing

┌─────────────────────────────────────────────────────┐
│                   agent-server                       │
│                                                      │
│  ┌──────────┐  ┌──────────┐  ┌────────────────────┐ │
│  │ /chat    │  │ /voice   │  │ /sessions          │ │
│  │ endpoint │  │ endpoint │  │ (CRUD, history)    │ │
│  └────┬─────┘  └────┬─────┘  └────────────────────┘ │
│       │              │ STT                           │
│       └──────┬───────┘                               │
│              ▼                                        │
│     ┌─────────────────┐                              │
│     │  session manager│◄──── PostgreSQL               │
│     │  (load/save     │      (sessions +             │
│     │   history)      │       messages +             │
│     └────────┬────────┘       pgvector)              │
│              │                                        │
│              ▼                                        │
│     ┌─────────────────┐                              │
│     │   RAG pipeline  │◄──── pgvector similarity     │
│     │  (inject chunks │      search                  │
│     │   into context) │                              │
│     └────────┬────────┘                              │
│              │                                        │
│              ▼                                        │
│     ┌─────────────────┐                              │
│     │   agent loop    │                              │
│     │  (tool dispatch)│                              │
│     └────────┬────────┘                              │
└──────────────┼──────────────────────────────────────┘
               │
               ▼
          LiteLLM proxy
          (models + MCP servers)


          -- sessions
id          uuid primary key
client_id   text           -- which device/user
created_at  timestamptz
last_active timestamptz
metadata    jsonb          -- persona, context overrides etc

-- messages  
id          uuid primary key
session_id  uuid references sessions
role        text           -- user / assistant / tool
content     text
tool_calls  jsonb          -- stored if tool was called
created_at  timestamptz

-- documents (for RAG)
id          uuid primary key
content     text
embedding   vector(1536)   -- pgvector
source      text           -- filename, url, etc
metadata    jsonb




Agent Server — Architecture SpecOverviewA self-hosted FastAPI agent server that provides voice and chat interfaces to a configurable LLM backend (LiteLLM). Supports multiple named bots, persistent session management, always-on RAG, and a hybrid tool system combining upstream MCP tools (via LiteLLM) and locally-defined Python tools.Tech Stack
Runtime: Python 3.12+
Framework: FastAPI (async)
Database: PostgreSQL with pgvector extension
ORM: SQLAlchemy (async) + Alembic for migrations
LLM Backend: LiteLLM proxy (OpenAI-compatible)
STT: faster-whisper (local)
Containerization: Docker Compose

agent-server/
├── app/
│   ├── main.py                  # FastAPI app entry, route registration
│   ├── config.py                # Settings from env vars (pydantic-settings)
│   ├── dependencies.py          # FastAPI dependency injection (db, auth)
│   │
│   ├── routers/
│   │   ├── chat.py              # POST /chat
│   │   ├── voice.py             # POST /voice (audio in, text out)
│   │   └── sessions.py          # GET/DELETE /sessions endpoints
│   │
│   ├── agent/
│   │   ├── loop.py              # Core agent loop (tool call iteration)
│   │   ├── bots.py              # Bot registry and config loader
│   │   └── rag.py               # Embedding + retrieval injection
│   │
│   ├── tools/
│   │   ├── registry.py          # Central tool dispatcher
│   │   ├── mcp.py               # Fetch + proxy MCP tools from LiteLLM
│   │   └── local/               # Custom Python tool implementations
│   │       ├── __init__.py
│   │       └── example.py       # Example local tool
│   │
│   ├── services/
│   │   ├── sessions.py          # Session CRUD, message persistence
│   │   └── stt.py               # Whisper transcription
│   │
│   └── db/
│       ├── models.py            # SQLAlchemy ORM models
│       └── migrations/          # Alembic migration files
│
├── bots/                        # Bot definition files (YAML or Python)
│   ├── default.yaml
│   ├── home_assistant.yaml
│   └── desktop.yaml
│
├── docker-compose.yml
├── Dockerfile
├── alembic.ini
├── pyproject.toml
└── .env


env# Auth
API_KEY=your-secret-bearer-key

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/agentdb

# LiteLLM
LITELLM_BASE_URL=http://litellm:4000/v1
LITELLM_API_KEY=your-litellm-key
LITELLM_MCP_URL=http://litellm:4000/mcp

# STT
WHISPER_MODEL=base.en

# RAG
EMBEDDING_MODEL=text-embedding-3-small   # or a local model alias in LiteLLM
EMBEDDING_DIM=1536
RAG_TOP_K=5
RAG_SIMILARITY_THRESHOLD=0.75



-- Sessions
CREATE TABLE sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id   TEXT NOT NULL,
    bot_id      TEXT NOT NULL DEFAULT 'default',
    created_at  TIMESTAMPTZ DEFAULT now(),
    last_active TIMESTAMPTZ DEFAULT now(),
    metadata    JSONB DEFAULT '{}'
);

-- Messages (full conversation history per session)
CREATE TABLE messages (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,        -- user | assistant | tool | system
    content     TEXT,
    tool_calls  JSONB,                -- raw tool_calls from model if present
    tool_call_id TEXT,               -- for role=tool messages
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- RAG document chunks
CREATE TABLE documents (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content     TEXT NOT NULL,
    embedding   VECTOR(1536),
    source      TEXT,                -- filename, url, label
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX ON documents USING ivfflat (embedding vector_cosine_ops);


# bots/home_assistant.yaml
id: home_assistant
name: "Home Assistant Bot"
description: "Controls home automation and queries entity states"
model: gemini-flash          # LiteLLM model alias
system_prompt: |
  You are a home automation agent with access to a live Home Assistant
  instance. Always verify entity state after acting. Be concise.
  For destructive actions (locks, alarms), confirm before executing.

# MCP servers from LiteLLM this bot can use
# These are server aliases as configured in your LiteLLM proxy
mcp_servers:
  - home_assistant            # LiteLLM will namespace tools as home_assistant_*

# Local Python tools available to this bot
local_tools:
  - get_current_time
  - send_notification

# RAG enabled for this bot
rag: true


# bots/desktop.yaml
id: desktop
name: "Desktop Assistant"
model: gpt-4.1-mini
system_prompt: |
  You are a desktop assistant on an Arch Linux machine running Hyprland.
  You have access to clipboard content and active window context
  injected into each message.
mcp_servers: []
local_tools:
  - get_current_time
  - run_shell_command        # example local tool
rag: false


Tool System — Design and Implementation
This is the most important architectural piece. There are two categories of tools and they are handled differently.
Category 1: MCP Tools (upstream via LiteLLM)
MCP tools are registered in your LiteLLM config.yaml (e.g. Home Assistant MCP server). LiteLLM acts as a gateway — it fetches tool schemas from the MCP server and exposes them.
How it works:

At startup (or cached with TTL), fetch available tool schemas from LiteLLM's MCP endpoint
Filter to only the servers configured for the current bot
Pass schemas into the chat completions call as tools=
When the model returns a tool_calls with an MCP tool name, forward the call to LiteLLM's MCP execution endpoint
LiteLLM executes against the actual MCP server (HA, etc.) and returns the result


# app/tools/mcp.py
import httpx
from app.config import settings
from functools import lru_cache
import time

_tool_cache: dict = {}
_cache_ttl = 60  # seconds

async def fetch_mcp_tools(allowed_servers: list[str]) -> list[dict]:
    """
    Fetch tool schemas from LiteLLM MCP gateway.
    LiteLLM namespaces tools as: {server_alias}_{tool_name}
    Filter to only servers this bot is allowed to use.
    """
    cache_key = ",".join(sorted(allowed_servers))
    cached = _tool_cache.get(cache_key)
    if cached and time.time() - cached["ts"] < _cache_ttl:
        return cached["tools"]

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{settings.LITELLM_MCP_URL}/tools/list",
            headers={"Authorization": f"Bearer {settings.LITELLM_API_KEY}"}
        )
        resp.raise_for_status()
        all_tools = resp.json().get("tools", [])

    # Filter by allowed server prefixes for this bot
    filtered = [
        {"type": "function", "function": t}
        for t in all_tools
        if any(t["name"].startswith(s + "_") for s in allowed_servers)
    ]

    _tool_cache[cache_key] = {"tools": filtered, "ts": time.time()}
    return filtered


async def call_mcp_tool(tool_name: str, arguments: dict) -> str:
    """Forward tool execution to LiteLLM MCP gateway."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{settings.LITELLM_MCP_URL}/tools/call",
            headers={"Authorization": f"Bearer {settings.LITELLM_API_KEY}"},
            json={"name": tool_name, "arguments": arguments}
        )
        resp.raise_for_status()
        return resp.text  # return raw JSON string, agent appends as tool result



Category 2: Local Python Tools
These are functions you define directly in the server. Anything that can't or shouldn't be an MCP server — desktop integration, internal APIs, computed values, etc.
How it works:

Each local tool is a Python async function with a corresponding OpenAI function schema
The registry maps tool names to their schema + callable
When the model returns a tool_call for a local tool, the registry dispatches directly to the function


# app/tools/registry.py
import json
from dataclasses import dataclass
from typing import Callable, Awaitable
from app.tools.mcp import call_mcp_tool

@dataclass
class LocalTool:
    name: str
    schema: dict          # OpenAI function schema
    fn: Callable[..., Awaitable[str]]


# Registry of all local tools
_local_tools: dict[str, LocalTool] = {}

def register(schema: dict):
    """Decorator to register a local tool."""
    def decorator(fn):
        _local_tools[schema["name"]] = LocalTool(
            name=schema["name"],
            schema={"type": "function", "function": schema},
            fn=fn
        )
        return fn
    return decorator

def get_local_tool_schemas(allowed_names: list[str]) -> list[dict]:
    return [
        _local_tools[n].schema
        for n in allowed_names
        if n in _local_tools
    ]

async def dispatch(tool_name: str, arguments: dict, mcp_servers: list[str]) -> str:
    """
    Route tool call to either a local function or LiteLLM MCP gateway.
    Local tools take priority if name matches.
    MCP tools are identified by server prefix.
    """
    if tool_name in _local_tools:
        result = await _local_tools[tool_name].fn(**arguments)
        return json.dumps(result) if not isinstance(result, str) else result

    if any(tool_name.startswith(s + "_") for s in mcp_servers):
        return await call_mcp_tool(tool_name, arguments)

    return json.dumps({"error": f"Unknown tool: {tool_name}"})


    # app/tools/local/example.py
from app.tools.registry import register
from datetime import datetime

@register({
    "name": "get_current_time",
    "description": "Returns the current local time",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": []
    }
})
async def get_current_time() -> str:
    return datetime.now().strftime("%I:%M %p")


@register({
    "name": "send_notification",
    "description": "Sends a desktop notification on the host machine",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "message": {"type": "string"}
        },
        "required": ["title", "message"]
    }
})
async def send_notification(title: str, message: str) -> str:
    import subprocess
    subprocess.run(["notify-send", title, message])
    return "Notification sent"


    # app/agent/loop.py
import json
from openai import AsyncOpenAI
from app.config import settings
from app.agent.bots import BotConfig
from app.agent.rag import retrieve_context
from app.tools.registry import get_local_tool_schemas, dispatch
from app.tools.mcp import fetch_mcp_tools

client = AsyncOpenAI(
    base_url=settings.LITELLM_BASE_URL,
    api_key=settings.LITELLM_API_KEY
)

async def run(messages: list[dict], bot: BotConfig, user_message: str) -> str:
    # Always-on RAG: retrieve relevant chunks and inject before user message
    if bot.rag:
        chunks = await retrieve_context(user_message)
        if chunks:
            rag_content = "\n\n".join(chunks)
            # Inject as a system message immediately before the user turn
            messages.append({
                "role": "system",
                "content": f"Relevant context:\n{rag_content}"
            })

    messages.append({"role": "user", "content": user_message})

    # Assemble tool list for this bot
    mcp_tools = await fetch_mcp_tools(bot.mcp_servers)
    local_tools = get_local_tool_schemas(bot.local_tools)
    all_tools = mcp_tools + local_tools

    # Agentic loop
    while True:
        response = await client.chat.completions.create(
            model=bot.model,
            messages=messages,
            tools=all_tools if all_tools else None,
            tool_choice="auto" if all_tools else None
        )

        msg = response.choices[0].message
        messages.append(msg)

        if not msg.tool_calls:
            return msg.content

        for tc in msg.tool_calls:
            result = await dispatch(
                tc.function.name,
                json.loads(tc.function.arguments),
                bot.mcp_servers
            )
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result
            })



            # app/services/sessions.py
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Session, Message
from app.agent.bots import get_bot

async def load_or_create(
    db: AsyncSession,
    session_id: UUID | None,
    client_id: str,
    bot_id: str
) -> tuple[UUID, list[dict]]:
    """
    Returns (session_id, messages_array_for_agent).
    messages includes system prompt as first entry.
    """
    bot = get_bot(bot_id)

    if session_id:
        session = await db.get(Session, session_id)
        if session:
            # Load history from DB
            rows = await db.execute(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.created_at)
            )
            messages = [_row_to_dict(r) for r in rows.scalars()]
            return session_id, messages

    # Create new session
    session = Session(client_id=client_id, bot_id=bot_id)
    db.add(session)
    await db.flush()

    system_msg = {"role": "system", "content": bot.system_prompt}
    return session.id, [system_msg]


async def persist_turn(
    db: AsyncSession,
    session_id: UUID,
    messages: list[dict],
    from_index: int
):
    """Persist only the new messages added this turn."""
    new_messages = messages[from_index:]
    for msg in new_messages:
        db.add(Message(
            session_id=session_id,
            role=msg.get("role"),
            content=msg.get("content") if isinstance(msg.get("content"), str) else None,
            tool_calls=msg.get("tool_calls"),
            tool_call_id=msg.get("tool_call_id")
        ))
    await db.commit()


# app/routers/chat.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from uuid import UUID
from app.dependencies import get_db, verify_api_key
from app.services.sessions import load_or_create, persist_turn
from app.agent.loop import run
from app.agent.bots import get_bot

router = APIRouter(prefix="/chat", dependencies=[Depends(verify_api_key)])

class ChatRequest(BaseModel):
    message: str
    session_id: UUID | None = None
    client_id: str = "default"
    bot_id: str = "default"

class ChatResponse(BaseModel):
    session_id: UUID
    response: str

@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest, db=Depends(get_db)):
    bot = get_bot(req.bot_id)
    session_id, messages = await load_or_create(
        db, req.session_id, req.client_id, req.bot_id
    )

    snapshot_index = len(messages)  # track where new messages begin
    response = await run(messages, bot, req.message)

    await persist_turn(db, session_id, messages, snapshot_index)

    return ChatResponse(session_id=session_id, response=response)



# docker-compose.yml
services:
  agent-server:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - ./bots:/app/bots       # hot-reload bot configs

  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass
      POSTGRES_DB: agentdb
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U user -d agentdb"]
      interval: 5s
      retries: 5

volumes:
  pgdata:


Key Implementation Notes for Cursor

Import all local tool modules at startup in main.py so the @register decorators run and populate the registry. Add new tools by creating files under app/tools/local/ and importing them.
MCP tool schemas are cached with a short TTL. Don't fetch on every request.
RAG injection uses a system message inserted just before the user turn each time, not prepended to history. This keeps the context window clean for long sessions.
persist_turn uses snapshot_index to avoid double-writing existing history. Only messages appended during the current agent loop are saved.
Bot configs are loaded from YAML at startup into a dict keyed by id. Hot-reload is possible but not required initially.
Voice endpoint (/voice) accepts multipart/form-data with an audio file field, runs it through faster-whisper, then calls the same run() function as the chat endpoint. Returns text; TTS is client-side.
Session endpoint (/sessions/{id}) supports GET (return history) and DELETE (clear history, keep session) for client UX needs like "start over".



The user wants RAG support eventually but it is not the current priority. app/agent/rag.py should exist with retrieve_context() returning an empty list. The injection block in the agent loop and the rag field in bot configs should stay as-is — they are forward-looking placeholders. Do not implement embedding generation, document ingestion, similarity search, or any pgvector-specific logic yet. The documents table and pgvector extension can stay in the schema for now but do not write any application code that touches them. When the user is ready to implement RAG properly, the decisions around embedding model, chunk strategy, and ingestion pipeline will be made explicitly — do not make those calls implicitly.



Good call on client-defined session IDs — yes, just generate a UUID client-side and send it. The server treats a new unseen session_id as a create. Simpler handshake, no round-trip needed just to get an ID.
Here's the cursor note:

Linux Test Client / Desktop Client
A separate Python application (not part of the agent-server repo, but can live in a sibling folder or separate repo) that serves as both the development test harness and the eventual desktop voice client. It should be built incrementally — start as a simple CLI, evolve toward a persistent background process.
Phase 1 — CLI test harness
Simple interactive loop. Configurable server URL and API key via a local .env or config file. Sends text messages to /chat, prints responses. Supports specifying a bot_id. Session ID is generated client-side as a UUID on startup (or loaded from a local state file so it persists between runs). Commands like /new to generate a fresh session ID, /session <uuid> to resume a specific one, /sessions to list from server if that endpoint exists. This is enough to develop and debug the agent server without any audio involved.
Phase 2 — Voice input
Add push-to-talk via a configurable hotkey (F9 or similar, configured in .env). Hold key to record via sounddevice, release to stop. Audio runs through local faster-whisper for transcription, transcript is sent to /chat same as text. Response text is printed. TTS playback is optional at this stage — pipe through piper or edge-tts if available, skip gracefully if not.
Phase 3 — Background daemon
Evolves into a persistent process running in the background on the desktop. Wake word detection via openwakeword replaces push-to-talk. Hyprland/keyd integration for hotkey binding. Desktop notifications via notify-send for responses. Optional clipboard context injection — on trigger, grab clipboard content and prepend to the user message so the user can say "summarize this" naturally.
Session management UX
Session ID is always a client-generated UUID. On first run, generate one and persist it to a local state file (e.g. ~/.config/agent-client/state.json). On subsequent runs, load and reuse it — this means conversations survive restarts naturally. /new command or hotkey generates a fresh UUID and overwrites state. The client never waits for the server to hand it a session ID.
Config file (~/.config/agent-client/config.env or similar)

GENT_URL=http://your-server:8000
API_KEY=your-bearer-key
BOT_ID=desktop
HOTKEY=f9
WHISPER_MODEL=base.en
TTS_ENABLED=true

Key implementation note for Cursor — build Phase 1 first and make sure the agent server is fully testable via text before adding any audio code. Audio dependencies (sounddevice, faster-whisper, openwakeword) should be optional imports that fail gracefully so the CLI works on any machine regardless of audio hardware.