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
memory:
  enabled: true              # log compaction summaries to memory KB + retrieve on each turn
  cross_session: false       # widen retrieval to other sessions for this client
voice:
  piper_model: en_US-amy-medium    # Python client TTS voice
  android_voice: en-US-default     # Android client TTS voice (expo-speech)
  speed: 1.0                      # speech rate multiplier (both clients)
  listen_sound: chime              # wake word confirmation sound preset
```

Then restart the server. Uvicorn `--reload` watches `.py` and `.yaml` files, but bot configs are loaded at startup so a full restart is needed.

**`voice`** provides per-bot overrides for voice/sound settings. All fields are optional — missing fields fall back to the client's global defaults. See "Voice config" below for details.

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

**`mcp_servers`** lists MCP server names defined in `mcp.yaml`. The agent server fetches available tools from each server's MCP endpoint, makes them available to the LLM, and proxies tool calls back.

```yaml
mcp_servers:
  - homeassistant
  - github
```

### MCP Servers (mcp.yaml)

MCP server connections are defined in `mcp.yaml` at the project root. Each entry maps a name (referenced by bots) to a URL and optional API key:

```yaml
homeassistant:
  url: http://litellm:4000/homeassistant/mcp
  api_key: ${LITELLM_API_KEY}

github:
  url: http://some-other-mcp-server:8080/mcp
  api_key: ${GITHUB_MCP_KEY}
```

Values support `${ENV_VAR}` substitution so you can keep secrets in `.env`. The URL should be the full MCP endpoint — this works with any MCP-compatible server, not just LiteLLM. Tool schemas are cached for 60 seconds.

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
| `/compact` | Force compaction + memory storage now |
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

Type `/v` to record a single voice input, or `/vc` for continuous voice conversation. Recording auto-stops on silence.

**Server-side transcription** is the default. The client sends recorded audio to the server's `POST /transcribe` endpoint, which runs [faster-whisper](https://github.com/SYSTRAN/faster-whisper). This keeps transcription fast (especially with GPU acceleration on the server) and removes ML dependencies from the client. If the server is unreachable, the client falls back to local transcription automatically.

The whisper model (~150MB for `base.en`) downloads on first use (on whichever side runs it).

**Server STT config** (in `.env`):

```
STT_PROVIDER=local                  # "local" (faster-whisper); future: "groq", "openai"
WHISPER_MODEL=base.en               # model name (base.en, small.en, medium.en, etc.)
WHISPER_DEVICE=auto                 # "auto" (GPU if available), "cpu", "cuda"
WHISPER_COMPUTE_TYPE=auto           # "auto", "int8", "float16", "float32"
WHISPER_BEAM_SIZE=1                 # beam size for decoding
WHISPER_LANGUAGE=en                 # language code
```

`WHISPER_DEVICE=auto` uses CUDA when available and gracefully falls back to CPU if CUDA runtime libraries are missing.

**Requires:** `--voice` flag (or `--listen`, which implies `--voice`).

### Text-to-Speech (TTS)

When TTS is enabled, responses are printed and spoken aloud using [Piper](https://github.com/rhasspy/piper), a fully local neural TTS engine.

**Enable TTS** by any of:
- CLI flag: `--tts`
- Config file: `TTS_ENABLED=true` in `~/.config/agent-client/config.env`
- In-session: `/tts`

`aplay` is required (part of `alsa-utils`).

#### Silent responses

The client supports `[silent]...[/silent]` tags in bot responses. Text inside these tags is displayed (dimmed) but not spoken aloud. This is useful for routine confirmations like smart home actions or simple command output where TTS would be annoying.

To enable, add an instruction to your bot's system prompt:

```
When you execute a routine action, wrap the confirmation in [silent]...[/silent] tags.
Example: [silent]Office light turned off.[/silent]
Only speak without tags when there's an error or something genuinely useful to say.
```

Mixed responses work too — `[silent]Light off.[/silent] By the way, your bedroom light has been on for 12 hours.` speaks only the second part.

### Voice config

All optional, in `~/.config/agent-client/config.env`:

```
TTS_ENABLED=true
PIPER_MODEL=en_US-lessac-medium
PIPER_MODEL_DIR=~/.local/share/piper
TTS_SPEED=1.0
LISTEN_SOUND=chime
WHISPER_MODEL=base.en
WAKE_WORDS=hey_jarvis,hey_computer
```

`PIPER_MODEL` sets the TTS voice. The format is `{language}-{name}-{quality}`. Models download automatically on first use (~30-80MB each). Common en_US voices:

| Model | Description |
|---|---|
| `en_US-lessac-medium` | Female, clear and natural — **the default** |
| `en_US-lessac-high` | Same voice, higher quality (larger model) |
| `en_US-amy-medium` | Female, warm tone |
| `en_US-ryan-medium` | Male, neutral |
| `en_US-ryan-high` | Same voice, higher quality |
| `en_US-joe-medium` | Male, casual |
| `en_US-john-medium` | Male |
| `en_US-bryce-medium` | Male |
| `en_US-kristin-medium` | Female |
| `en_US-kusal-medium` | Male |
| `en_US-norman-medium` | Male |
| `en_US-ljspeech-high` | Female, classic TTS voice |
| `en_US-hfc_female-medium` | Female |
| `en_US-hfc_male-medium` | Male |

British English voices are also available (e.g. `en_GB-alan-medium`, `en_GB-alba-medium`). See the [full voice list](https://github.com/rhasspy/piper/blob/master/VOICES.md) for all languages and voices.

`TTS_SPEED` controls speech rate. Values > 1.0 are faster, < 1.0 are slower.

`LISTEN_SOUND` is the confirmation tone played when the wake word is detected. Available presets:

| Preset | Description |
|---|---|
| `chime` | Two-tone rising (660Hz + 880Hz) — the default |
| `beep` | Single short 800Hz tone |
| `ping` | Quick high-pitched 1200Hz blip |

These client-side defaults can be overridden per-bot via the `voice` section in bot YAML. When you switch bots, the client fetches voice config from the server and applies any bot-specific overrides automatically.

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

### Long-Term Memory

When `memory.enabled` is set on a bot, compaction summaries are additionally written to a dedicated `memories` table with vector embeddings. These entries accumulate over time — each compaction appends a new memory rather than overwriting the previous one.

On each turn, the user's message is embedded and searched against stored memories via pgvector cosine similarity. Only memories above the similarity threshold (default 0.75) are injected, so irrelevant turns add nothing to context. When relevant memories are found, the client shows `[Recalled N memories...]`.

This is designed for long-lived sessions (weeks/months). Compaction keeps the active context lean, while the memory KB lets the model recall specifics from far back — "remember when I set up the Raspberry Pi?" finds the memory entry from three weeks ago.

**Bot config:**

```yaml
memory:
  enabled: true          # log compaction summaries + retrieve relevant memories
  cross_session: false   # default: search only current session's memories
                         # true: search all sessions for this client
  prompt: |              # optional: filter what gets stored in memory
    Only store information that reveals something new about the user: their
    preferences, projects, setup, people they mention, or decisions they made.
    Do not store routine commands (light switches, weather checks, timers)
    or small talk.
```

When `prompt` is set, each compaction summary is run through a distillation LLM call before being written to the KB. The LLM strips out noise and keeps only what matches the prompt's criteria. If nothing in the summary is worth remembering, the write is skipped entirely. This doesn't affect the session summary — only what goes into long-term memory.

**Global config** (in `.env`):

```
MEMORY_RETRIEVAL_LIMIT=5          # max memory chunks to retrieve per turn
MEMORY_SIMILARITY_THRESHOLD=0.75  # minimum cosine similarity (0-1)
```

**Manual trigger:** `POST /sessions/{id}/summarize` forces a compaction and memory write regardless of turn count. Useful for explicitly capturing a conversation before switching context.

## API

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check (no auth) |
| `/chat` | POST | Send a message, get a response |
| `/chat/stream` | POST | Same as `/chat` but streams SSE events with tool status |
| `/transcribe` | POST | Transcribe audio to text (server-side STT) |
| `/sessions` | GET | List sessions with titles (optional `?client_id=` filter) |
| `/sessions/{id}` | GET | Get session with full message history |
| `/sessions/{id}` | DELETE | Delete a session |
| `/sessions/{id}/summarize` | POST | Force summarization + memory write |
| `/bots` | GET | List available bots (includes per-bot `voice` config) |

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

### POST /transcribe

Send raw audio for server-side transcription.

```
POST /transcribe
Content-Type: application/octet-stream
Authorization: Bearer <API_KEY>

Body: raw 16kHz mono float32 PCM audio bytes
```

Returns:

```json
{"text": "hello world"}
```

Audio must be between 0.1s and 60s. The server runs faster-whisper (or whichever `STT_PROVIDER` is configured) and returns the transcribed text.

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
  routers/        FastAPI endpoints (/chat, /chat/stream, /sessions, /transcribe, /health)
  services/       Session persistence
  stt/            Speech-to-text provider abstraction (local whisper, future cloud)
  tools/          Tool registry, MCP proxy, local tools
    local/        Python tool implementations (web_search, client_action, etc.)
bots/             Bot YAML configs
skills/           Skill knowledge files (*.md)
mcp.yaml          MCP server connection config
client/           CLI client (separate installable package)
  agent_client/   Client source (cli, http client, audio, config, state)
android-client/   React Native Android client
migrations/       Alembic migrations
scripts/          Dev helper scripts
```
