import ast
import json
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode


class Settings(BaseSettings):
    TIMEZONE: str = "America/New_York"
    # Auth
    API_KEY: str

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://agent:agent@postgres:5432/agentdb"

    # LiteLLM
    LITELLM_BASE_URL: str = "http://litellm:4000/v1"
    LITELLM_API_KEY: str = ""
    # Image generation (OpenAI-compatible `images/generations` via LiteLLM)
    IMAGE_GENERATION_MODEL: str = "gemini/gemini-2.5-flash-image"

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
    LLM_FALLBACK_MODEL: str = ""             # if set, try this model once after all retries exhaust
    # Rate limit retry (task level — reschedules entire task on rate limit failure)
    TASK_RATE_LIMIT_RETRIES: int = 3         # max reschedule attempts before marking failed

    # Web tools
    SEARXNG_URL: str = "http://searxng:8080"
    PLAYWRIGHT_WS_URL: str = "ws://playwright:3000"

    # Bennie Loggins (pet health API)
    BENNIE_LOGGINS_BASE_URL: str = "https://bennieloggins.com"
    BENNIE_LOGGINS_API_KEY: str = ""

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

    # RAG / embeddings (skills, memory, knowledge). If you change EMBEDDING_MODEL, dimension
    # may change — you must re-embed (wipe documents/memories/bot_knowledge or run a migration).
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS: int = 1536
    RAG_TOP_K: int = 5
    RAG_SIMILARITY_THRESHOLD: float = 0.3

    # Filesystem indexing (semantic search over arbitrary directories)
    FS_INDEX_TOP_K: int = 8
    FS_INDEX_SIMILARITY_THRESHOLD: float = 0.30
    FS_INDEX_COOLDOWN_SECONDS: int = 300   # min seconds between full re-indexes per (root, bot)
    FS_INDEX_CHUNK_WINDOW: int = 1500      # chars for sliding-window fallback chunker
    FS_INDEX_CHUNK_OVERLAP: int = 200      # overlap chars for sliding-window chunks
    FS_INDEX_MAX_FILE_BYTES: int = 500_000 # skip files larger than this

    # Extra tool directories (colon-separated paths) scanned at startup in addition to ./tools/
    TOOL_DIRS: str = ""

    # Dynamic tool selection (embed tool descriptions, retrieve top-K per turn)
    TOOL_RETRIEVAL_THRESHOLD: float = 0.35
    TOOL_RETRIEVAL_TOP_K: int = 10

    # Memory
    MEMORY_RETRIEVAL_LIMIT: int = 5
    MEMORY_SIMILARITY_THRESHOLD: float = 0.75
    WIPE_MEMORY_ON_SESSION_DELETE: bool = False

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
    WORKSPACE_BASE_DIR: str = "~/.agent-workspaces"

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

    # Context compression (pre-turn summarization via cheap model)
    CONTEXT_COMPRESSION_ENABLED: bool = False
    CONTEXT_COMPRESSION_MODEL: str = ""          # empty = use COMPACTION_MODEL
    CONTEXT_COMPRESSION_THRESHOLD: int = 20000   # chars of conversation history to trigger
    CONTEXT_COMPRESSION_KEEP_TURNS: int = 2      # recent user turns kept verbatim
    CONTEXT_COMPRESSION_MAX_SUMMARY_TOKENS: int = 2000

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

    # CORS (comma-separated origins, e.g. "http://localhost:8081,http://localhost:19006")
    CORS_ORIGINS: str = ""

    # Frigate NVR
    FRIGATE_URL: str = ""  # e.g. http://192.168.1.x:5000
    FRIGATE_API_KEY: str = ""  # optional; only if behind an auth proxy
    FRIGATE_MAX_CLIP_BYTES: int = 52_428_800  # 50 MB max for video downloads

    # Slack
    SLACK_DEFAULT_BOT: str = "default"
    SLACK_BOT_TOKEN: str = ""  # xoxb-... used for channel name lookup in admin UI

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
