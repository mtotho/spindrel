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
    # --- Paths ---
    "SPINDREL_HOME": {"group": "Paths", "label": "Spindrel Home", "description": "Path to your Spindrel home directory. Each subdirectory is discovered as an integration (tools, capabilities, skills). In Docker, set HOME_HOST_DIR and HOME_LOCAL_DIR env vars for path translation. Requires server restart.", "type": "string", "nullable": True},
    "INTEGRATION_DIRS": {"group": "Paths", "label": "Integration Directories", "description": "Colon-separated paths to external integration directories. Deprecated — use Spindrel Home instead.", "type": "string", "nullable": True, "ui_hidden": True},
    "TOOL_DIRS": {"group": "Paths", "label": "Extra Tool Directories", "description": "Colon-separated paths to extra tool directories. Deprecated — use Spindrel Home instead.", "type": "string", "nullable": True, "ui_hidden": True},
    # --- General ---
    "API_KEY": {"group": "General", "label": "API Key", "description": "Static API key for server auth", "type": "string", "read_only": True},
    "TIMEZONE": {"group": "General", "label": "Timezone", "description": "Server timezone (e.g. America/New_York)", "type": "string"},
    "LOG_LEVEL": {"group": "General", "label": "Log Level", "description": "Logging verbosity", "type": "string", "options": ["DEBUG", "INFO", "WARNING", "ERROR"]},
    "CORS_ORIGINS": {"group": "General", "label": "CORS Origins", "description": "Comma-separated allowed origins", "type": "string"},
    "AGENT_TRACE": {"group": "General", "label": "Agent Trace", "description": "Enable one-line trace per tool/response", "type": "bool"},
    # --- Agent ---
    "AGENT_MAX_ITERATIONS": {"group": "Agent", "label": "Max Iterations", "description": "Maximum agent loop iterations per request", "type": "int", "min": 1, "max": 100},
    "TOOL_LOOP_DETECTION_ENABLED": {"group": "Agent", "label": "Tool Loop Detection", "description": "Detect and break repeating tool call cycles within a single agent run", "type": "bool"},
    "PARALLEL_TOOL_EXECUTION": {"group": "Agent", "label": "Parallel Tool Execution", "description": "Dispatch multiple tool calls concurrently (latency = max instead of sum)", "type": "bool"},
    "PARALLEL_TOOL_MAX_CONCURRENT": {"group": "Agent", "label": "Parallel Tool Max Concurrent", "description": "Max concurrent tool dispatches per batch (semaphore limit)", "type": "int", "min": 1, "max": 50},
    "CAPABILITIES_DISABLED": {"group": "Agent", "label": "Disabled Capabilities", "description": "Comma-separated carapace IDs to hide globally from auto-discovery (e.g. 'orchestrator,arr')", "type": "string", "nullable": True},
    "LLM_FALLBACK_MODEL": {"group": "Agent", "label": "Fallback Model", "description": "Model to try after all retries exhaust (empty = none)", "type": "string", "widget": "model"},
    "LLM_FALLBACK_MODEL_PROVIDER_ID": {"group": "Agent", "label": "Fallback Model Provider", "type": "string", "description": "Provider for fallback model", "ui_hidden": True},
    "LLM_MAX_RETRIES": {"group": "Agent", "label": "LLM Max Retries", "description": "Retry attempts for transient errors (5xx, connection)", "type": "int", "min": 0, "max": 10},
    "LLM_RETRY_INITIAL_WAIT": {"group": "Agent", "label": "LLM Retry Initial Wait", "description": "Seconds before first retry (doubles each attempt)", "type": "float", "min": 0.5, "max": 60},
    "LLM_RATE_LIMIT_RETRIES": {"group": "Agent", "label": "Rate Limit Retries", "description": "Additional attempts after rate limit failure", "type": "int", "min": 0, "max": 10},
    "LLM_RATE_LIMIT_INITIAL_WAIT": {"group": "Agent", "label": "Rate Limit Initial Wait", "description": "Seconds before first rate limit retry", "type": "int", "min": 10, "max": 300},
    # --- Chat History ---
    "DEFAULT_HISTORY_MODE": {"group": "Chat History", "label": "Default History Mode", "description": "How conversation history is stored and retrieved", "type": "string", "options": ["summary", "structured", "file"]},
    "COMPACTION_MODEL": {"group": "Chat History", "label": "Compaction Model", "description": "LiteLLM model alias for context compaction", "type": "string", "widget": "model"},
    "COMPACTION_MODEL_PROVIDER_ID": {"group": "Chat History", "label": "Compaction Model Provider", "type": "string", "description": "Provider for compaction model", "ui_hidden": True},
    "COMPACTION_INTERVAL": {"group": "Chat History", "label": "Compaction Interval", "description": "Turns between compaction runs", "type": "int", "min": 5, "max": 200},
    "COMPACTION_KEEP_TURNS": {"group": "Chat History", "label": "Keep Turns", "description": "Recent turns kept in context (not compacted)", "type": "int", "min": 1, "max": 50},
    "MEMORY_FLUSH_ENABLED": {"group": "Chat History", "label": "Memory Flush Before Compaction", "description": "Run a dedicated memory flush before compaction — bot saves memories/knowledge/persona while it still sees full context", "type": "bool"},
    "MEMORY_FLUSH_MODEL": {"group": "Chat History", "label": "Memory Flush Model", "description": "Model for memory flush (empty = use bot's model)", "type": "string", "widget": "model"},
    "MEMORY_FLUSH_MODEL_PROVIDER_ID": {"group": "Chat History", "label": "Memory Flush Model Provider", "type": "string", "description": "Provider for memory flush model", "ui_hidden": True},
    "MEMORY_FLUSH_DEFAULT_PROMPT": {"group": "Chat History", "label": "Memory Flush Default Prompt", "description": "Default prompt for the memory flush pass. Tells the bot what to save before context is archived.", "type": "string", "widget": "textarea"},
    "MEMORY_SCHEME_PROMPT": {"group": "Chat History", "label": "Memory Scheme System Prompt (Override)", "description": "Custom override for the workspace-files memory prompt. Leave empty to use the built-in default.", "type": "string", "widget": "textarea", "nullable": True, "ui_hidden": True},
    "MEMORY_SCHEME_FLUSH_PROMPT": {"group": "Chat History", "label": "Memory Scheme Flush Prompt (Override)", "description": "Custom override for the workspace-files flush prompt. Leave empty to use the built-in default.", "type": "string", "widget": "textarea", "nullable": True, "ui_hidden": True},
    "PREVIOUS_SUMMARY_INJECT_CHARS": {"group": "Chat History", "label": "Previous Summary Max Chars", "description": "Max characters of existing summary injected into heartbeat/memory-flush context. Truncates at sentence boundary.", "type": "int", "min": 0, "max": 5000},
    "SECTION_INDEX_COUNT": {"group": "Chat History", "label": "Section Index Count", "description": "Number of recent sections shown in the index (file mode)", "type": "int", "min": 0, "max": 100},
    "SECTION_INDEX_VERBOSITY": {"group": "Chat History", "label": "Section Index Verbosity", "description": "Detail level for section index entries", "type": "string", "options": ["compact", "standard", "detailed"]},
    "HISTORY_WRITE_FILES": {"group": "Chat History", "label": "Write Transcript Files", "description": "Also write transcripts to .history/ files on disk. Transcripts are always stored in the database.", "type": "bool"},
    "SECTION_RETENTION_MODE": {"group": "Chat History", "label": "Section Retention", "description": "How long to keep archived sections", "type": "string", "options": ["forever", "count", "days"]},
    "SECTION_RETENTION_VALUE": {"group": "Chat History", "label": "Retention Value", "description": "Sections to keep (count mode) or days to retain (days mode)", "type": "int", "min": 1, "max": 10000},
    # --- Context Pruning ---
    "CONTEXT_PRUNING_ENABLED": {"group": "Chat History", "label": "Context Pruning", "description": "Trim old tool results from context at the start of each new user turn", "type": "bool"},
    "CONTEXT_PRUNING_MIN_LENGTH": {"group": "Chat History", "label": "Pruning Min Length", "description": "Tool results shorter than this are never pruned (applies to both turn-boundary and in-loop pruning)", "type": "int", "min": 0, "max": 10000},
    "IN_LOOP_PRUNING_ENABLED": {"group": "Chat History", "label": "In-Loop Pruning", "description": "Trim old tool results between iterations within a single agent run. Prevents long tool-call chains from accumulating context. Pruned results stay retrievable via read_conversation_history.", "type": "bool"},
    "IN_LOOP_PRUNING_KEEP_ITERATIONS": {"group": "Chat History", "label": "In-Loop Keep Iterations", "description": "How many of the most recent iterations stay verbatim. 1 = aggressive (only the last round of tool results is kept), 2-3 = more conservative. Older iterations get a retrieval-pointer marker.", "type": "int", "min": 1, "max": 10},
    # --- Embeddings & RAG ---
    "EMBEDDING_MODEL": {"group": "Embeddings & RAG", "label": "Embedding Model", "description": "Model for text embeddings (use local/ prefix for local ONNX models, e.g. local/BAAI/bge-small-en-v1.5)", "type": "string", "widget": "embedding_model"},
    "RAG_TOP_K": {"group": "Embeddings & RAG", "label": "RAG Top-K", "description": "Number of RAG results to return", "type": "int", "min": 1, "max": 50},
    "TOOL_RETRIEVAL_THRESHOLD": {"group": "Embeddings & RAG", "label": "Tool Retrieval Threshold", "description": "Minimum similarity for tool retrieval", "type": "float", "min": 0.0, "max": 1.0},
    "TOOL_RETRIEVAL_TOP_K": {"group": "Embeddings & RAG", "label": "Tool Retrieval Top-K", "description": "Number of tools returned by retrieval", "type": "int", "min": 1, "max": 50},
    "MEMORY_RETRIEVAL_LIMIT": {"group": "Embeddings & RAG", "label": "Memory Retrieval Limit", "description": "Max memory items to retrieve", "type": "int", "min": 1, "max": 50},
    "MEMORY_SIMILARITY_THRESHOLD": {"group": "Embeddings & RAG", "label": "Memory Similarity Threshold", "description": "Minimum similarity for memory retrieval", "type": "float", "min": 0.0, "max": 1.0},
    "KNOWLEDGE_SIMILARITY_THRESHOLD": {"group": "Embeddings & RAG", "label": "Knowledge Similarity Threshold", "description": "Minimum similarity for knowledge retrieval", "type": "float", "min": 0.0, "max": 1.0},
    "KNOWLEDGE_MAX_INJECT_CHARS": {"group": "Embeddings & RAG", "label": "Knowledge Max Inject Chars", "description": "Max chars per knowledge doc injected", "type": "int", "min": 500, "max": 50000},
    "MEMORY_MAX_INJECT_CHARS": {"group": "Embeddings & RAG", "label": "Memory Max Inject Chars", "description": "Max chars per memory item injected", "type": "int", "min": 500, "max": 50000},
    # --- RAG Re-ranking ---
    "RAG_RERANK_ENABLED": {"group": "RAG Re-ranking", "label": "Enabled", "description": "Filter dynamically-retrieved RAG chunks by relevance. Pinned skills/knowledge are never filtered.", "type": "bool"},
    "RAG_RERANK_BACKEND": {"group": "RAG Re-ranking", "label": "Backend", "description": "cross-encoder (recommended): fast local ONNX model, ~120ms, zero API cost. llm: full LLM call, ~2s, API cost per request", "type": "string", "options": ["cross-encoder", "llm"]},
    "RAG_RERANK_MODEL": {"group": "RAG Re-ranking", "label": "LLM Model", "description": "Model for LLM backend only. A small/fast model works well (e.g. gemini-2.0-flash-lite). Empty = compaction model", "type": "string", "widget": "model"},
    "RAG_RERANK_MODEL_PROVIDER_ID": {"group": "RAG Re-ranking", "label": "Rerank Model Provider", "type": "string", "description": "Provider for rerank model", "ui_hidden": True},
    "RAG_RERANK_THRESHOLD_CHARS": {"group": "RAG Re-ranking", "label": "Threshold (chars)", "description": "Only re-rank when total RAG content exceeds this many chars. Default 5000 (~2-3 skill chunks)", "type": "int", "min": 500, "max": 100000},
    "RAG_RERANK_MAX_CHUNKS": {"group": "RAG Re-ranking", "label": "Max Chunks", "description": "Max chunks to keep after re-ranking. 20 is generous; lower to 10-15 for tighter context", "type": "int", "min": 1, "max": 100},
    "RAG_RERANK_MAX_TOKENS": {"group": "RAG Re-ranking", "label": "Max Tokens (LLM)", "description": "Max output tokens for LLM re-ranker response. Only used with LLM backend", "type": "int", "min": 100, "max": 4000},
    "RAG_RERANK_CROSS_ENCODER_MODEL": {"group": "RAG Re-ranking", "label": "Cross-Encoder Model", "description": "ONNX model for cross-encoder backend. Default (ms-marco-MiniLM-L-6-v2) is fast and effective for general use", "type": "string"},
    "RAG_RERANK_SCORE_THRESHOLD": {"group": "RAG Re-ranking", "label": "Score Threshold", "description": "Min relevance probability (0-1) to keep a chunk. 0.01 = keep anything >1%% likely relevant. Raise to 0.05-0.1 for stricter filtering", "type": "float", "min": 0.0, "max": 1.0},
    # --- Hybrid Search ---
    "HYBRID_SEARCH_ENABLED": {"group": "Embeddings & RAG", "label": "Hybrid Search", "description": "Combine BM25 keyword search with vector search via Reciprocal Rank Fusion", "type": "bool"},
    "HYBRID_SEARCH_RRF_K": {"group": "Embeddings & RAG", "label": "RRF K Parameter", "description": "Reciprocal Rank Fusion k: higher values give more weight to top results", "type": "int", "min": 1, "max": 200},
    # --- Contextual Retrieval ---
    "CONTEXTUAL_RETRIEVAL_ENABLED": {"group": "Embeddings & RAG", "label": "Contextual Retrieval", "description": "Generate LLM descriptions per chunk during indexing for better retrieval", "type": "bool"},
    "CONTEXTUAL_RETRIEVAL_MODEL": {"group": "Embeddings & RAG", "label": "Context Gen Model", "description": "Model for context generation (empty = compaction model)", "type": "string", "widget": "model"},
    "CONTEXTUAL_RETRIEVAL_MAX_TOKENS": {"group": "Embeddings & RAG", "label": "Context Gen Max Tokens", "description": "Max tokens for contextual description generation", "type": "int", "min": 50, "max": 500},
    "CONTEXTUAL_RETRIEVAL_BATCH_SIZE": {"group": "Embeddings & RAG", "label": "Context Gen Batch Size", "description": "Concurrent LLM calls during indexing", "type": "int", "min": 1, "max": 20},
    "CONTEXTUAL_RETRIEVAL_PROVIDER_ID": {"group": "Embeddings & RAG", "label": "Context Gen Provider", "description": "Provider for context generation (empty = default)", "type": "string", "nullable": True},
    # --- Prompt Caching ---
    "PROMPT_CACHE_ENABLED": {"group": "Agent", "label": "Prompt Caching", "description": "Add Anthropic cache_control breakpoints for Claude models (reduces cost on repeated context)", "type": "bool"},
    "PROMPT_CACHE_MIN_TOKENS": {"group": "Agent", "label": "Cache Min Tokens", "description": "Min estimated tokens in a system message before applying cache breakpoint", "type": "int", "min": 128, "max": 10000},
    # --- Tool Summarization ---
    "TOOL_RESULT_SUMMARIZE_ENABLED": {"group": "Tool Summarization", "label": "Enabled", "description": "Auto-summarize long tool results", "type": "bool"},
    "TOOL_RESULT_SUMMARIZE_THRESHOLD": {"group": "Tool Summarization", "label": "Threshold (chars)", "description": "Summarize tool results above this character count", "type": "int", "min": 500, "max": 50000},
    "TOOL_RESULT_SUMMARIZE_MODEL": {"group": "Tool Summarization", "label": "Model", "description": "Model for tool result summarization", "type": "string", "widget": "model"},
    "TOOL_RESULT_SUMMARIZE_MODEL_PROVIDER_ID": {"group": "Tool Summarization", "label": "Summarize Model Provider", "type": "string", "description": "Provider for tool result summarize model", "ui_hidden": True},
    "TOOL_RESULT_SUMMARIZE_MAX_TOKENS": {"group": "Tool Summarization", "label": "Max Tokens", "description": "Max tokens for summary output", "type": "int", "min": 50, "max": 2000},
    "TOOL_RESULT_HARD_CAP": {"group": "Tool Summarization", "label": "Hard Cap (chars)", "description": "Maximum chars per tool result in current turn (0 = no cap)", "type": "int", "min": 0, "max": 200000},
    # --- Speech-to-Text ---
    "STT_PROVIDER": {"group": "Speech-to-Text", "label": "STT Provider", "description": "Transcription provider", "type": "string", "options": ["local", "groq", "openai"]},
    "WHISPER_MODEL": {"group": "Speech-to-Text", "label": "Whisper Model", "description": "faster-whisper model name", "type": "string"},
    "WHISPER_DEVICE": {"group": "Speech-to-Text", "label": "Device", "description": "Compute device", "type": "string", "options": ["auto", "cpu", "cuda"]},
    "WHISPER_COMPUTE_TYPE": {"group": "Speech-to-Text", "label": "Compute Type", "description": "Compute precision", "type": "string", "options": ["auto", "int8", "float16", "float32"]},
    "WHISPER_BEAM_SIZE": {"group": "Speech-to-Text", "label": "Beam Size", "description": "Beam search width", "type": "int", "min": 1, "max": 10},
    "WHISPER_LANGUAGE": {"group": "Speech-to-Text", "label": "Language", "description": "Transcription language code", "type": "string"},
    # --- API Rate Limiting ---
    "RATE_LIMIT_ENABLED": {"group": "API Rate Limiting", "label": "Enabled", "description": "Rate-limit incoming requests to the Spindrel API (not LLM provider calls). Uses in-memory token bucket per API key or client IP. Requires server restart to take effect.", "type": "bool"},
    "RATE_LIMIT_DEFAULT": {"group": "API Rate Limiting", "label": "Default Limit", "description": "Rate limit for all Spindrel API endpoints (e.g. 100/minute, 10/second, 5000/hour)", "type": "string"},
    "RATE_LIMIT_CHAT": {"group": "API Rate Limiting", "label": "Chat Limit", "description": "Stricter rate limit for /chat and /chat/stream endpoints (e.g. 30/minute)", "type": "string"},
    # --- Security ---
    "SECRET_REDACTION_ENABLED": {"group": "Security", "label": "Secret Redaction", "description": "Redact known secrets from tool results and LLM output", "type": "bool"},
    # --- Tool Policies ---
    "TOOL_POLICY_ENABLED": {"group": "Tool Policies", "label": "Enabled", "description": "Master switch for the tool policy engine", "type": "bool"},
    "TOOL_POLICY_DEFAULT_ACTION": {"group": "Tool Policies", "label": "Default Action", "description": "Action when no rule matches: allow, deny, or require_approval", "type": "string", "options": ["allow", "deny", "require_approval"]},
    "TOOL_POLICY_TIER_GATING": {"group": "Tool Policies", "label": "Tier-Based Gating", "description": "Auto-require approval for exec_capable and control_plane tools when no explicit rule matches", "type": "bool"},
    # --- Memory Hygiene ---
    "MEMORY_HYGIENE_ENABLED": {"group": "Memory Hygiene", "label": "Enabled", "description": "Enable periodic memory hygiene jobs for workspace-files bots. Bots review cross-channel memory, promote stable facts, prune stale entries, and consolidate skills.", "type": "bool"},
    "MEMORY_HYGIENE_INTERVAL_HOURS": {"group": "Memory Hygiene", "label": "Interval (hours)", "description": "Hours between hygiene runs (per-bot override available)", "type": "int", "min": 1, "max": 720},
    "MEMORY_HYGIENE_PROMPT": {"group": "Memory Hygiene", "label": "Hygiene Prompt", "description": "Custom prompt for hygiene runs. Leave empty to use the built-in default shown below.", "type": "string", "widget": "textarea", "nullable": True, "builtin_default_key": "DEFAULT_MEMORY_HYGIENE_PROMPT"},
    "MEMORY_HYGIENE_ONLY_IF_ACTIVE": {"group": "Memory Hygiene", "label": "Only If Active", "description": "Skip hygiene when no user messages have landed in any of a bot's channels (primary or member) since the last run. Bot-to-bot delegation, heartbeats, and assistant replies do NOT count — a bot whose channels only see bot traffic will never dream unless this is off.", "type": "bool"},
    "MEMORY_HYGIENE_MODEL": {"group": "Memory Hygiene", "label": "Model", "description": "Default model for hygiene runs (empty = use each bot's default model). Per-bot override available.", "type": "string", "widget": "model", "nullable": True},
    "MEMORY_HYGIENE_MODEL_PROVIDER_ID": {"group": "Memory Hygiene", "label": "Hygiene Model Provider", "type": "string", "description": "Provider for memory hygiene model", "ui_hidden": True},
    "MEMORY_HYGIENE_TARGET_HOUR": {"group": "Memory Hygiene", "label": "Target Start Hour", "description": "Hour of day (0-23, local time) when hygiene runs should cluster. Bots stagger within ~60 min of this hour. Set -1 to disable (runs spread across the full interval).", "type": "int", "min": -1, "max": 23},
    "MEMORY_MD_NUDGE_THRESHOLD": {"group": "Memory Hygiene", "label": "Memory Size Nudge (lines)", "description": "When MEMORY.md exceeds this many lines, the bot gets a system message each turn reminding it to prune and consolidate. Set to 0 to disable.", "type": "int", "min": 0, "max": 500},
    # --- Skill Review (separate dreaming job for skill curation) ---
    "SKILL_REVIEW_ENABLED": {"group": "Memory Hygiene", "label": "Skill Review Enabled", "description": "Enable periodic skill review jobs. Cross-channel reflection, skill pruning, auto-inject audit. Runs separately from memory maintenance.", "type": "bool"},
    "SKILL_REVIEW_INTERVAL_HOURS": {"group": "Memory Hygiene", "label": "Skill Review Interval (hours)", "description": "Hours between skill review runs (default: 72). Skill rot is slower than memory drift.", "type": "int", "min": 1, "max": 720},
    "SKILL_REVIEW_PROMPT": {"group": "Memory Hygiene", "label": "Skill Review Prompt", "description": "Custom prompt for skill review runs. Leave empty to use the built-in default.", "type": "string", "widget": "textarea", "nullable": True, "builtin_default_key": "DEFAULT_SKILL_REVIEW_PROMPT"},
    "SKILL_REVIEW_ONLY_IF_ACTIVE": {"group": "Memory Hygiene", "label": "Skill Review Only If Active", "description": "Skip skill review when no user messages since last run. Recommended: off (skill rot happens regardless of activity).", "type": "bool"},
    "SKILL_REVIEW_MODEL": {"group": "Memory Hygiene", "label": "Skill Review Model", "description": "Default model for skill review runs (empty = use bot's model). Should be a strong reasoning model.", "type": "string", "widget": "model", "nullable": True},
    "SKILL_REVIEW_MODEL_PROVIDER_ID": {"group": "Memory Hygiene", "label": "Skill Review Model Provider", "type": "string", "description": "Provider for skill review model", "ui_hidden": True},
    "SKILL_REVIEW_TARGET_HOUR": {"group": "Memory Hygiene", "label": "Skill Review Target Hour", "description": "Hour of day (0-23, local time) when skill review runs should cluster. Set -1 to disable.", "type": "int", "min": -1, "max": 23},
    # --- Heartbeat ---
    "HEARTBEAT_QUIET_HOURS": {"group": "Heartbeat", "label": "Quiet Hours", "description": "Time window where heartbeats slow (e.g. 23:00-07:00)", "type": "string"},
    "HEARTBEAT_QUIET_INTERVAL_MINUTES": {"group": "Heartbeat", "label": "Quiet Interval (min)", "description": "Interval during quiet hours (0 = disabled)", "type": "int", "min": 0, "max": 1440},
    "HEARTBEAT_ACTIVE_INTERVAL_MINUTES": {"group": "Heartbeat", "label": "Active Interval (min)", "description": "Default active heartbeat interval", "type": "int", "min": 1, "max": 1440},
    "HEARTBEAT_DEFAULT_PROMPT": {"group": "Heartbeat", "label": "Default Prompt", "description": "Fallback prompt used when a channel heartbeat has no prompt, template, or workspace file configured.", "type": "string", "widget": "textarea"},
    "HEARTBEAT_PREVIOUS_CONCLUSION_CHARS": {"group": "Heartbeat", "label": "Previous Conclusion Max Chars", "description": "Max characters of previous heartbeat conclusion injected into the next heartbeat. Truncates at sentence boundary.", "type": "int", "min": 0, "max": 5000},
    "HEARTBEAT_REPETITION_DETECTION": {"group": "Heartbeat", "label": "Repetition Detection", "description": "Detect and warn when heartbeat outputs are repetitive", "type": "bool"},
    "HEARTBEAT_REPETITION_THRESHOLD": {"group": "Heartbeat", "label": "Repetition Threshold", "description": "Similarity ratio (0-1) above which consecutive outputs are considered repetitive", "type": "float", "min": 0.0, "max": 1.0},
    "HEARTBEAT_REPETITION_WARNING": {"group": "Heartbeat", "label": "Repetition Warning", "description": "Warning text injected when repetition is detected", "type": "string", "widget": "textarea"},
    # --- Attachments ---
    "ATTACHMENT_SUMMARY_ENABLED": {"group": "Attachments", "label": "Summary Enabled", "description": "Auto-summarize attachments", "type": "bool"},
    "ATTACHMENT_SUMMARY_MODEL": {"group": "Attachments", "label": "Summary Model", "description": "Model for attachment summarization", "type": "string", "widget": "model"},
    "ATTACHMENT_SUMMARY_MODEL_PROVIDER_ID": {"group": "Attachments", "label": "Summary Model Provider", "type": "string", "description": "Provider for attachment summary model", "ui_hidden": True},
    "ATTACHMENT_VISION_CONCURRENCY": {"group": "Attachments", "label": "Vision Concurrency", "description": "Max concurrent vision API calls", "type": "int", "min": 1, "max": 20},
    "ATTACHMENT_TEXT_MAX_CHARS": {"group": "Attachments", "label": "Text Max Chars", "description": "Max chars for text summarization", "type": "int", "min": 1000, "max": 200000},
    "ATTACHMENT_RETENTION_DAYS": {"group": "Attachments", "label": "Retention Days", "description": "Days to keep attachments (empty = forever)", "type": "int", "min": 1, "max": 3650, "nullable": True},
    "ATTACHMENT_MAX_SIZE_BYTES": {"group": "Attachments", "label": "Max Size (bytes)", "description": "Max attachment size (empty = no limit)", "type": "int", "min": 1024, "max": 1073741824, "nullable": True},
    # --- Data Retention ---
    "DATA_RETENTION_DAYS": {"group": "Data Retention", "label": "Retention Days", "description": "Days to keep operational data (trace events, tool calls, heartbeat runs, etc.). Empty = keep forever.", "type": "int", "min": 1, "max": 3650, "nullable": True},
    "DATA_RETENTION_SWEEP_INTERVAL_S": {"group": "Data Retention", "label": "Sweep Interval (seconds)", "description": "Seconds between automatic retention sweeps", "type": "int", "min": 3600, "max": 604800},
    # --- Docker Stacks ---
    "DOCKER_STACKS_ENABLED": {"group": "Docker Stacks", "label": "Enabled", "description": "Allow agents to create and manage Docker Compose stacks (databases, caches, services)", "type": "bool"},
    "DOCKER_STACK_MAX_PER_BOT": {"group": "Docker Stacks", "label": "Max Stacks Per Bot", "description": "Maximum number of stacks a single bot can create", "type": "int", "min": 1, "max": 50},
    "DOCKER_STACK_DEFAULT_CPUS": {"group": "Docker Stacks", "label": "Default CPUs", "description": "CPU limit injected into every stack service", "type": "float", "min": 0.1, "max": 16.0},
    "DOCKER_STACK_DEFAULT_MEMORY": {"group": "Docker Stacks", "label": "Default Memory", "description": "Memory limit injected into every stack service (e.g. 512m, 1g)", "type": "string"},
    "DOCKER_STACK_COMPOSE_TIMEOUT": {"group": "Docker Stacks", "label": "Compose Timeout", "description": "Timeout in seconds for docker compose operations", "type": "int", "min": 30, "max": 600},
    "DOCKER_STACK_EXEC_TIMEOUT": {"group": "Docker Stacks", "label": "Exec Timeout", "description": "Timeout in seconds for exec commands in stack containers", "type": "int", "min": 5, "max": 300},
    "DOCKER_STACK_LOG_TAIL_MAX": {"group": "Docker Stacks", "label": "Log Tail Max", "description": "Maximum number of log lines to retrieve", "type": "int", "min": 10, "max": 10000},
    # --- Image Generation ---
    "IMAGE_GENERATION_MODEL": {"group": "Image Generation", "label": "Model", "description": "Model for image generation", "type": "string", "widget": "model"},
    "IMAGE_GENERATION_PROVIDER_ID": {"group": "Image Generation", "label": "Image Gen Provider", "type": "string", "description": "Provider for image generation model", "ui_hidden": True},
    # --- Prompt Generation ---
    "PROMPT_GENERATION_MODEL": {"group": "Prompt Generation", "label": "Model", "description": "Model used for the Generate Prompt feature in admin UI (empty = default LiteLLM model)", "type": "string", "widget": "model"},
    "PROMPT_GENERATION_MODEL_PROVIDER_ID": {"group": "Prompt Generation", "label": "Prompt Gen Provider", "type": "string", "description": "Provider for prompt generation model", "ui_hidden": True},
    "PROMPT_GENERATION_TEMPERATURE": {"group": "Prompt Generation", "label": "Temperature", "description": "LLM temperature for prompt generation (0.0-1.0)", "type": "float", "min": 0.0, "max": 1.0},
}

# Group ordering for consistent display
GROUP_ORDER = [
    "System", "Paths", "General", "Security", "API Rate Limiting", "Agent", "Chat History",
    "Embeddings & RAG", "RAG Re-ranking", "Tool Summarization",
    "Tool Policies", "Speech-to-Text", "Memory Hygiene", "Heartbeat", "Docker Stacks", "Attachments", "Data Retention", "Image Generation", "Prompt Generation",
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
        if schema.get("ui_hidden"):
            entry["ui_hidden"] = True
        if schema.get("builtin_default_key"):
            from app import config as _cfg
            entry["builtin_default"] = getattr(_cfg, schema["builtin_default_key"], None)

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


async def _recalc_hygiene_schedules(db: AsyncSession) -> None:
    """Recalculate next_hygiene_run_at for all bots using global target_hour.

    Called when MEMORY_HYGIENE_TARGET_HOUR or MEMORY_HYGIENE_INTERVAL_HOURS
    changes globally. Only affects bots that don't have a bot-level override.
    """
    from app.db.models import Bot as BotRow
    from app.services.memory_hygiene import _compute_next_run, resolve_enabled

    now = datetime.now(timezone.utc)
    rows = (await db.execute(select(BotRow).where(BotRow.memory_scheme == "workspace-files"))).scalars().all()
    updated = 0
    for bot in rows:
        if not resolve_enabled(bot):
            continue
        # Skip bots with bot-level target_hour override (they're unaffected)
        if bot.memory_hygiene_target_hour is not None:
            continue
        bot.next_hygiene_run_at = _compute_next_run(bot, now, after_run=False)
        updated += 1
    if updated:
        await db.commit()
        logger.info("Recalculated hygiene schedule for %d bots after global setting change", updated)


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

    # Recalculate hygiene schedules when global target_hour or interval changes
    _hygiene_schedule_keys = {"MEMORY_HYGIENE_TARGET_HOUR", "MEMORY_HYGIENE_INTERVAL_HOURS"}
    if _hygiene_schedule_keys & set(applied):
        try:
            await _recalc_hygiene_schedules(db)
        except Exception:
            logger.exception("Failed to recalculate hygiene schedules after global setting change")

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
