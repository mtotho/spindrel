# Agent Server

Self-hosted FastAPI agent server. Text-in, text-out chat with configurable LLM backend via LiteLLM, persistent sessions, a tool system (local Python + MCP), web search, and voice-enabled clients (Python CLI + Android) with wake word detection.

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

**Docker sandboxes** — Long-lived containers (OpenClaw-style) the agent can start and exec into. Enable with `DOCKER_SANDBOX_ENABLED=true`. See [DOCKER_SANDBOX_PLAN.md](DOCKER_SANDBOX_PLAN.md).

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
EMBEDDING_DIMENSIONS=1536                # must match the model's output dimension
RAG_TOP_K=5                              # max chunks to retrieve per query
RAG_SIMILARITY_THRESHOLD=0.3             # minimum cosine similarity (0-1)
```

The embedding model is called through your LiteLLM proxy, so any model LiteLLM supports works here. **If you change `EMBEDDING_MODEL` or `EMBEDDING_DIMENSIONS`**, existing vectors (documents, memories, bot_knowledge) are incompatible — you must re-embed everything: either wipe those tables and re-run your skill loader (and accept that memories/knowledge are lost), or add a migration that drops/recreates the vector columns with the new dimension.

### Available local tools

| Tool | Description |
|---|---|
| `get_current_time` | Returns current UTC time |
| `web_search` | Search the web via SearXNG. Returns top N results as JSON |
| `fetch_url` | Fetch and read a webpage via Playwright (falls back to httpx) |
| `client_action` | Perform actions on the client device (new session, switch bot, toggle TTS, etc.) |
| `update_persona` | Overwrite the bot's persona layer (see "Personas" below). Requires `persona: true` on the bot. |
| `upsert_knowledge` | Create or update a knowledge document by name. Requires `knowledge.enabled` on the bot. |
| `get_knowledge` | Retrieve a knowledge document by exact name. Requires `knowledge.enabled` on the bot. |
| `search_knowledge` | Search knowledge documents by semantic similarity. Requires `knowledge.enabled` on the bot. |
| `create_task` | Schedule a deferred agent job. Runs later and dispatches the result back to the originating channel/thread. For cross-bot work use `delegate_to_agent` instead. |
| `list_my_tasks` | List recent tasks for the current session with status and result previews. |
| `get_task` | Get the full status and result of a task by ID. |
| `cancel_task` | Cancel a pending task so it won't run. |
| `reschedule_task` | Change when a pending task will run. |
| `delegate_to_agent` | Run another bot as a sub-agent. Immediate mode returns the result synchronously; deferred mode creates a background task. See [docs/delegation.md](docs/delegation.md). |
| `delegate_to_harness` | Run an external CLI tool (e.g. `claude`, `cursor`) as a subprocess and return its stdout. Requires `harnesses.yaml` and `harness_access` on the bot. See [docs/harness.md](docs/harness.md). |
| `get_trace` | Read the current turn's RAG + tool call trace for self-debugging. |
| `list_sandbox_profiles` | List Docker sandbox profiles (image/templates) this bot can use. |
| `ensure_sandbox` | Start a **new** container from a profile; returns `instance_id` (each call adds one until max concurrent). |
| `exec_sandbox` | Run a shell command in a sandbox; requires `instance_id` from `ensure_sandbox`. |
| `stop_sandbox` | Stop a sandbox by `instance_id` (container kept). |
| `remove_sandbox` | Stop and remove a sandbox by `instance_id`. |

**`context_compaction`** (default `true`) enables automatic context summarization. When enabled, the server periodically uses an LLM to generate a title and detailed summary for the session, then loads the summary instead of the full message history. This keeps context windows manageable for long conversations.

**`compaction_interval`** overrides the global `COMPACTION_INTERVAL` for this bot. This is the number of user turns (not messages) between compaction runs. Default is 10.

**`compaction_model`** overrides the model used for summarization. By default it uses the global `COMPACTION_MODEL`, falling back to the bot's own model.

**`mcp_servers`** lists MCP server names defined in `mcp.yaml`. The agent server fetches available tools from each server's MCP endpoint, makes them available to the LLM, and proxies tool calls back.

```yaml
mcp_servers:
  - homeassistant
  - github
```

**Dynamic tool retrieval** — With `tool_retrieval: true` (the default), the server embeds each allowed local and MCP tool schema and each turn passes only the top similar tools to the LLM, plus any `pinned_tools` (always included). Tools in `client_tools` are always included. Routing (`call_local_tool`, `call_mcp_tool`, etc.) still uses the full registry and MCP cache. Set `tool_retrieval: false` to pass every allowed tool every turn. Global defaults: `TOOL_RETRIEVAL_THRESHOLD` and `TOOL_RETRIEVAL_TOP_K` in `.env`; per-bot override with `tool_similarity_threshold`. Details: [TOOL_RAG_PLAN.md](TOOL_RAG_PLAN.md).

```yaml
pinned_tools:
  - get_current_time
  - client_action
tool_retrieval: true
tool_similarity_threshold: 0.35
```

**Extra tool directories** — Drop-in Python tools can live in `./tools/` or paths in `TOOL_DIRS` (colon-separated in `.env`). See [tools/README.md](tools/README.md).

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

Values support `${ENV_VAR}` substitution so you can keep secrets in `.env`. The URL should be the full MCP endpoint — this works with any MCP-compatible server, not just LiteLLM. Tool schemas are cached for 60 seconds; when the cache refreshes, tool embeddings are updated in the background. At startup, the server waits until each MCP server referenced by a bot has been fetched and indexed before finishing readiness.

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

Voice and listen tone are configured **only on the client** (each client has its own TTS engine and available voices). Set them in `~/.config/agent-client/config.env` (Python) or in the app’s Settings screen (Android). The server does not send voice or tone settings per bot.

### How the client finds its settings

The client checks these in order (later overrides earlier):

1. `~/.config/agent-client/config.env` (optional persistent config)
2. Environment variables (`AGENT_URL`, `API_KEY`, `BOT_ID`, `TTS_ENABLED`, etc.)
3. CLI flags (`--url`, `--key`, `--bot`, `--tts`/`--no-tts`, `--listen`)

In-session overrides (for the current run only): `/tts_voice <model>` sets the Piper TTS voice; `/tone chime|beep|ping` sets the listen confirmation sound. Use `/tts_voice` or `/tone` with no argument to show the current value.

For local dev the scripts handle all of this — they pull `API_KEY` from your `.env` automatically.

### Sessions

The client generates a session UUID on first run and saves it to `~/.config/agent-client/state.json`. Conversations persist across client restarts. Use `/new` to start a fresh conversation.

### Context Compaction

Long conversations are automatically summarized to keep context windows manageable. After a configurable number of user turns, the server runs compaction **after** the turn is persisted. On the **streaming** path, compaction runs in the same request and events (including memory-phase tool use) are streamed to the client. On the **non-streaming** path, compaction runs in the background so the HTTP response is not blocked.

**Behavior:**

1. **Normal chat (RAG/agent loop)** — Unchanged. Each turn still does: set agent context, optional skills/RAG retrieval, optional memory retrieval, optional knowledge retrieval, append user message, then the agent tool loop (LLM + tools until final response).

2. **Compaction when the bot has no memory, persona, or knowledge** — When the turn count since the last compaction reaches `COMPACTION_INTERVAL`, the server runs a single LLM call with the base compaction prompt to produce a **title** and **detailed summary**, then updates the session watermark. On the next load, the session is system prompt + summary + the last N turns verbatim.

3. **Compaction when the bot has memory, persona, or knowledge enabled** — Before summarizing, the server runs a **memory phase**: the model gets only the memory/knowledge compaction prompt (e.g. “this conversation is about to be summarized; decide what to store in memory, knowledge, or persona and use tools”) and a transcript of the conversation (including truncated tool results so it can see what was retrieved). That is run through the **same agent tool loop** as normal chat (so the model can call `save_memory`, `upsert_knowledge`, `update_persona`, etc.). The memory phase does **not** produce the summary. When the model is done with tools, the server runs a **separate** one-off LLM call (`_generate_summary`) to produce the title and summary, then updates the watermark.

So: summary + last N turns in context (configurable via `COMPACTION_KEEP_TURNS`, default 10). Old messages stay in the database and are visible via `/history`.

Configure compaction globally in `.env`:

```
COMPACTION_MODEL=gemini/gemini-2.5-flash   # cheap/fast model for summaries
COMPACTION_INTERVAL=30                      # Run compaction when this many user turns exist since last compaction.
COMPACTION_KEEP_TURNS=10                    # Last N turns kept verbatim; only older turns are summarized.
```

Or per-bot in YAML:

```yaml
context_compaction: true       # default true; set false to disable
compaction_interval: 5         # override for this bot
compaction_model: gpt-4o-mini # override model for this bot
# memory_knowledge_compaction_prompt: |     # optional; override the "last chance to save" prompt (default from MEMORY_KNOWLEDGE_COMPACTION_PROMPT)
```

### Tool Result Summarization

Large tool outputs (e.g. `apt-get install` without `-q`, verbose build logs, long directory listings) burn through token budgets fast. Each tool result injected into context is re-sent to the LLM on every subsequent call in the same agent turn. A single 5 KB output adds ~1250 tokens to every remaining LLM call, compounding quickly at TPM limits.

Tool result summarization automatically condenses oversized outputs before they enter context:

1. After a tool call returns output above the threshold, the server makes a **one-shot summarization call** — no conversation history, just the raw tool output.
2. The summary (300 tokens max) replaces the full output in the LLM context. The raw output is still stored in the database.
3. The `tool_result` SSE event gains `"summarized": true` so clients can see when it happened.

**Why it saves tokens despite the extra call:** the summarization call is isolated and cheap (it can use a fast/cheap model like gemini-flash). The savings accumulate across all remaining LLM calls in the turn — with 3 more calls after a large tool result, you pay ~300 tokens once and save 3 × 1200 tokens instead.

**Global config** (`.env`):

```
TOOL_RESULT_SUMMARIZE_ENABLED=true
TOOL_RESULT_SUMMARIZE_THRESHOLD=3000      # chars; summarize if output exceeds this
TOOL_RESULT_SUMMARIZE_MODEL=gemini/gemini-2.5-flash  # empty = use bot's current model
TOOL_RESULT_SUMMARIZE_MAX_TOKENS=300     # max tokens for the summary output
TOOL_RESULT_SUMMARIZE_EXCLUDE_TOOLS=get_skill,read_file  # comma-separated, never summarize these
```

**Per-bot override** — configure in the admin UI or via `tool_result_config` in the bot's DB record. Bot settings take priority; omit a field to inherit the global setting. `exclude_tools` at the bot level is merged with (not a replacement for) the global exclude list.

```yaml
# Example: force-enable for this bot with a lower threshold and cheaper model
tool_result_config:
  enabled: true
  threshold: 1500
  model: gemini/gemini-2.5-flash
  max_tokens: 200
  exclude_tools:
    - list_sandbox_profiles
```

**Proactive mitigation:** tool descriptions for `exec_sandbox` and `run_host_command` already instruct the model to use quiet flags (`apt-get install -qq -y`, `pip install -q`, `npm install --silent`, etc.) to avoid verbose output in the first place.

### Long-Term Memory

When `memory.enabled` is set on a bot, the bot is given a memory tool which it can choose to write memories a dedicated `memories` table with vector embeddings. These entries accumulate over time — each tool invoke appends a new memory rather than overwriting the previous one.

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

### Knowledge

When `knowledge.enabled` is set on a bot, the bot gets tools to create and query **knowledge documents** — named, updatable docs (e.g. project notes, system layouts, runbooks) stored with vector embeddings. Unlike memories (many small facts), knowledge docs are single documents you overwrite as understanding grows; they are retrieved by semantic search or by exact name.

On each turn, the user's message is embedded and matched against knowledge docs via pgvector cosine similarity. Matching chunks (up to 3, above the similarity threshold) are injected as a system message so the model has relevant context without being told to call a tool.

**Bot config:**

```yaml
knowledge:
  enabled: true           # enable retrieval injection + knowledge tools
  cross_bot: false        # false: only this bot's docs + shared; true: all docs for this client
  similarity_threshold: 0.45   # minimum cosine similarity (0–1) for retrieval
local_tools:
  - upsert_knowledge
  - get_knowledge
  - search_knowledge
```

**Behaviour:**

- **upsert_knowledge** — Create or update a document by `name` (e.g. `project_xyz`, `home_network`). Use `shared: true` to make it visible to all bots for this client (stored with `bot_id` NULL).
- **get_knowledge** — Return the full content of a document by exact name.
- **search_knowledge** — Semantic search over knowledge docs; returns formatted chunks above the threshold.

Knowledge uses the same embedding model as skills and memory (`EMBEDDING_MODEL` in `.env`). The `bot_knowledge` table stores name, content, embedding, and scope (`bot_id`, `client_id`); a migration is required if not already applied.

### Personas

When `persona: true` is set on a bot, the bot gets a persistent **persona layer** — a short, first-person document of self-knowledge it maintains across all conversations for that bot. The layer is stored in the `bot_personas` table (one row per bot) and injected into context on every session load.

**How it works:**

1. **Enable on a bot** — In the bot YAML set `persona: true` and add `update_persona` to `local_tools`.
2. **Session context** — When a session is loaded (new or existing), if the bot has persona enabled and a stored layer exists, the server injects it as a system message: `[PERSONA]\n{content}`. So the LLM always sees the current persona alongside the main system prompt.
3. **Updates** — The bot can call the `update_persona` tool whenever it wants to revise the layer (e.g. when it notices a consistent preference or communication style worth keeping). The tool overwrites the entire layer; there is no append or patch.

**Intended use:** The persona is meant to stay small (under ~300 tokens), written in first person as self-knowledge — e.g. "I tend to be concise" or "I remember the user prefers dark mode" — not as instructions or rules. It lets the bot accumulate a stable identity across sessions without bloating the system prompt.

**Example bot config:**

```yaml
# bots/brief_bot.yaml
id: brief_bot
name: "Brief Bot"
persona: true
local_tools:
  - update_persona
  # ... other tools
```

The persona layer starts empty. Once the bot calls `update_persona` with content, that content is stored and used for all future turns and sessions for that bot.

## Using the Android Client

A React Native (Expo bare workflow) voice assistant app for Android tablets. Supports voice input, TTS, wake word detection, and runs as a foreground service so it stays alive behind a kiosk app like Home Assistant.

### Prerequisites

- Android SDK installed locally (Android Studio or standalone)
- `ANDROID_HOME` set, or `android-client/android/local.properties` with `sdk.dir=...`
- Java 17+, Node.js 18+

### Quick start

```bash
cd android-client
npm install
npx expo prebuild                     # generates android/ directory
ANDROID_HOME=/path/to/sdk npx expo run:android   # build + run on emulator/device
```

### Preloading config from .env

The Android client reads your server's `.env` at build time so you don't have to type keys on the device. Add to your `.env`:

```
ANDROID_AGENT_URL=http://192.168.1.100:8000   # your machine's LAN IP
PICOVOICE_ACCESS_KEY=your-key-here             # free from console.picovoice.ai
```

These become the defaults in the app. You can still override them in the in-app settings screen. `API_KEY` is also read automatically.

### Transcription (Server vs Local)

In Settings you can choose **Transcription**:

- **Server (Whisper)** — Recorded audio is sent to `POST /transcribe` and transcribed by faster-whisper on the server. Default; works for any audio format the server supports.
- **Local (Cheetah)** — On-device transcription with [Picovoice Cheetah](https://picovoice.ai/docs/cheetah/). No audio is sent for STT; uses the same Picovoice access key as wake word. Place the English model file `cheetah_params.pv` (from [Picovoice’s repo](https://github.com/Picovoice/cheetah/tree/master/lib/common)) in `android-client/cheetah_params.pv` so it is bundled with the app.

### Wake word detection

Uses [Picovoice Porcupine](https://picovoice.ai/platform/porcupine/) for on-device wake word detection. Free tier supports 14 built-in keywords (Jarvis, Alexa, Computer, etc.). Get a free access key at [console.picovoice.ai](https://console.picovoice.ai) — no credit card required.

Configure in the app's Settings tab under "Wake Word", or preload via `PICOVOICE_ACCESS_KEY` in `.env`. The same key is used for wake word and for local (Cheetah) transcription.

### Foreground service

The app runs an Android foreground service with a persistent notification so the voice pipeline stays alive when the app is backgrounded. The notification shows the current state (listening for wake word, hearing you, thinking, speaking). Requires `RECORD_AUDIO` permission which is requested at launch.

### Sideloading to a Fire tablet

1. Enable developer mode: Settings > Device Options > tap Serial Number 7 times
2. Enable ADB: Settings > Developer Options > Enable ADB
3. `adb connect <tablet-ip>:5555`
4. `adb install android-client/android/app/build/outputs/apk/debug/app-debug.apk`
5. I had to run this on my Android "GO" Edition since the option wasn't in the UI. `adb shell pm grant com.agentvoiceclient android.permission.SYSTEM_ALERT_WINDOW`


### More details

See [ANDROID_CLIENT_PLAN.MD](ANDROID_CLIENT_PLAN.MD) for the full architecture, build phases, and implementation status.

## Slack

A Slack Socket Mode bot routes channel messages to the `POST /chat` endpoint. It runs as a **separate process** (no inbound ports; Slack pushes events over an outbound WebSocket).

**Setup:** Add to `.env`:

```
SLACK_BOT_TOKEN=xoxb-...          # Bot token (from OAuth)
SLACK_APP_TOKEN=xapp-...          # App-level token (for Socket Mode)
AGENT_API_KEY=same-as-API_KEY     # Auth key for the agent-server
AGENT_BASE_URL=http://localhost:8000  # Agent-server URL
SLACK_DEFAULT_BOT=default         # Fallback bot when no channel mapping exists
```

When both Slack tokens are set, `./scripts/dev-server.sh` starts the bot automatically. To run standalone: `cd slack-integration && python slack_bot.py`.

**Slack app scopes** (Bot token): `app_mentions:read`, `chat:write`, `channels:history`, `channels:read`, `commands`, `files:read`, `files:write`. Optional: `chat:write.customize` for per-bot display names.

**Event subscriptions:** `message.channels`, `app_mention`

Full details: [docs/slack.md](docs/slack.md)

### Session model

Each Slack channel has **one shared session** derived deterministically from the channel ID. The session is shared across all bots in that channel — switching the default bot with `/bot` keeps the same session and preserves full conversation history.

### Active vs passive messages

Messages in a channel are classified as **active** or **passive**:

- **Active** — the agent runs and replies. Triggered by @mentioning the Slack app, or when `require_mention = false` for the channel.
- **Passive** — stored silently, no reply. Triggered by all other messages when `require_mention = true` (the default). Passive messages are injected as a system context block (`[Channel context — ambient messages not directed at the bot]`) on the next active turn, and optionally included in memory compaction so the bot can extract facts from channel activity into long-term knowledge.

Configure per-channel at **`/admin/slack`**.

### Channel configuration

| Setting | Default | Description |
|---|---|---|
| **Default Bot** | `SLACK_DEFAULT_BOT` | The bot that responds to @mentions and `/ask` in this channel. |
| **Require @mention** | `true` | When checked, only @mentions trigger the agent. All other messages are stored passively. When unchecked, the bot replies to every message. |
| **Passive memory** | `true` | When compaction runs, passive channel messages are included in the memory phase so the bot can extract relevant facts into knowledge. |

### Slash commands

Register these at **api.slack.com/apps → Slash Commands** (Socket Mode; Request URL is ignored). Enable the `commands` scope on the Bot token.

| Command | Description |
|---|---|
| `/ask <bot-id> <message>` | Route a message to a specific bot. Bot replies in the channel with its display name. `/ask` alone lists available bots. |
| `/bot [id]` | Show or switch the default bot for this channel. Session is unchanged. |
| `/bots` | List all available bots and their IDs. |
| `/context` | Show the current context window breakdown (chars per role). |
| `/compact` | Force session compaction (summarize + memory write) now. |
| `/plan [subcommand]` | View and manage agent plans (see below). |

**`/plan` subcommands:**

```
/plan                          List active plans
/plan list all                 List all plans including completed/abandoned
/plan <id>                     Show plan detail with item statuses
/plan done <id> <n>            Mark item n done
/plan skip <id> <n>            Mark item n skipped
/plan pending <id> <n>         Reset item n to pending
/plan progress <id> <n>        Mark item n in-progress
/plan complete <id>            Mark plan complete
/plan abandon <id>             Abandon a plan
```

`<id>` is a plan UUID prefix (first 8 chars is usually enough). Item numbers are 1-based.

### Multi-bot channels

A channel has one **default bot** (used for @mentions), but multiple bots can operate in the same channel:

- **`/ask <bot-id> <message>`** — routes directly to a specific bot; the bot replies attributed to its display name
- **Delegation** — the default bot can delegate to other bots via `delegate_to_agent`; the sub-bot's response is posted to the channel attributed to its display name

**Note:** Slack allows only one @mentionable user per app installation. Multiple independently @mentionable bots require separate Slack app installs.

## Task Scheduling

The task system lets the agent schedule deferred work and deliver results back to wherever the request came from — a Slack thread, a webhook, or just the DB for polling. A background worker polls for due tasks every 5 seconds.

### What you can do

**Reminders** — ask the bot to remind you of something later:

> "Remind me to check the deployment in 20 minutes"
> "Send me a message tomorrow morning at 9am asking if I submitted the timesheet"

The bot calls `create_task` with a prompt and a time offset. When the task fires, the result is posted back to the same Slack channel and thread automatically. No extra setup.

**Deferred research** — kick off a long job and come back to it:

> "In 2 hours, check the weather and the Hacker News front page and give me a summary"
> "At midnight, fetch the status of all my home assistant entities and save a snapshot to knowledge"

**Conditional follow-ups** — chain work together:

> "Check if the garage door is open. If it is, send me a message in 10 minutes to close it."

The agent handles this in one turn: check the door, then call `create_task` with a conditional prompt.

**Recurring-ish tasks** — approximate recurrence by scheduling the next task from within a task's prompt:

> "Every hour, check if the office temperature is above 78°F and message me if so"

The task prompt can include: *"After checking, schedule yourself again for +1h."* The agent will call `create_task` again at the end of each run.

### Time format

`create_task` and `reschedule_task` accept:

| Format | Example | Meaning |
|---|---|---|
| Relative offset | `+30m` | 30 minutes from now |
| Relative offset | `+2h` | 2 hours from now |
| Relative offset | `+1d` | 1 day from now |
| Relative offset | `+90s` | 90 seconds from now |
| ISO 8601 | `2026-03-20T09:00:00` | Absolute UTC time |
| null / omit | — | Run immediately (next worker poll, ≤5s) |

### Managing tasks

```
you:  remind me to water the plants in 2 hours
bot:  Done — task abc123 scheduled for 14:32 UTC.

you:  actually make it 3 hours
bot:  [calls list_my_tasks, then reschedule_task]
      Rescheduled to 15:32 UTC.

you:  cancel it
bot:  [calls cancel_task]
      Task abc123 cancelled.

you:  what tasks do i have pending?
bot:  [calls list_my_tasks]
      Tasks:
      - abc123 [pending] scheduled=2026-03-19 15:32 UTC
      - def456 [complete] scheduled=immediately | result: Office temp is 72°F.
```

### Adding task tools to a bot

```yaml
local_tools:
  - create_task
  - list_my_tasks
  - get_task
  - cancel_task
  - reschedule_task
```

Tool retrieval will surface them when the intent sounds like scheduling/reminders. If you want them always available regardless of RAG, add them to `pinned_tools` too.

### Dispatch types

When `create_task` is called during a request, it automatically inherits the dispatch routing from that request's context. You don't configure this per-task — it just works.

| dispatch_type | Where results go |
|---|---|
| `slack` | Posted to the originating Slack channel/thread via `chat.postMessage` |
| `webhook` | POSTed as JSON to a URL in `dispatch_config.url` |
| `internal` | Written as a message into a session so another agent can pick it up |
| `none` | Result stored in DB only; poll with `get_task` |

CLI and direct API clients get `none` by default — use `get_task` or check `/admin/tasks` to see results.

### Admin UI

`/admin/tasks` shows all tasks with status, bot, dispatch type, and result previews. Click a task for the full prompt, result, error traceback, dispatch config, and timing.

### API

Include dispatch fields in `POST /chat` to control where task results are delivered when calling from your own code:

```json
{
  "message": "check the weather and remind me again in 1 hour",
  "bot_id": "slack_bot",
  "client_id": "my-app",
  "dispatch_type": "webhook",
  "dispatch_config": {"url": "https://example.com/hooks/agent-results"}
}
```

## Bot-to-Bot Delegation

One bot can delegate work to another bot — either synchronously (immediate mode, result returned in the same turn) or as a background task (deferred mode).

**Quick setup:**

```yaml
# bots/orchestrator.yaml
local_tools:
  - delegate_to_agent
delegate_bots:
  - researcher_bot    # allowlist of bots this one can delegate to
```

Having a non-empty `delegate_bots` list enables delegation for that bot without requiring the global `DELEGATION_ENABLED` flag.

**Immediate delegation** (default) — the child bot runs now and its response is returned to the orchestrator as a tool result. On Slack, the child also posts its response to the thread attributed to the child bot's display name/icon.

**Deferred delegation** — creates a background task. The orchestrator gets a task ID and continues; the child's result is posted back to the originating channel when it completes.

**Delegation chains** — child bots can themselves delegate (up to `DELEGATION_MAX_DEPTH`, default 3). All chains are visible at `/admin/delegations` as a tree view.

**@-tag override** — users can mention `@bot-id` in their message to ephemeral-delegate to any bot, bypassing the allowlist for that single request.

→ Full details: [docs/delegation.md](docs/delegation.md)

## External Harnesses

Harnesses let a bot call external CLI tools (e.g. `claude`, `cursor`) as subprocesses and get their stdout back as a tool result.

**Quick setup:**

```yaml
# bots/my_bot.yaml
local_tools:
  - delegate_to_harness
harness_access:
  - claude-code    # allowlist of harness names from harnesses.yaml
```

**Claude Code harness** — uses `ANTHROPIC_API_KEY` from `.env` (inherited by the subprocess automatically). For Claude subscription users, see credential mounting in the docs.

```
ANTHROPIC_API_KEY=sk-ant-api03-...   # in .env
```

The `Dockerfile` and `dockerfiles/agent-python` both include Node.js + `@anthropic-ai/claude-code` for Docker deployments. The `harnesses.yaml` is mounted via `docker-compose.yml`.

→ Full details: [docs/harness.md](docs/harness.md)

## Integration Framework

External services (Gmail, GitHub, webhooks, etc.) can connect to the agent server without touching core code. Each integration lives in `integrations/<name>/` and is auto-discovered at startup.

**Integration API** — `/api/v1/` — REST endpoints for injecting messages and ingesting documents from external services. All require `Authorization: Bearer <API_KEY>`.

| Endpoint | Description |
|---|---|
| `POST /api/v1/sessions` | Create/get a session for an integration client |
| `POST /api/v1/sessions/{id}/messages` | Inject a message (optionally fan-out to Slack, trigger agent) |
| `GET /api/v1/sessions/{id}/messages` | List session messages |
| `POST /api/v1/documents` | Ingest + embed a document for semantic search |
| `GET /api/v1/documents/search?q=...` | Cosine similarity search over integration documents |
| `GET /api/v1/documents/{id}` | Fetch document by ID |
| `DELETE /api/v1/documents/{id}` | Delete document |

**Fan-out**: When a message is injected into a session with `notify=true`, it is automatically forwarded to the session's delivery targets. For Slack sessions (client_id starts with `slack:`), the message is posted to the corresponding channel.

→ Full details: [docs/integrations/README.md](docs/integrations/README.md)

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

Send audio for server-side transcription. Accepts two formats:

**Raw float32 PCM** (used by the Python CLI client):

```
POST /transcribe
Content-Type: application/octet-stream
Authorization: Bearer <API_KEY>

Body: raw 16kHz mono float32 PCM audio bytes
```

**Audio file** (used by the Android client — M4A, WAV, OGG, MP3, etc.):

```
POST /transcribe
Content-Type: audio/mp4
Authorization: Bearer <API_KEY>

Body: raw audio file bytes
```

The server detects the format from `Content-Type`. Audio files are decoded via ffmpeg (bundled with faster-whisper). Returns:

```json
{"text": "hello world"}
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
android-client/   React Native (Expo bare workflow) Android client
  app/            Expo Router screens (chat, sessions, settings)
  src/agent.ts    Server API client (chat, transcribe, SSE)
  src/config.ts   AsyncStorage config with build-time .env defaults
  src/service/    VoiceService state machine (idle → listen → process → respond)
  src/voice/      Wake word (Porcupine), recorder (expo-av), TTS (expo-speech)
  src/native/     TypeScript bridge to native foreground service module
  android/        Native Android project (foreground service, native modules)
migrations/       Alembic migrations
scripts/          Dev helper scripts
docs/             Feature documentation
  delegation.md   Bot-to-bot delegation (delegate_to_agent)
  harness.md      External CLI harness execution (delegate_to_harness, claude-code setup)
  slack.md        Slack integration (session model, passive messages, channel config)
```
