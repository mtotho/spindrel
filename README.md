# Agent Server

Self-hosted FastAPI agent server. Text-in, text-out chat with configurable LLM backend via LiteLLM, persistent sessions, a tool system (local Python + MCP), web search, and a voice-enabled CLI client with wake word detection.

## Quick Start

```bash
cp .env.example .env         # edit this first — see "Configuration" below
./scripts/dev-server.sh      # starts postgres + searxng + playwright + server (terminal 1)
./scripts/dev-client.sh      # starts the CLI chat client (terminal 2)
```

The dev-server script starts three Docker containers (postgres, searxng, playwright) and then runs the FastAPI server locally with `--reload`.

## Configuration

### Server (.env)

Copy `.env.example` to `.env` and edit:

```
API_KEY=dev
DATABASE_URL=postgresql+asyncpg://agent:agent@localhost:5432/agentdb
LITELLM_BASE_URL=http://localhost:4000/v1
LITELLM_API_KEY=your-litellm-key

# Web tools
SEARXNG_URL=http://searxng:8080
PLAYWRIGHT_WS_URL=ws://playwright:3000
```

`API_KEY` is the bearer token that clients use to authenticate. For local dev, any value works — just make sure the client uses the same one.

`LITELLM_BASE_URL` points to your LiteLLM proxy. The server calls it with the OpenAI SDK, so this should be the `/v1` endpoint. LiteLLM needs to be running separately — it is not managed by this project's docker-compose.

`SEARXNG_URL` and `PLAYWRIGHT_WS_URL` point to the web tool services. Both are included in docker-compose and start automatically with `dev-server.sh`.

### Bots (bots/*.yaml)

A bot is a named configuration that tells the server which model to use, what system prompt to send, and which tools are available. Bot YAML files live in `bots/` and are loaded once at server startup.

```yaml
# bots/default.yaml
id: default
name: "Default Assistant"
model: gemini/gemini-2.5-flash
system_prompt: |
  You are a helpful assistant.
mcp_servers: []
local_tools: []
rag: false
```

**`model`** is a LiteLLM model alias. It gets passed straight through to the LiteLLM `/v1/chat/completions` endpoint. Whatever models you've configured in LiteLLM, use those names here.

**To create a new bot**, add a YAML file to `bots/`:

```yaml
# bots/code.yaml
id: code
name: "Code Assistant"
model: claude-sonnet-4-20250514
system_prompt: |
  You are a senior software engineer. Be concise and direct.
mcp_servers: []
local_tools:
  - get_current_time
  - web_search
  - fetch_url
  - client_action
rag: false
context_compaction: true
# compaction_interval: 10   # optional per-bot override
# compaction_model: gpt-4o-mini  # optional cheaper model for summaries
```

Then restart the server. Uvicorn `--reload` watches `.py` and `.yaml` files, but bot configs are loaded at startup so a full restart is needed.

**`skills`** lists skill IDs (filenames without `.md`) from the `skills/` directory. When a bot has skills, the server automatically retrieves relevant skill content for each user message via vector similarity search and injects it into the LLM's context. See "Skills" below.

### Skills (skills/*.md)

Skills are curated knowledge files that give bots domain expertise. Drop a `.md` file in `skills/` and list it in a bot's config — the bot will automatically pull in relevant sections when the user asks about that topic.

**How it works:**

1. On server startup, each `.md` file is chunked by `## ` sections and embedded via your LiteLLM embedding model
2. Embeddings are stored in the `documents` table (pgvector with HNSW index)
3. Unchanged files are skipped on restart (tracked by content hash)
4. At query time, the user's message is embedded and matched against skill chunks via cosine similarity
5. Matching chunks are injected into the LLM context as a system message

**Creating a skill:**

```markdown
---
name: Home Assistant
description: Home Assistant automation and configuration
---

# Home Assistant

## Automations

Automations have three parts: trigger, condition, action...

## Integrations

Integrations connect HA to devices and services...
```

The `---` frontmatter block is optional. `name` controls the display name in context (defaults to the filename in title case). The content is split at `## ` headings — each section becomes an independently searchable chunk.

**Adding skills to a bot:**

```yaml
# bots/my_bot.yaml
skills:
  - home_assistant
  - arch_linux
```

Skill IDs are filenames without the `.md` extension. Only the listed skills are searched for that bot.

**Embedding config** (in `.env`):

```
EMBEDDING_MODEL=text-embedding-3-small   # model name via LiteLLM
EMBEDDING_DIM=1536                       # must match the model's output dimension
RAG_TOP_K=5                              # max chunks to retrieve per query
RAG_SIMILARITY_THRESHOLD=0.3             # minimum cosine similarity (0-1)
```

The embedding model is called through your LiteLLM proxy, so any model LiteLLM supports works here.

### Available local tools

| Tool | Description |
|---|---|
| `get_current_time` | Returns current UTC time |
| `web_search` | Search the web via SearXNG. Returns top N results as JSON |
| `fetch_url` | Fetch and read a webpage via Playwright (falls back to httpx) |
| `client_action` | Perform actions on the client device (new session, switch bot, toggle TTS, etc.) |

**`context_compaction`** (default `true`) enables automatic context summarization. When enabled, the server periodically uses an LLM to generate a title and detailed summary for the session, then loads the summary instead of the full message history. This keeps context windows manageable for long conversations.

**`compaction_interval`** overrides the global `COMPACTION_INTERVAL` for this bot. This is the number of user turns (not messages) between compaction runs. Default is 10.

**`compaction_model`** overrides the model used for summarization. By default it uses the global `COMPACTION_MODEL`, falling back to the bot's own model.

**`mcp_servers`** lists MCP server names as configured in your LiteLLM proxy. Tools from each server are namespaced with a prefix (e.g. a server named `HAOS` exposes tools like `HAOS_call_service`, `HAOS_get_states`). The agent server fetches available tools from LiteLLM's MCP endpoint on each turn, filters to the bot's allowed servers, and proxies tool calls back through LiteLLM.

```yaml
mcp_servers:
  - HAOS
  - filesystem
```

Requires `LITELLM_MCP_URL` in `.env` (defaults to `http://litellm:4000/mcp`). Tool schemas are cached for 60 seconds.

## Using the CLI Client

```bash
./scripts/dev-client.sh
# with a specific bot:
./scripts/dev-client.sh --bot code
# with TTS:
./scripts/dev-client.sh --tts
# with full voice (TTS + STT + wake word):
./scripts/dev-client.sh --tts --voice
# start directly in wake word listen mode:
./scripts/dev-client.sh --tts --listen
```

You'll see a prompt like:

```
Agent Chat — session a1b2c3 | bot default | tts off
Type /help for commands.

[default|a1b2c3] >
```

### Commands

| Command | What it does |
|---|---|
| `/help` | Show all commands |
| `/new` | Start a fresh conversation (new session) |
| `/session` | Show current session UUID |
| `/session <uuid>` | Switch to a specific session |
| `/sessions` | List all sessions on the server |
| `/history` | Print the current session's message history |
| `/v` | Voice input — record, transcribe, send |
| `/vc` | Voice conversation — continuous back-and-forth |
| `/listen` | Wake word mode — say the wake word to trigger recording |
| `/bot <id>` | Switch to a different bot |
| `/bots` | List available bots |
| `/tts` | Toggle text-to-speech on/off |
| `/quit` | Exit (Ctrl+C also works) |

### Streaming tool status

The client uses Server-Sent Events (`POST /chat/stream`) to get real-time feedback during the agent loop. When the bot uses tools, you see status immediately:

```
[brief_bot|a1b2c3] > what's in the news today?
  [Searching the web...]
  [Reading webpage...]

Here's what's happening today: ...
```

This works in all modes — typed input, voice, and wake word listen mode.

### Wake word mode

Type `/listen` or start with `--listen` to enter wake word mode. The client listens for a wake word (e.g. "hey jarvis"), plays a confirmation tone, records your speech, transcribes it, and sends it to the bot. After the response, it goes back to listening.

Configure wake words in `~/.config/agent-client/config.env` or the server `.env`:

```
WAKE_WORDS=hey_jarvis,hey_computer
```

Available wake words depend on what [openwakeword](https://github.com/dscripka/openWakeWord) supports. The client prints available options on first use.

### Voice commands (client actions)

When a bot has `client_action` in its `local_tools`, you can perform client operations by voice. The bot interprets your intent and calls the tool, which the client executes:

- "Start a new session" — creates a fresh session
- "Switch to the code bot" — switches bot
- "Turn on text to speech" — toggles TTS
- "Show me my sessions" — lists sessions
- "What have we been talking about?" — prints history + bot summarizes

These work because `client_action` is a server-side tool that returns structured data. The client receives the actions alongside the response and executes them locally.

### Voice input (STT)

Type `/v` to record a single voice input, or `/vc` for continuous voice conversation. Recording auto-stops on silence. Audio is transcribed locally via [faster-whisper](https://github.com/SYSTRAN/faster-whisper).

The whisper model (~150MB for `base.en`) downloads on first use.

**Requires:** `--voice` flag (or `--listen`, which implies `--voice`).

### Text-to-Speech (TTS)

When TTS is enabled, responses are printed and spoken aloud using [Piper](https://github.com/rhasspy/piper), a fully local neural TTS engine.

**Enable TTS** by any of:
- CLI flag: `--tts`
- Config file: `TTS_ENABLED=true` in `~/.config/agent-client/config.env`
- In-session: `/tts`

`aplay` is required (part of `alsa-utils`).

### Voice config

All optional, in `~/.config/agent-client/config.env`:

```
TTS_ENABLED=true
PIPER_MODEL=en_US-lessac-medium
PIPER_MODEL_DIR=~/.local/share/piper
WHISPER_MODEL=base.en
WAKE_WORDS=hey_jarvis,hey_computer
```

### How the client finds its settings

The client checks these in order (later overrides earlier):

1. `~/.config/agent-client/config.env` (optional persistent config)
2. Environment variables (`AGENT_URL`, `API_KEY`, `BOT_ID`, `TTS_ENABLED`, etc.)
3. CLI flags (`--url`, `--key`, `--bot`, `--tts`/`--no-tts`, `--listen`)

For local dev the scripts handle all of this — they pull `API_KEY` from your `.env` automatically.

### Sessions

The client generates a session UUID on first run and saves it to `~/.config/agent-client/state.json`. Conversations persist across client restarts. Use `/new` to start a fresh conversation.

### Context Compaction

Long conversations are automatically summarized to keep context windows manageable. After a configurable number of user turns (default 10), the server asks an LLM to produce:

- A **title** for the session (shown in `/sessions` listings instead of bare UUIDs)
- A **detailed summary** capturing key facts, decisions, code references, and ongoing tasks

On the next message, instead of replaying the entire history, the session loads: system prompt + summary + the last few turns verbatim (default 2, configurable via `COMPACTION_KEEP_TURNS`). This means the LLM always has exact recall of the most recent exchanges while older context comes from the summary. Old messages are preserved in the database and still visible via `/history`.

This runs as a background task — it doesn't slow down your chat response. Configure it globally in `.env`:

```
COMPACTION_MODEL=gemini/gemini-2.5-flash   # cheap/fast model for summaries
COMPACTION_INTERVAL=10                      # user turns between compactions
COMPACTION_KEEP_TURNS=2                     # recent turns kept verbatim alongside summary
```

Or per-bot in YAML:

```yaml
context_compaction: true       # default true; set false to disable
compaction_interval: 5         # override for this bot
compaction_model: gpt-4o-mini  # override model for this bot
```

## API

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check (no auth) |
| `/chat` | POST | Send a message, get a response |
| `/chat/stream` | POST | Same as `/chat` but streams SSE events with tool status |
| `/sessions` | GET | List sessions with titles (optional `?client_id=` filter) |
| `/sessions/{id}` | GET | Get session with full message history |
| `/sessions/{id}` | DELETE | Delete a session |
| `/bots` | GET | List available bots |

All endpoints except `/health` require `Authorization: Bearer <API_KEY>`.

### POST /chat

```json
{"message": "hello", "session_id": "uuid", "client_id": "cli", "bot_id": "default"}
```

Returns:

```json
{"session_id": "uuid", "response": "Hi!", "client_actions": []}
```

### POST /chat/stream

Same request body. Returns `text/event-stream` with events:

```
data: {"type": "tool_start", "tool": "web_search", "session_id": "uuid"}

data: {"type": "tool_result", "tool": "web_search", "session_id": "uuid"}

data: {"type": "response", "text": "Here's what I found...", "client_actions": [], "session_id": "uuid"}
```

## Local Development Setup (manual)

If you don't want to use the scripts:

### 1. Docker services

```bash
docker compose up postgres searxng playwright -d
```

Useful commands:

```bash
docker compose logs postgres       # check logs
docker compose down                # stop all
docker compose down -v             # stop + wipe data
```

### 2. Python

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 3. Server

```bash
uvicorn app.main:app --reload
```

Migrations run automatically on first start. Health check: `curl localhost:8000/health`

### 4. Client

In a separate terminal:

```bash
source .venv/bin/activate
pip install -e client/
agent-chat --key dev --url http://localhost:8000
```

## Docker (full stack)

For deploying everything containerized:

```bash
docker compose up --build
```

This starts four services: `agent-server`, `postgres`, `searxng`, and `playwright`.

When running in Docker, the `.env` should use Docker service names (`postgres`, `searxng`, `playwright`) not `localhost`.

## Project Layout

```
app/              Server application
  agent/          Agent loop, bot config, skills, RAG retrieval
  db/             SQLAlchemy models + engine
  routers/        FastAPI endpoints (/chat, /chat/stream, /sessions, /health)
  services/       Session persistence
  tools/          Tool registry, MCP proxy, local tools
    local/        Python tool implementations (web_search, client_action, etc.)
bots/             Bot YAML configs
skills/           Skill knowledge files (*.md)
client/           CLI client (separate installable package)
  agent_client/   Client source (cli, http client, audio, config, state)
migrations/       Alembic migrations
scripts/          Dev helper scripts
```
