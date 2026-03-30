import ast
import json
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode


# ---------------------------------------------------------------------------
# Canonical memory-scheme prompt defaults (single source of truth)
# ---------------------------------------------------------------------------

DEFAULT_MEMORY_SCHEME_PROMPT = """\
## Memory

Your persistent memory lives in `{memory_rel}/` relative to your workspace directory.
MEMORY.md and recent daily logs are already in your context — do not re-read them.

The memory hierarchy from most stable to most ephemeral:

### MEMORY.md — Curated Knowledge Base
The single most important file. Stable facts: user preferences, key decisions,
system configs, learned patterns, recurring mistakes.
Keep under ~100 lines. Format: `## Sections` with `_Updated: YYYY-MM-DD_` headers.

**MEMORY.md Curation Protocol:**
- NEVER append session entries, progress notes, or "what happened today" to MEMORY.md
- NEVER clear and rewrite MEMORY.md — edit individual sections in place
- NEVER let MEMORY.md grow beyond ~100 lines — remove outdated info to make room
- Only write to MEMORY.md when you have a stable fact confirmed across sessions
- Each write should edit an existing section or add a new permanent section
- Deduplicate: before adding, check if the fact is already captured

### reference/ — Reference Documents
Longer guides, runbooks, architecture notes. Not in your context.
Use get_memory_file("name") or search_memory("query") to access.

### logs/YYYY-MM-DD.md — Daily Logs (Ephemeral)
Session notes, events, decisions, task progress. Today's and yesterday's logs
are in your context. Older logs are searchable only.

**Daily Log Protocol:**
- **Session start**: Append an entry to today's log with time and task context.
- **Every 3–5 responses**: Append a progress note. Do not let more than 5 responses pass without a write.
- **On any decision, correction, or discovery**: Write it immediately. Do not defer.
- **Self-check**: If you cannot point to a log write in the last few turns, write now before continuing.
- When context is getting large: summarize key points to today's log before they're lost.

### Tools
- search_memory(query) — hybrid semantic+keyword search across all memory files
- get_memory_file(name) — read a specific memory file
- Writing: use the `file` tool (write, append, edit operations) to write/edit memory files

### Promotion Rules
- Before answering about past work or context: search_memory first.
- When corrected on a mistake or preference: add it as a rule to MEMORY.md immediately.
- After establishing or agreeing on a file format, schema, convention, or workflow: write it to MEMORY.md or the appropriate reference file immediately — do not wait for a future session to confirm it.
- When a fact is confirmed across multiple sessions: promote it from daily log to MEMORY.md (edit in place, do not append)."""

DEFAULT_CHANNEL_WORKSPACE_PROMPT = """\
Channel workspace — absolute path: {workspace_path}
IMPORTANT: Always use the exact path above for file operations. The channel ID is {channel_id} (a UUID, NOT the channel name).
Use the `file` tool for reading, writing, editing, and listing workspace files (preferred over exec_command).
Use search_channel_archive to search archived files, search_channel_workspace for broader search.
Keep active files minimal — archive resolved items. Write durable learnings to memory.md, not workspace.
The data/ subfolder holds binary files (PDFs, images, etc.) — not auto-injected into context.
When receiving data files, save to data/ and create/update a workspace .md file with descriptions and metadata.
Cross-channel: if the user references another project/channel, use list_workspace_channels to find it, \
then search_channel_workspace with its channel_id to find relevant workspace content.
{data_listing}"""


DEFAULT_MEMORY_SCHEME_FLUSH_PROMPT = """\
Before this conversation is compacted, save important context to your memory files:
- Append key decisions and events to today's daily log
- Promote any new stable facts to MEMORY.md (edit existing sections in place, do not append session entries)
- Write anything you'll need to remember in future sessions
Use the `file` tool (append, write, edit) to write to the appropriate files."""


# ---------------------------------------------------------------------------
# Default global base prompt — prepended before all bot system prompts
# ---------------------------------------------------------------------------
# Covers fleet-wide operating rules, output style, delegation mechanics,
# scheduled tasks, tool discipline, and confidence signaling.
#
# Things intentionally NOT here (handled by other injection layers):
#   - Current datetime → context_assembly.py injects a system message
#   - Memory routing/tools/curation → DEFAULT_MEMORY_SCHEME_PROMPT
#   - Channel workspace paths → DEFAULT_CHANNEL_WORKSPACE_PROMPT
#   - Skill injection → context_assembly skill pipeline
#   - Conversation history → file-mode section index injection

DEFAULT_GLOBAL_BASE_PROMPT = """\
You are an agent on the Spindrel platform — a self-hosted multi-bot orchestration system.

## Operating Rules

- Do exactly what was asked. Do not add unrequested features, cleanup, or improvements.
- Before acting on ambiguous requests: state your assumption before proceeding, not after. \
Ask first only if the stakes are high.
- Do not take irreversible actions (delete, send, deploy) without explicit confirmation. \
Confirmation must be in the current session — do not infer it from prior messages.
- If your last 3+ actions have made no progress, stop and report your state — do not loop.

## Output Format

Be direct and conversational. No filler, no preamble, no narration of steps as you take them.

During multi-step tasks: work silently. When done, say what happened in plain language. \
Not a formula — just say it like a person would.

When composing messages for Slack: bold is *single asterisk*, links are <url|text>, \
lists use • bullets. Never use **double asterisks**, [text](url), or # headers.

## Persistent Files

Your file structure, tools, and curation rules are defined in a separate injection \
layer. This section covers only the connection to bot-specific behavior.

- Your bot-specific prompt defines a routing table — it tells you which content \
goes to which file within memory/. Follow it exactly.
- When writing preferences, corrections, or facts to reference files, write silently — \
these updates are background housekeeping. Don't announce them unless asked.
- When routing to a reference file, note the cross-reference in today's daily log: \
→ wrote to reference/filename.md

## Delegation

Some tasks should be handled by other bots. Your bot-specific prompt defines what to \
delegate. This section defines how.

To delegate, use the `delegate_to` tool:
- `bot_id` — the target bot
- `message` — a clear, self-contained request. Include all context the target needs. \
Don't assume it has your conversation history.
- `attachments` — optional file paths or references to pass along

Rules:
- Be explicit. The target bot sees your message, not your conversation.
- Include constraints — if you need a specific format, length, or focus, say so.
- Don't chain unnecessarily. If you can answer something yourself, do.
- Report the result, not the delegation. The user doesn't need to know which bot did \
the work unless they ask. Synthesize the response into your own voice.

## Scheduled Tasks

Channels can have heartbeats — periodic check-ins on a configurable interval with \
optional quiet hours. Bots can also have scheduled tasks (cron-style or one-shot) \
associated with any channel. Your bot-specific prompt defines what to do during \
heartbeats and scheduled tasks — the base platform just runs them on schedule.

When executing a heartbeat or scheduled task: stay focused on what the prompt asks for. \
Keep the work small and targeted. Don't expand scope beyond the task definition.

## Context Awareness

- Your conversation may have been compacted — if something feels missing, use \
read_conversation_history.
- If the user seems frustrated or you may be misunderstanding, use \
read_conversation_history before responding.
- For exact strings from past conversations (errors, paths, ports), use \
read_conversation_history(section='messages:<query>') — this greps raw messages.
- When a tool result was summarized and you need the full output, use \
read_conversation_history(section='tool:<id>').

## Tool Discipline

- If a tool's schema is not fully in context, call get_tool(name) or get_skill(name) first.
- After a tool error: diagnose, fix, retry once. After a second failure: stop and report.
- Never guess tool names or parameters — if unsure, check first.

## Confidence

- When you know something from memory or context, say so directly.
- When inferring or uncertain, flag it: "I believe..." / "Based on [source]..."
- Never fabricate facts, tool outputs, or file contents."""


class Settings(BaseSettings):
    # System pause
    SYSTEM_PAUSED: bool = False
    SYSTEM_PAUSE_BEHAVIOR: str = "queue"  # "queue" or "drop"

    # Global base prompt — prepended before all other base/system prompts for every bot
    GLOBAL_BASE_PROMPT: str = DEFAULT_GLOBAL_BASE_PROMPT

    TIMEZONE: str = "America/New_York"
    BASE_URL: str = ""  # Public URL (e.g. tunnel); used to build webhook URLs in admin UI

    # Auth
    API_KEY: str
    ADMIN_API_KEY: str = ""  # empty = fall back to API_KEY for backward compat

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://agent:agent@postgres:5432/agentdb"

    # LiteLLM
    LITELLM_BASE_URL: str = "http://litellm:4000/v1"
    LITELLM_API_KEY: str = ""
    # Image generation (OpenAI-compatible `images/generations` via LiteLLM)
    IMAGE_GENERATION_MODEL: str = "gemini/gemini-2.5-flash-image"

    # Prompt generation (AI-assisted prompt authoring in admin UI)
    PROMPT_GENERATION_MODEL: str = ""  # empty = uses default LiteLLM model
    PROMPT_GENERATION_TEMPERATURE: float = 0.7

    # Agent
    AGENT_MAX_ITERATIONS: int = 15
    LOG_LEVEL: str = "INFO"  # INFO = pathway only; DEBUG = full args, result previews, token counts
    AGENT_TRACE: bool = False  # When True: one-line trace per tool/response (no JSON), ideal for dev
    # Rate limit retry (LLM call level — preserves accumulated tool-call context)
    LLM_RATE_LIMIT_RETRIES: int = 3          # additional attempts after first failure
    LLM_RATE_LIMIT_INITIAL_WAIT: int = 90    # seconds before first retry (slightly > 60s TPM window)
    # General transient-error retry (5xx, connection errors, timeouts)
    LLM_MAX_RETRIES: int = 3                 # additional attempts after first failure
    LLM_RETRY_INITIAL_WAIT: float = 2.0      # seconds; doubles each retry (2, 4, 8…)
    LLM_TIMEOUT: float = 120.0              # HTTP timeout for LLM API calls (seconds); covers slow providers
    LLM_FALLBACK_MODEL: str = ""             # if set, try this model once after all retries exhaust
    LLM_FALLBACK_COOLDOWN_SECONDS: int = 300  # circuit breaker: skip broken models for this long after fallback
    # Rate limit retry (task level — reschedules entire task on rate limit failure)
    TASK_RATE_LIMIT_RETRIES: int = 3         # max reschedule attempts before marking failed
    # Max run time for tasks/heartbeats (seconds). Per-task > per-channel > this global default.
    TASK_MAX_RUN_SECONDS: int = 1200         # 20 minutes

    # Web tools
    SEARXNG_URL: str = "http://searxng:8080"
    PLAYWRIGHT_WS_URL: str = "ws://playwright:3000"

    # Context compaction
    COMPACTION_MODEL: str = "gemini/gemini-2.5-flash"
    COMPACTION_INTERVAL: int = 30 # Every time there gets to be N turns in the session (minus the compaction message), the compaction will run.
    COMPACTION_KEEP_TURNS: int = 10 # The last M turns will be kept in context, not included in the compaction. So compaction will only include the last N-M turns.

    # STT / Transcription
    STT_PROVIDER: str = "local"  # "local" (faster-whisper) or future: "groq", "openai"
    WHISPER_MODEL: str = "base.en"
    WHISPER_DEVICE: str = "auto"  # "auto", "cpu", "cuda"
    WHISPER_COMPUTE_TYPE: str = "auto"  # "auto", "int8", "float16", "float32"
    WHISPER_BEAM_SIZE: int = 1
    WHISPER_LANGUAGE: str = "en"

    # RAG / embeddings (skills, memory, knowledge).
    # `dimensions` is always passed on every embeddings.create() call, so models that
    # support Matryoshka truncation (text-embedding-3-*) are automatically truncated to
    # EMBEDDING_DIMENSIONS.  If you switch to a model whose native size < EMBEDDING_DIMENSIONS,
    # you must re-embed everything (wipe documents/memories/bot_knowledge or run a migration).
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS: int = 1536
    RAG_TOP_K: int = 5
    RAG_SIMILARITY_THRESHOLD: float = 0.3

    # Local embeddings (fastembed / ONNX)
    FASTEMBED_CACHE_DIR: str = ""  # directory for downloaded ONNX models; empty = fastembed default

    # Filesystem indexing (semantic search over arbitrary directories)
    FS_INDEX_TOP_K: int = 8
    FS_INDEX_SIMILARITY_THRESHOLD: float = 0.30
    FS_INDEX_COOLDOWN_SECONDS: int = 300   # min seconds between full re-indexes per (root, bot)
    FS_INDEX_CHUNK_WINDOW: int = 1500      # chars for sliding-window fallback chunker
    FS_INDEX_CHUNK_OVERLAP: int = 200      # overlap chars for sliding-window chunks
    FS_INDEX_MAX_FILE_BYTES: int = 500_000 # skip files larger than this
    FS_INDEX_CONCURRENCY: int = 8          # max concurrent file embeddings during indexing
    FS_INDEX_PERIODIC_MINUTES: int = 30     # periodic re-verify interval (0 = disabled); catches watcher crashes

    # Extra tool directories (colon-separated paths) scanned at startup in addition to ./tools/
    TOOL_DIRS: str = ""

    # Extra integration directories (colon-separated paths) scanned at startup
    # in addition to ./integrations/. See docs/integrations/README.md.
    INTEGRATION_DIRS: str = ""

    # Dynamic tool selection (embed tool descriptions, retrieve top-K per turn)
    TOOL_RETRIEVAL_THRESHOLD: float = 0.35
    TOOL_RETRIEVAL_TOP_K: int = 10

    # Memory
    MEMORY_RETRIEVAL_LIMIT: int = 5
    MEMORY_SIMILARITY_THRESHOLD: float = 0.75
    WIPE_MEMORY_ON_SESSION_DELETE: bool = False

    # Tool policies
    TOOL_POLICY_DEFAULT_ACTION: str = "deny"  # "allow", "deny", or "require_approval" — what happens when no rule matches
    TOOL_POLICY_ENABLED: bool = True  # master switch for the policy engine

    # Host execution
    HOST_EXEC_ENABLED: bool = False
    HOST_EXEC_DEFAULT_TIMEOUT: int = 30
    HOST_EXEC_MAX_OUTPUT_BYTES: int = 65536  # 64 KB
    HOST_EXEC_WORKING_DIR_ALLOWLIST: Annotated[list[str], NoDecode] = []
    HOST_EXEC_BLOCKED_PATTERNS: Annotated[list[str], NoDecode] = []
    HOST_EXEC_ENV_PASSTHROUGH: Annotated[list[str], NoDecode] = ["PATH", "HOME", "USER", "LANG", "TERM"]

    # Filesystem commands
    FS_COMMANDS_MAX_READ_BYTES: int = 500_000
    FS_COMMANDS_MAX_LIST_ENTRIES: int = 1000

    # Delegation
    DELEGATION_MAX_DEPTH: int = 3
    HARNESS_CONFIG_FILE: str = "harnesses.yaml"
    HARNESS_WORKING_DIR_ALLOWLIST: Annotated[list[str], NoDecode] = []
    HARNESS_MAX_RESUME_RETRIES: int = 1

    # Workspaces
    WORKSPACE_BASE_DIR: str = "~/.spindrel-workspaces"
    WORKSPACE_DEFAULT_IMAGE: str = "agent-workspace:latest"
    # Path translation for Docker deployment (sibling container pattern).
    # When the server runs inside Docker, it accesses workspace files via
    # a mounted volume (WORKSPACE_LOCAL_DIR), but child containers need
    # the actual host path (WORKSPACE_HOST_DIR) for their -v bind mounts.
    # Leave both empty when running the server on the host.
    WORKSPACE_HOST_DIR: str = ""    # e.g., "/home/you/.agent-workspaces"
    WORKSPACE_LOCAL_DIR: str = ""   # e.g., "/workspace-data"
    # Public URL of this server (injected into workspace containers)
    SERVER_PUBLIC_URL: str = "http://host.docker.internal:8000"

    # Workspace code editor (code-server)
    EDITOR_PORT_RANGE_START: int = 9100
    EDITOR_PORT_RANGE_END: int = 9199

    # Docker sandboxes
    DOCKER_SANDBOX_ENABLED: bool = False
    DOCKER_SOCKET_PATH: str = "/var/run/docker.sock"
    DOCKER_SANDBOX_MAX_CONCURRENT: int = 10
    DOCKER_SANDBOX_DEFAULT_TIMEOUT: int = 30
    DOCKER_SANDBOX_MAX_OUTPUT_BYTES: int = 65536  # 64 KB
    # NoDecode: env is always a string; pydantic-settings would json.loads(list[str]) first and
    # fail on single quotes or comma-separated paths before our validator runs.
    DOCKER_SANDBOX_MOUNT_ALLOWLIST: Annotated[list[str], NoDecode] = []
    DOCKER_SANDBOX_IDLE_PRUNE_INTERVAL: int = 300

    # RAG re-ranking (post-assembly cross-source relevance filtering)
    RAG_RERANK_ENABLED: bool = False
    RAG_RERANK_MODEL: str = ""              # empty = use COMPACTION_MODEL
    RAG_RERANK_THRESHOLD_CHARS: int = 5000  # only rerank when total RAG chars exceed this
    RAG_RERANK_MAX_CHUNKS: int = 20         # max chunks to keep after reranking
    RAG_RERANK_MAX_TOKENS: int = 1000       # max output tokens for reranker response

    # Chat History defaults
    DEFAULT_HISTORY_MODE: str = "file"  # "summary" | "structured" | "file"
    SECTION_INDEX_COUNT: int = 10
    SECTION_INDEX_VERBOSITY: str = "standard"  # "compact" | "standard" | "detailed"
    TRIGGER_HEARTBEAT_BEFORE_COMPACTION: bool = False  # deprecated — use MEMORY_FLUSH_ENABLED

    # Memory flush (dedicated pre-compaction memory save)
    MEMORY_FLUSH_ENABLED: bool = False
    MEMORY_FLUSH_MODEL: str = ""  # empty = use bot's model
    PREVIOUS_SUMMARY_INJECT_CHARS: int = 500  # max chars of existing summary injected into heartbeat/memory-flush context
    MEMORY_FLUSH_DEFAULT_PROMPT: str = """\
[MEMORY FLUSH — PRE-COMPACTION]
The conversation context is about to be compacted. Older messages will be archived and removed from your active context.

Review the recent conversation and save anything important:
- Use save_memory for facts, preferences, decisions, or context you'll need later
- Use update_knowledge for documentation or reference material worth preserving
- Use update_persona if the user revealed preferences about how they want to interact

Focus on what would be LOST if you couldn't see these messages anymore. Don't save things that are already in your memories or knowledge. Be selective — only save what matters."""

    # Memory scheme system prompt (workspace-files mode).
    # Use {memory_rel} placeholder for the bot-relative memory path.
    MEMORY_SCHEME_PROMPT: str = ""
    # Memory scheme flush prompt (workspace-files mode).
    # Empty = use DEFAULT_MEMORY_SCHEME_FLUSH_PROMPT.
    MEMORY_SCHEME_FLUSH_PROMPT: str = ""

    # Channel workspace injection prompt.
    # Placeholders: {workspace_path}, {channel_id}, {data_listing}
    # Empty = use DEFAULT_CHANNEL_WORKSPACE_PROMPT.
    CHANNEL_WORKSPACE_PROMPT: str = ""

    # Context pruning (trim old tool results at assembly time)
    CONTEXT_PRUNING_ENABLED: bool = True
    CONTEXT_PRUNING_KEEP_TURNS: int = 3
    CONTEXT_PRUNING_MIN_LENGTH: int = 200

    # Tool result summarization
    TOOL_RESULT_SUMMARIZE_ENABLED: bool = True
    TOOL_RESULT_SUMMARIZE_THRESHOLD: int = 3000       # chars; summarize if above this
    TOOL_RESULT_SUMMARIZE_MODEL: str = "gemini/gemini-2.5-flash"             # empty = use bot's current model
    TOOL_RESULT_SUMMARIZE_MAX_TOKENS: int = 300       # max tokens for summary output
    TOOL_RESULT_SUMMARIZE_EXCLUDE_TOOLS: Annotated[list[str], NoDecode] = ["get_skill"]

    # RAG injection limits (chars per item before joining; prevents context bloat)
    KNOWLEDGE_MAX_INJECT_CHARS: int = 8000   # per knowledge doc injected into context
    # Minimum cosine similarity when a knowledge row has no per-row override (0–1)
    KNOWLEDGE_SIMILARITY_THRESHOLD: float = 0.45
    MEMORY_MAX_INJECT_CHARS: int = 3000      # per memory item injected into context

    # Model elevation
    MODEL_ELEVATION_ENABLED: bool = False
    MODEL_ELEVATION_THRESHOLD: float = 0.4
    MODEL_ELEVATED_MODEL: str = "claude-sonnet-4-5"
    MODEL_ELEVATION_DEFAULT_MODEL: str = ""  # empty = use bot.model as default

    # Heartbeat schedule control
    HEARTBEAT_QUIET_HOURS: str = ""  # e.g. "23:00-07:00" — local time window where heartbeats slow/stop
    HEARTBEAT_QUIET_INTERVAL_MINUTES: int = 60  # interval during quiet hours (0 = disabled entirely)
    HEARTBEAT_ACTIVE_INTERVAL_MINUTES: int = 5  # default active interval (per-heartbeat DB value takes precedence)
    HEARTBEAT_DEFAULT_PROMPT: str = ""  # fallback prompt when channel heartbeat has no prompt/template/workspace file
    HEARTBEAT_PREVIOUS_CONCLUSION_CHARS: int = 500  # max chars of previous heartbeat conclusion injected into next heartbeat
    HEARTBEAT_REPETITION_DETECTION: bool = True
    HEARTBEAT_REPETITION_THRESHOLD: float = 0.8  # SequenceMatcher ratio
    HEARTBEAT_REPETITION_WARNING: str = (
        "WARNING: Your recent heartbeat outputs are repetitive — you keep producing "
        "very similar responses or taking the same actions. Break the pattern: find "
        "something genuinely new to report, try a different approach, or respond "
        "with just 'No updates.' Do NOT repeat the same text or tool calls as last time."
    )

    # Attachments
    ATTACHMENT_SUMMARY_ENABLED: bool = True
    ATTACHMENT_SUMMARY_MODEL: str = "gemini/gemini-2.5-flash"
    ATTACHMENT_VISION_CONCURRENCY: int = 3
    ATTACHMENT_SWEEP_INTERVAL_S: int = 60
    ATTACHMENT_TEXT_MAX_CHARS: int = 40_000  # ~10K tokens for text summarization
    ATTACHMENT_RETENTION_DAYS: int | None = None  # global default, None = keep forever
    ATTACHMENT_MAX_SIZE_BYTES: int | None = None  # global default, None = no limit
    ATTACHMENT_TYPES_ALLOWED: list[str] | None = None  # global default, None = all types
    ATTACHMENT_RETENTION_SWEEP_INTERVAL_S: int = 3600  # 1 hour between sweeps

    # User authentication (JWT + Google OAuth)
    JWT_SECRET: str = ""  # auto-generated on first startup if empty
    JWT_ACCESS_EXPIRY: int = 3600  # 1 hour
    JWT_REFRESH_EXPIRY: int = 2592000  # 30 days
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""

    # Config state auto-export (empty = disabled)
    CONFIG_STATE_FILE: str = "config-state.json"

    # CORS (comma-separated origins, e.g. "http://localhost:8081,http://localhost:19006")
    CORS_ORIGINS: str = ""

    BASE_COMPACTION_PROMPT: str ="""\
        You are a conversation summarizer. You will receive the message history of a \
        conversation between a user and an AI assistant.

        Produce a JSON object with the following fields:
        - "title": A concise title for this conversation (3-8 words, like a chat tab name).
        - "summary": A detailed summary of everything discussed so far. Include key facts, \
        decisions, code snippets or file paths mentioned, user preferences expressed, and \
        any ongoing tasks. This summary will replace the full history, so capture everything \
        the assistant would need to continue the conversation seamlessly.

        IMPORTANT: Include human-readable time references in the summary text itself \
        (e.g. "On March 5, 2025: ..." or "During the week of March 1-7: ..."). \
        These summaries may be stored as long-term memories and retrieved weeks later, \
        so temporal context is essential for the model to reason about when things happened.

        Respond ONLY with the JSON object, no markdown fences or extra text."""


    SECTION_EXECUTIVE_SUMMARY_PROMPT: str = """\
        You are a conversation historian. Below are section summaries from a long-running conversation. \
        Write a concise executive summary (3-5 sentences) covering the overall arc: \
        what the conversation has been about, key decisions made, and current state. \
        This summary will be injected as context for future messages, so focus on what \
        the assistant needs to know to continue effectively."""

    # Memory knowledge compaction prompt
    MEMORY_KNOWLEDGE_COMPACTION_PROMPT: str = """\
        This conversation is about to be summarized. You will keep the last N turns in context, and the rest will be summarized. So please decide now if there is 
        anything from this conversation so far that you want to store in memory, knowledge or update your persona with. Use available tools.
        """

    @field_validator(
        "DOCKER_SANDBOX_MOUNT_ALLOWLIST",
        "HOST_EXEC_WORKING_DIR_ALLOWLIST",
        "HOST_EXEC_BLOCKED_PATTERNS",
        "HOST_EXEC_ENV_PASSTHROUGH",
        "TOOL_RESULT_SUMMARIZE_EXCLUDE_TOOLS",
        "HARNESS_WORKING_DIR_ALLOWLIST",
        mode="before",
    )
    @classmethod
    def _parse_mount_allowlist(cls, v: object) -> list[str]:
        if isinstance(v, list):
            return [str(p).strip() for p in v if str(p).strip()]
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            if v.startswith("["):
                parsed: list | None = None
                try:
                    parsed = json.loads(v)
                except json.JSONDecodeError:
                    try:
                        parsed = ast.literal_eval(v)
                    except (ValueError, SyntaxError):
                        parsed = None
                if parsed is not None:
                    if not isinstance(parsed, list):
                        raise ValueError(
                            "DOCKER_SANDBOX_MOUNT_ALLOWLIST: expected a JSON/Python list of paths."
                        )
                    return [str(p).strip() for p in parsed if str(p).strip()]
                # Brackets but not valid JSON/Python, e.g. [/home/user/proj] (quotes omitted in .env)
                if v.endswith("]") and len(v) > 2:
                    inner = v[1:-1].strip()
                    if not inner:
                        return []
                    parts = [p.strip() for p in inner.split(",") if p.strip()]
                    if parts:
                        return parts
                raise ValueError(
                    "DOCKER_SANDBOX_MOUNT_ALLOWLIST: invalid list. "
                    "Use /a,/b or [\"/a\"] or [/a] (unquoted paths inside brackets)."
                )
            return [p.strip() for p in v.split(",") if p.strip()]
        return v

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
