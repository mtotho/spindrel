"""DB-backed server settings overrides for config.py values.

At startup, `load_settings_from_db()` reads overrides from the
`server_settings` table and patches the in-memory `settings` singleton.
The admin API uses `get_all_settings()` / `update_settings()` / `reset_setting()`
to manage overrides.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, settings
from app.db.models import ServerSetting

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema: describes every setting exposed to the admin UI
# ---------------------------------------------------------------------------

SETTINGS_SCHEMA: dict[str, dict[str, Any]] = {
    # --- System ---
    "SYSTEM_PAUSED": {"group": "System", "label": "System Paused", "description": "Pause all message processing (new requests queued or dropped)", "type": "bool"},
    "SYSTEM_PAUSE_BEHAVIOR": {"group": "System", "label": "Pause Behavior", "description": "What to do with incoming messages while paused", "type": "string", "options": ["queue", "drop"]},
    "GLOBAL_BASE_PROMPT": {"group": "System", "label": "Global Base Prompt", "description": "Prepended before all other base/system prompts for every bot. Use for org-wide instructions.", "type": "string", "widget": "textarea"},
    # --- General ---
    "API_KEY": {"group": "General", "label": "API Key", "description": "Static API key for server auth", "type": "string", "read_only": True},
    "TIMEZONE": {"group": "General", "label": "Timezone", "description": "Server timezone (e.g. America/New_York)", "type": "string"},
    "LOG_LEVEL": {"group": "General", "label": "Log Level", "description": "Logging verbosity", "type": "string", "options": ["DEBUG", "INFO", "WARNING", "ERROR"]},
    "CORS_ORIGINS": {"group": "General", "label": "CORS Origins", "description": "Comma-separated allowed origins", "type": "string"},
    "AGENT_TRACE": {"group": "General", "label": "Agent Trace", "description": "Enable one-line trace per tool/response", "type": "bool"},
    # --- Agent ---
    "AGENT_MAX_ITERATIONS": {"group": "Agent", "label": "Max Iterations", "description": "Maximum agent loop iterations per request", "type": "int", "min": 1, "max": 100},
    "LLM_FALLBACK_MODEL": {"group": "Agent", "label": "Fallback Model", "description": "Model to try after all retries exhaust (empty = none)", "type": "string", "widget": "model"},
    "LLM_MAX_RETRIES": {"group": "Agent", "label": "LLM Max Retries", "description": "Retry attempts for transient errors (5xx, connection)", "type": "int", "min": 0, "max": 10},
    "LLM_RETRY_INITIAL_WAIT": {"group": "Agent", "label": "LLM Retry Initial Wait", "description": "Seconds before first retry (doubles each attempt)", "type": "float", "min": 0.5, "max": 60},
    "LLM_RATE_LIMIT_RETRIES": {"group": "Agent", "label": "Rate Limit Retries", "description": "Additional attempts after rate limit failure", "type": "int", "min": 0, "max": 10},
    "LLM_RATE_LIMIT_INITIAL_WAIT": {"group": "Agent", "label": "Rate Limit Initial Wait", "description": "Seconds before first rate limit retry", "type": "int", "min": 10, "max": 300},
    # --- Chat History ---
    "DEFAULT_HISTORY_MODE": {"group": "Chat History", "label": "Default History Mode", "description": "How conversation history is stored and retrieved", "type": "string", "options": ["summary", "structured", "file"]},
    "COMPACTION_MODEL": {"group": "Chat History", "label": "Compaction Model", "description": "LiteLLM model alias for context compaction", "type": "string", "widget": "model"},
    "COMPACTION_INTERVAL": {"group": "Chat History", "label": "Compaction Interval", "description": "Turns between compaction runs", "type": "int", "min": 5, "max": 200},
    "COMPACTION_KEEP_TURNS": {"group": "Chat History", "label": "Keep Turns", "description": "Recent turns kept in context (not compacted)", "type": "int", "min": 1, "max": 50},
    "TRIGGER_HEARTBEAT_BEFORE_COMPACTION": {"group": "Chat History", "label": "Trigger Heartbeat Before Compaction", "description": "Fire channel heartbeats before compaction instead of the dedicated memory phase LLM call", "type": "bool"},
    "SECTION_INDEX_COUNT": {"group": "Chat History", "label": "Section Index Count", "description": "Number of recent sections shown in the index (file mode)", "type": "int", "min": 0, "max": 100},
    "SECTION_INDEX_VERBOSITY": {"group": "Chat History", "label": "Section Index Verbosity", "description": "Detail level for section index entries", "type": "string", "options": ["compact", "standard", "detailed"]},
    # --- Embeddings & RAG ---
    "EMBEDDING_MODEL": {"group": "Embeddings & RAG", "label": "Embedding Model", "description": "Model for text embeddings", "type": "string"},
    "RAG_TOP_K": {"group": "Embeddings & RAG", "label": "RAG Top-K", "description": "Number of RAG results to return", "type": "int", "min": 1, "max": 50},
    "RAG_SIMILARITY_THRESHOLD": {"group": "Embeddings & RAG", "label": "RAG Similarity Threshold", "description": "Minimum cosine similarity for RAG results", "type": "float", "min": 0.0, "max": 1.0},
    "TOOL_RETRIEVAL_THRESHOLD": {"group": "Embeddings & RAG", "label": "Tool Retrieval Threshold", "description": "Minimum similarity for tool retrieval", "type": "float", "min": 0.0, "max": 1.0},
    "TOOL_RETRIEVAL_TOP_K": {"group": "Embeddings & RAG", "label": "Tool Retrieval Top-K", "description": "Number of tools returned by retrieval", "type": "int", "min": 1, "max": 50},
    "MEMORY_RETRIEVAL_LIMIT": {"group": "Embeddings & RAG", "label": "Memory Retrieval Limit", "description": "Max memory items to retrieve", "type": "int", "min": 1, "max": 50},
    "MEMORY_SIMILARITY_THRESHOLD": {"group": "Embeddings & RAG", "label": "Memory Similarity Threshold", "description": "Minimum similarity for memory retrieval", "type": "float", "min": 0.0, "max": 1.0},
    "KNOWLEDGE_SIMILARITY_THRESHOLD": {"group": "Embeddings & RAG", "label": "Knowledge Similarity Threshold", "description": "Minimum similarity for knowledge retrieval", "type": "float", "min": 0.0, "max": 1.0},
    "KNOWLEDGE_MAX_INJECT_CHARS": {"group": "Embeddings & RAG", "label": "Knowledge Max Inject Chars", "description": "Max chars per knowledge doc injected", "type": "int", "min": 500, "max": 50000},
    "MEMORY_MAX_INJECT_CHARS": {"group": "Embeddings & RAG", "label": "Memory Max Inject Chars", "description": "Max chars per memory item injected", "type": "int", "min": 500, "max": 50000},
    # --- RAG Re-ranking ---
    "RAG_RERANK_ENABLED": {"group": "RAG Re-ranking", "label": "Enabled", "description": "Re-rank RAG chunks across sources using an LLM", "type": "bool"},
    "RAG_RERANK_MODEL": {"group": "RAG Re-ranking", "label": "Model", "description": "Model for re-ranking (empty = compaction model)", "type": "string", "widget": "model"},
    "RAG_RERANK_THRESHOLD_CHARS": {"group": "RAG Re-ranking", "label": "Threshold (chars)", "description": "Only re-rank when total RAG chars exceed this", "type": "int", "min": 500, "max": 100000},
    "RAG_RERANK_MAX_CHUNKS": {"group": "RAG Re-ranking", "label": "Max Chunks", "description": "Max chunks to keep after re-ranking", "type": "int", "min": 1, "max": 100},
    "RAG_RERANK_MAX_TOKENS": {"group": "RAG Re-ranking", "label": "Max Tokens", "description": "Max output tokens for re-ranker response", "type": "int", "min": 100, "max": 4000},
    # --- Tool Summarization ---
    "TOOL_RESULT_SUMMARIZE_ENABLED": {"group": "Tool Summarization", "label": "Enabled", "description": "Auto-summarize long tool results", "type": "bool"},
    "TOOL_RESULT_SUMMARIZE_THRESHOLD": {"group": "Tool Summarization", "label": "Threshold (chars)", "description": "Summarize tool results above this character count", "type": "int", "min": 500, "max": 50000},
    "TOOL_RESULT_SUMMARIZE_MODEL": {"group": "Tool Summarization", "label": "Model", "description": "Model for tool result summarization", "type": "string", "widget": "model"},
    "TOOL_RESULT_SUMMARIZE_MAX_TOKENS": {"group": "Tool Summarization", "label": "Max Tokens", "description": "Max tokens for summary output", "type": "int", "min": 50, "max": 2000},
    # --- Model Elevation ---
    "MODEL_ELEVATION_ENABLED": {"group": "Model Elevation", "label": "Enabled", "description": "Enable dynamic model elevation for complex queries", "type": "bool"},
    "MODEL_ELEVATION_THRESHOLD": {"group": "Model Elevation", "label": "Threshold", "description": "Complexity threshold to trigger elevation (0-1)", "type": "float", "min": 0.0, "max": 1.0},
    "MODEL_ELEVATED_MODEL": {"group": "Model Elevation", "label": "Elevated Model", "description": "Model to elevate to", "type": "string", "widget": "model"},
    "MODEL_ELEVATION_DEFAULT_MODEL": {"group": "Model Elevation", "label": "Default Model", "description": "Default model (empty = bot model)", "type": "string", "widget": "model"},
    # --- Speech-to-Text ---
    "STT_PROVIDER": {"group": "Speech-to-Text", "label": "STT Provider", "description": "Transcription provider", "type": "string", "options": ["local", "groq", "openai"]},
    "WHISPER_MODEL": {"group": "Speech-to-Text", "label": "Whisper Model", "description": "faster-whisper model name", "type": "string"},
    "WHISPER_DEVICE": {"group": "Speech-to-Text", "label": "Device", "description": "Compute device", "type": "string", "options": ["auto", "cpu", "cuda"]},
    "WHISPER_COMPUTE_TYPE": {"group": "Speech-to-Text", "label": "Compute Type", "description": "Compute precision", "type": "string", "options": ["auto", "int8", "float16", "float32"]},
    "WHISPER_BEAM_SIZE": {"group": "Speech-to-Text", "label": "Beam Size", "description": "Beam search width", "type": "int", "min": 1, "max": 10},
    "WHISPER_LANGUAGE": {"group": "Speech-to-Text", "label": "Language", "description": "Transcription language code", "type": "string"},
    # --- Heartbeat ---
    "HEARTBEAT_QUIET_HOURS": {"group": "Heartbeat", "label": "Quiet Hours", "description": "Time window where heartbeats slow (e.g. 23:00-07:00)", "type": "string"},
    "HEARTBEAT_QUIET_INTERVAL_MINUTES": {"group": "Heartbeat", "label": "Quiet Interval (min)", "description": "Interval during quiet hours (0 = disabled)", "type": "int", "min": 0, "max": 1440},
    "HEARTBEAT_ACTIVE_INTERVAL_MINUTES": {"group": "Heartbeat", "label": "Active Interval (min)", "description": "Default active heartbeat interval", "type": "int", "min": 1, "max": 1440},
    # --- Attachments ---
    "ATTACHMENT_SUMMARY_ENABLED": {"group": "Attachments", "label": "Summary Enabled", "description": "Auto-summarize attachments", "type": "bool"},
    "ATTACHMENT_SUMMARY_MODEL": {"group": "Attachments", "label": "Summary Model", "description": "Model for attachment summarization", "type": "string", "widget": "model"},
    "ATTACHMENT_VISION_CONCURRENCY": {"group": "Attachments", "label": "Vision Concurrency", "description": "Max concurrent vision API calls", "type": "int", "min": 1, "max": 20},
    "ATTACHMENT_TEXT_MAX_CHARS": {"group": "Attachments", "label": "Text Max Chars", "description": "Max chars for text summarization", "type": "int", "min": 1000, "max": 200000},
    "ATTACHMENT_RETENTION_DAYS": {"group": "Attachments", "label": "Retention Days", "description": "Days to keep attachments (empty = forever)", "type": "int", "min": 1, "max": 3650, "nullable": True},
    "ATTACHMENT_MAX_SIZE_BYTES": {"group": "Attachments", "label": "Max Size (bytes)", "description": "Max attachment size (empty = no limit)", "type": "int", "min": 1024, "max": 1073741824, "nullable": True},
    # --- Image Generation ---
    "IMAGE_GENERATION_MODEL": {"group": "Image Generation", "label": "Model", "description": "Model for image generation", "type": "string", "widget": "model"},
    # --- Prompt Generation ---
    "PROMPT_GENERATION_MODEL": {"group": "Prompt Generation", "label": "Model", "description": "Model used for the Generate Prompt feature in admin UI (empty = default LiteLLM model)", "type": "string", "widget": "model"},
}

# Group ordering for consistent display
GROUP_ORDER = [
    "System", "General", "Agent", "Chat History",
    "Embeddings & RAG", "RAG Re-ranking", "Tool Summarization", "Model Elevation",
    "Speech-to-Text", "Heartbeat", "Attachments", "Image Generation", "Prompt Generation",
]


def _coerce(value: str, schema: dict[str, Any]) -> Any:
    """Coerce a string DB value to the correct Python type."""
    dtype = schema.get("type", "string")
    if dtype == "bool":
        return value.lower() in ("true", "1", "yes")
    if dtype == "int":
        if schema.get("nullable") and value in ("", "None", "null"):
            return None
        return int(value)
    if dtype == "float":
        return float(value)
    return value


def _serialize(value: Any) -> str:
    """Serialize a Python value to a string for DB storage."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _get_env_default(key: str) -> Any:
    """Get the default value from the Settings class (not the in-memory instance)."""
    field = Settings.model_fields.get(key)
    if field is None:
        return None
    return field.default


# ---------------------------------------------------------------------------
# Startup loader
# ---------------------------------------------------------------------------

async def load_settings_from_db() -> None:
    """Load DB overrides and patch the in-memory settings singleton."""
    from app.db.engine import async_session

    async with async_session() as db:
        rows = (await db.execute(select(ServerSetting))).scalars().all()

    patched = 0
    for row in rows:
        schema = SETTINGS_SCHEMA.get(row.key)
        if not schema:
            logger.warning("Ignoring unknown setting key in DB: %s", row.key)
            continue
        if schema.get("read_only"):
            continue
        try:
            typed_value = _coerce(row.value, schema)
            object.__setattr__(settings, row.key, typed_value)
            patched += 1
        except (ValueError, TypeError) as exc:
            logger.warning("Failed to apply setting %s=%r: %s", row.key, row.value, exc)

    if patched:
        logger.info("Applied %d server setting override(s) from DB", patched)


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

async def get_all_settings() -> list[dict[str, Any]]:
    """Return grouped settings with current values, defaults, and override flags."""
    from app.db.engine import async_session

    async with async_session() as db:
        rows = (await db.execute(select(ServerSetting))).scalars().all()
    overrides = {row.key: row.value for row in rows}

    groups: dict[str, list[dict[str, Any]]] = {}
    for key, schema in SETTINGS_SCHEMA.items():
        group = schema["group"]
        current_value = getattr(settings, key, None)
        env_default = _get_env_default(key)
        is_overridden = key in overrides

        entry = {
            "key": key,
            "label": schema["label"],
            "description": schema["description"],
            "type": schema["type"],
            "value": _mask_value(key, current_value) if schema.get("read_only") else current_value,
            "default": env_default,
            "overridden": is_overridden,
            "read_only": schema.get("read_only", False),
        }
        if "options" in schema:
            entry["options"] = schema["options"]
        if "min" in schema:
            entry["min"] = schema["min"]
        if "max" in schema:
            entry["max"] = schema["max"]
        if schema.get("nullable"):
            entry["nullable"] = True
        if "widget" in schema:
            entry["widget"] = schema["widget"]

        groups.setdefault(group, []).append(entry)

    # Return ordered groups
    result = []
    for group_name in GROUP_ORDER:
        if group_name in groups:
            result.append({"group": group_name, "settings": groups[group_name]})
    # Catch any groups not in GROUP_ORDER
    for group_name, items in groups.items():
        if group_name not in GROUP_ORDER:
            result.append({"group": group_name, "settings": items})

    return result


def _mask_value(key: str, value: Any) -> str:
    """Mask sensitive values for display."""
    s = str(value or "")
    if len(s) <= 8:
        return "****"
    return s[:4] + "****" + s[-4:]


async def update_settings(updates: dict[str, Any], db: AsyncSession) -> dict[str, Any]:
    """Upsert settings to DB and patch in-memory. Returns applied updates."""
    applied = {}
    now = datetime.now(timezone.utc)

    for key, value in updates.items():
        schema = SETTINGS_SCHEMA.get(key)
        if not schema:
            raise ValueError(f"Unknown setting: {key}")
        if schema.get("read_only"):
            raise ValueError(f"Setting is read-only: {key}")

        # Coerce to validate type
        str_value = _serialize(value)
        typed_value = _coerce(str_value, schema)

        # Upsert to DB
        stmt = pg_insert(ServerSetting).values(
            key=key, value=str_value, updated_at=now,
        ).on_conflict_do_update(
            index_elements=["key"],
            set_={"value": str_value, "updated_at": now},
        )
        await db.execute(stmt)

        # Patch in-memory
        object.__setattr__(settings, key, typed_value)
        applied[key] = typed_value

    await db.commit()
    return applied


async def reset_setting(key: str, db: AsyncSession) -> Any:
    """Delete DB override and revert to env default."""
    schema = SETTINGS_SCHEMA.get(key)
    if not schema:
        raise ValueError(f"Unknown setting: {key}")
    if schema.get("read_only"):
        raise ValueError(f"Setting is read-only: {key}")

    await db.execute(delete(ServerSetting).where(ServerSetting.key == key))
    await db.commit()

    env_default = _get_env_default(key)
    object.__setattr__(settings, key, env_default)
    return env_default
