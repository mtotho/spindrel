"""RAG re-ranking: LLM-based cross-source relevance filtering.

After context assembly injects RAG chunks from multiple sources (skills, memory,
knowledge, filesystem), this module evaluates all chunks against the user query
and keeps only the most relevant ones.  Tagged content (explicitly @-mentioned)
and non-RAG system messages are never re-ranked.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Chunk identification: RAG prefixes we recognise and re-rank
# ---------------------------------------------------------------------------

_RAG_PREFIXES: list[tuple[str, str]] = [
    ("Pinned skill context:\n\n", "skill_pinned"),
    ("Relevant skill context:\n\n", "skill_rag"),
    ("Relevant memories from past conversations", "memory"),
    ("Pinned knowledge (always available):\n\n", "pinned_knowledge"),
    ("Relevant knowledge:\n\n", "knowledge"),
    ("Relevant files from workspace", "filesystem"),
    ("Relevant code/files", "filesystem"),
    ("Workspace pinned skills:\n\n", "ws_skill_pinned"),
    ("Relevant workspace skills:\n\n", "ws_skill_rag"),
    ("Relevant conversation history sections:\n\n", "conversation_sections"),
]

# Prefixes that are NEVER re-ranked (user explicitly requested, or structural)
_EXCLUDED_PREFIXES: list[str] = [
    "Tagged skill context",
    "Tagged knowledge",
]

CHUNK_SEPARATOR = "\n\n---\n\n"


@dataclass
class RerankResult:
    original_chunks: int = 0
    kept_chunks: int = 0
    original_chars: int = 0
    kept_chars: int = 0
    removed_message_indices: list[int] = field(default_factory=list)


@dataclass
class _RagMessage:
    """Bookkeeping for a single RAG system message."""
    index: int           # position in the messages list
    source: str          # e.g. "memory", "skill_rag", …
    chunks: list[str]    # individual chunks split from the message content
    prefix: str          # the original prefix before chunks


def _identify_rag_messages(messages: list[dict]) -> list[_RagMessage]:
    """Walk messages and return bookkeeping for RAG-sourced system messages."""
    result: list[_RagMessage] = []
    for idx, msg in enumerate(messages):
        if msg.get("role") != "system":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue

        # Skip explicitly-requested content
        if any(content.startswith(ep) for ep in _EXCLUDED_PREFIXES):
            continue

        for prefix, source in _RAG_PREFIXES:
            if content.startswith(prefix):
                # For memory messages the prefix is the whole first line
                if source == "memory":
                    # The first line is a header; chunks follow after first \n\n
                    first_break = content.find("\n\n")
                    if first_break == -1:
                        break
                    actual_prefix = content[:first_break + 2]
                    body = content[first_break + 2:]
                else:
                    actual_prefix = prefix
                    body = content[len(prefix):]

                chunks = body.split(CHUNK_SEPARATOR) if body.strip() else []
                chunks = [c for c in chunks if c.strip()]
                if chunks:
                    result.append(_RagMessage(
                        index=idx, source=source,
                        chunks=chunks, prefix=actual_prefix,
                    ))
                break
    return result


def _build_rerank_prompt(
    rag_messages: list[_RagMessage],
    user_message: str,
) -> list[dict]:
    """Build the messages payload for the re-ranking LLM call."""
    system = (
        "You are a relevance judge. You will receive numbered context chunks from "
        "various sources (skills, memories, knowledge docs, files) and a user query. "
        "Your job is to decide which chunks are relevant to answering the query.\n\n"
        "Respond with ONLY a JSON object: {\"keep\": [list of chunk numbers to keep]}. "
        "Include chunks that are directly relevant, provide useful background, or contain "
        "information the assistant would need. Exclude chunks that are clearly off-topic "
        "or redundant.\n\n"
        "IMPORTANT: Respond with valid JSON only, no markdown fences or extra text."
    )

    lines: list[str] = []
    global_idx = 0
    for rm in rag_messages:
        for chunk in rm.chunks:
            preview = chunk[:500] if len(chunk) > 500 else chunk
            lines.append(f"[{global_idx}] (source: {rm.source})\n{preview}")
            global_idx += 1

    user_content = (
        f"User query: {user_message}\n\n"
        f"Context chunks ({global_idx} total):\n\n"
        + "\n\n".join(lines)
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]


def _parse_keep_indices(text: str, total_chunks: int) -> list[int] | None:
    """Parse the LLM response to extract kept chunk indices."""
    # Try to find JSON object in response
    text = text.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object within text
        match = re.search(r"\{[^}]+\}", text)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                return None
        else:
            return None

    keep = data.get("keep")
    if not isinstance(keep, list):
        return None

    # Validate indices
    valid = [int(i) for i in keep if isinstance(i, (int, float)) and 0 <= int(i) < total_chunks]
    return valid


async def rerank_rag_context(
    messages: list[dict],
    user_message: str,
    provider_id: str | None = None,
) -> RerankResult | None:
    """Re-rank RAG context chunks using an LLM.

    Modifies ``messages`` in-place: removes or trims RAG system messages
    whose chunks were not selected by the re-ranker.

    Returns ``None`` when re-ranking is skipped (disabled, below threshold, or error).
    Returns a ``RerankResult`` on success with before/after stats.
    """
    if not settings.RAG_RERANK_ENABLED:
        return None

    # Identify RAG messages
    rag_msgs = _identify_rag_messages(messages)
    if not rag_msgs:
        return None

    # Count total chunks and chars
    all_chunks: list[tuple[_RagMessage, int, str]] = []  # (parent_msg, chunk_local_idx, text)
    total_chars = 0
    for rm in rag_msgs:
        for ci, chunk in enumerate(rm.chunks):
            all_chunks.append((rm, ci, chunk))
            total_chars += len(chunk)

    if total_chars < settings.RAG_RERANK_THRESHOLD_CHARS:
        return None

    # Build prompt and call LLM
    model = settings.RAG_RERANK_MODEL or settings.COMPACTION_MODEL
    rerank_messages = _build_rerank_prompt(rag_msgs, user_message)

    try:
        from app.services.providers import get_llm_client
        client = get_llm_client(provider_id)
        response = await client.chat.completions.create(
            model=model,
            messages=rerank_messages,
            temperature=0.0,
            max_tokens=settings.RAG_RERANK_MAX_TOKENS,
        )
        result_text = response.choices[0].message.content or ""
    except Exception:
        logger.warning("RAG re-ranking LLM call failed, skipping", exc_info=True)
        return None

    # Parse response
    keep_indices = _parse_keep_indices(result_text, len(all_chunks))
    if keep_indices is None:
        logger.warning("RAG re-ranking: failed to parse LLM response: %s", result_text[:200])
        return None

    # Cap at max chunks
    keep_indices = keep_indices[:settings.RAG_RERANK_MAX_CHUNKS]
    keep_set = set(keep_indices)

    # Build a mapping: for each _RagMessage, which local chunk indices survive
    surviving: dict[int, list[int]] = {}  # msg_index -> list of local chunk indices
    global_idx = 0
    for rm in rag_msgs:
        local_keep: list[int] = []
        for ci in range(len(rm.chunks)):
            if global_idx in keep_set:
                local_keep.append(ci)
            global_idx += 1
        surviving[rm.index] = local_keep

    # Rebuild messages in-place
    kept_chars = 0
    kept_chunks = 0
    indices_to_remove: list[int] = []

    for rm in rag_msgs:
        local_keep = surviving[rm.index]
        if not local_keep:
            # Remove entire message
            indices_to_remove.append(rm.index)
        else:
            # Rebuild with only kept chunks
            kept = [rm.chunks[i] for i in local_keep]
            kept_chars += sum(len(c) for c in kept)
            kept_chunks += len(kept)
            messages[rm.index]["content"] = rm.prefix + CHUNK_SEPARATOR.join(kept)

    # Remove empty messages (in reverse order to preserve indices)
    for idx in sorted(indices_to_remove, reverse=True):
        messages.pop(idx)

    return RerankResult(
        original_chunks=len(all_chunks),
        kept_chunks=kept_chunks,
        original_chars=total_chars,
        kept_chars=kept_chars,
        removed_message_indices=indices_to_remove,
    )
