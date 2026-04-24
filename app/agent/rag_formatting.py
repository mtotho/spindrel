"""Shared RAG message formatting constants.

These prefixes are consumed by both context assembly and the reranker. Keep
them stable so injected retrieval blocks and downstream filtering agree on
which system messages are actually RAG context.
"""

CHUNK_SEPARATOR = "\n\n---\n\n"

MEMORY_RAG_PREFIX = "Relevant memories from past conversations"
LEGACY_WORKSPACE_RAG_PREFIX = "Relevant files from workspace"
LEGACY_CODE_RAG_PREFIX = "Relevant code/files"
CONVERSATION_SECTIONS_RAG_PREFIX = "Relevant conversation history sections:\n\n"
GENERIC_KNOWLEDGE_RAG_PREFIX = "Relevant knowledge"
CHANNEL_KNOWLEDGE_BASE_RAG_PREFIX = "Relevant excerpts from the channel knowledge base"
CHANNEL_INDEX_SEGMENTS_RAG_PREFIX = (
    "Relevant excerpts from the channel knowledge base and indexed directories"
)
WORKSPACE_RAG_PREFIX = "Relevant workspace file excerpts"
LEGACY_INDEXED_DIRECTORIES_RAG_PREFIX = "Relevant file excerpts from indexed directories"
BOT_KNOWLEDGE_BASE_RAG_PREFIX = "Relevant excerpts from this bot's knowledge base"

PINNED_SKILL_CONTEXT_PREFIX = "Pinned skill context"
PINNED_KNOWLEDGE_CONTEXT_PREFIX = "Pinned knowledge"
TAGGED_SKILL_CONTEXT_PREFIX = "Tagged skill context"
TAGGED_KNOWLEDGE_CONTEXT_PREFIX = "Tagged knowledge"
MEMORY_BOOTSTRAP_PREFIX = "Your persistent memory ("
MEMORY_TODAY_LOG_PREFIX = "Today's daily log ("
MEMORY_YESTERDAY_LOG_PREFIX = "Yesterday's daily log ("
MEMORY_REFERENCE_INDEX_PREFIX = "Reference documents in "

RERANKABLE_RAG_PREFIXES: list[tuple[str, str]] = [
    (MEMORY_RAG_PREFIX, "memory"),
    (LEGACY_WORKSPACE_RAG_PREFIX, "filesystem"),
    (LEGACY_CODE_RAG_PREFIX, "filesystem"),
    (CONVERSATION_SECTIONS_RAG_PREFIX, "conversation_sections"),
    (GENERIC_KNOWLEDGE_RAG_PREFIX, "knowledge"),
    (CHANNEL_KNOWLEDGE_BASE_RAG_PREFIX, "knowledge"),
    (CHANNEL_INDEX_SEGMENTS_RAG_PREFIX, "knowledge"),
    (WORKSPACE_RAG_PREFIX, "filesystem"),
    (LEGACY_INDEXED_DIRECTORIES_RAG_PREFIX, "filesystem"),
    (BOT_KNOWLEDGE_BASE_RAG_PREFIX, "knowledge"),
]

NON_RERANKABLE_SYSTEM_PREFIXES: list[str] = [
    PINNED_SKILL_CONTEXT_PREFIX,
    PINNED_KNOWLEDGE_CONTEXT_PREFIX,
    TAGGED_SKILL_CONTEXT_PREFIX,
    TAGGED_KNOWLEDGE_CONTEXT_PREFIX,
    MEMORY_BOOTSTRAP_PREFIX,
    MEMORY_TODAY_LOG_PREFIX,
    MEMORY_YESTERDAY_LOG_PREFIX,
    MEMORY_REFERENCE_INDEX_PREFIX,
]
