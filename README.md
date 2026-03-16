# Agent Server

Self-hosted FastAPI agent server. Text-in, text-out chat with configurable LLM backend via LiteLLM, persistent sessions, and a tool system (local Python + MCP).

## Quick Start

```bash
cp .env.example .env         # edit this first — see "Configuration" below
./scripts/dev-server.sh      # starts postgres + server (terminal 1)
./scripts/dev-client.sh      # starts the CLI chat client (terminal 2)
```

## Configuration

### Server (.env)

Copy `.env.example` to `.env` and edit:

```
API_KEY=dev
DATABASE_URL=postgresql+asyncpg://agent:agent@localhost:5432/agentdb
LITELLM_BASE_URL=http://localhost:4000/v1
LITELLM_API_KEY=your-litellm-key
```

`API_KEY` is the bearer token that clients use to authenticate. For local dev, any value works — just make sure the client uses the same one.

`LITELLM_BASE_URL` points to your LiteLLM proxy. The server calls it with the OpenAI SDK, so this should be the `/v1` endpoint. LiteLLM needs to be running separately — it is not managed by this project's docker-compose.

### Bots (bots/*.yaml)

A bot is a named configuration that tells the server which model to use, what system prompt to send, and which tools are available. Bot YAML files live in `bots/` and are loaded once at server startup.

The server ships with one bot:

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

**`model`** is a LiteLLM model alias. It gets passed straight through to the LiteLLM `/v1/chat/completions` endpoint. Whatever models you've configured in LiteLLM, use those names here. For example if LiteLLM has `gpt-4.1-mini` mapped to an OpenAI key, or `claude-sonnet` mapped to Anthropic, those are the strings you'd put in `model`.

**To create a new bot**, add a YAML file to `bots/`:

```yaml
# bots/code.yaml
id: code
name: "Code Assistant"
model: claude-sonnet-4-20250514
system_prompt: |
  You are a senior software engineer. Be concise and direct.
  Provide code examples when helpful.
mcp_servers: []
local_tools:
  - get_current_time
rag: false
```

Then restart the server (or `./scripts/dev-server.sh` — uvicorn `--reload` picks up YAML changes in `bots/` on next request since they're loaded at startup, so you'd need a full restart).

**`local_tools`** lists tool names the bot is allowed to use. Available tools are defined in `app/tools/local/`. The example `get_current_time` tool is included.

**`mcp_servers`** lists LiteLLM MCP server aliases. If LiteLLM has MCP servers configured (e.g. `filesystem`, `github`), put their aliases here and the bot will have access to those tools.

## Using the CLI Client

Start it with:

```bash
./scripts/dev-client.sh
# or with a specific bot:
./scripts/dev-client.sh --bot code
# with TTS enabled:
./scripts/dev-client.sh --tts
# with full voice (TTS + voice input):
./scripts/dev-client.sh --tts --voice
```

You'll see a prompt like:

```
Agent Chat — session a1b2c3 | bot default | tts off
Type /help for commands.

[default|a1b2c3] >
```

The prompt shows `[bot_id|session_id]`. Just type a message and hit enter.

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
| `/bot <id>` | Switch to a different bot mid-session |
| `/bots` | List available bots |
| `/tts` | Toggle text-to-speech on/off |
| `/quit` | Exit (Ctrl+C also works) |

### Voice Input (STT)

Type `/v` to start recording. Speak into your mic — recording **auto-stops when you stop talking** (silence detection). The audio is transcribed locally via [faster-whisper](https://github.com/SYSTRAN/faster-whisper) and sent as a chat message. Combined with TTS, this gives you a full voice conversation loop.

The whisper model (~150MB for `base.en`) downloads on first use.

**Requires:** `./scripts/dev-client.sh --voice` (or `--tts` which also pulls in voice deps).

### Text-to-Speech (TTS)

When TTS is enabled, the bot's response is **printed and spoken aloud** using [Piper](https://github.com/rhasspy/piper), a fully local neural TTS engine. Nothing leaves the machine.

**Enable TTS** by any of:

- CLI flag: `./scripts/dev-client.sh --tts`
- Config file: set `TTS_ENABLED=true` in `~/.config/agent-client/config.env`
- In-session: type `/tts` to toggle on/off

The dev script auto-installs all deps when you pass `--tts` or `--voice`. Piper downloads its voice model (~60MB) on first use.

`aplay` is also required (part of `alsa-utils`, should already be on most Linux systems).

### Voice config

All optional, in `~/.config/agent-client/config.env`:

```
TTS_ENABLED=true
PIPER_MODEL=en_US-lessac-medium
PIPER_MODEL_DIR=~/.local/share/piper
WHISPER_MODEL=base.en
```

If `piper` or `aplay` aren't in PATH, TTS is disabled with an error. The text REPL always works regardless.

### How the client finds its settings

The client checks these in order (later overrides earlier):

1. `~/.config/agent-client/config.env` (optional persistent config)
2. Environment variables (`AGENT_URL`, `API_KEY`, `BOT_ID`, `TTS_ENABLED`, etc.)
3. CLI flags (`--url`, `--key`, `--bot`, `--tts`/`--no-tts`)

For local dev the scripts handle all of this — they pull `API_KEY` from your `.env` automatically.

### Sessions

The client generates a session UUID on first run and saves it to `~/.config/agent-client/state.json`. This means conversations persist across client restarts. Use `/new` to start a fresh conversation.

## Local Development Setup (manual)

If you don't want to use the scripts:

### 1. Postgres

```bash
docker compose up postgres -d
```

Useful commands:

```bash
docker compose logs postgres       # check logs
docker compose down                # stop
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

Note: when running in Docker, use Docker service names in `.env` (`postgres` not `localhost`).

## Project Layout

```
app/              Server application
  agent/          Agent loop, bot config, RAG stub
  db/             SQLAlchemy models + engine
  routers/        FastAPI endpoints (/chat, /sessions, /health)
  services/       Session persistence
  tools/          Tool registry, MCP proxy, local tools
bots/             Bot YAML configs
client/           CLI client (separate installable package)
migrations/       Alembic migrations
scripts/          Dev helper scripts
```
