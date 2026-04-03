"""Contextual retrieval — LLM-generated descriptions for better RAG.

Before embedding a chunk, generates a 1-2 sentence semantic description that
captures the chunk's topic, role, and key entities within the broader document.
This description is prepended to the embedding text, dramatically improving
retrieval recall (~35-67% fewer failures per Anthropic's research).

Feature is opt-in via ``CONTEXTUAL_RETRIEVAL_ENABLED`` (default: False).
"""

import asyncio
import collections
import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# In-memory LRU cache: (content_hash, chunk_index) → description string
# Bounded at 10,000 entries (~100 documents × 100 chunks) to prevent unbounded growth.
_MAX_CACHE_SIZE = 10_000
_context_cache: collections.OrderedDict[tuple[str, int], str] = collections.OrderedDict()

_PROMPT_TEMPLATE = """\
<document>
{document_text}
</document>

Here is a chunk from that document:

<chunk>
{chunk_text}
</chunk>

Give a short (1-2 sentence) description of this chunk that situates it within the overall document. \
Start with "This chunk..." and describe its topic, role in the document, and any key entities or concepts. \
Be specific and concrete — mention names, terms, and relationships rather than vague summaries."""

# Maximum chars of the source document to include in the prompt (keeps cost low)
_DOC_CONTEXT_CHARS = 4000


async def generate_chunk_context(
    chunk_text: str,
    document_text: str,
    document_title: str,
    chunk_index: int,
    content_hash: str,
) -> str | None:
    """Generate a contextual description for a single chunk.

    Returns the description string, or None on failure (graceful degradation).
    Uses in-memory cache keyed by (content_hash, chunk_index).
    """
    if not settings.CONTEXTUAL_RETRIEVAL_ENABLED:
        return None

    cache_key = (content_hash, chunk_index)
    if cache_key in _context_cache:
        _context_cache.move_to_end(cache_key)
        return _context_cache[cache_key]

    model = settings.CONTEXTUAL_RETRIEVAL_MODEL or settings.COMPACTION_MODEL
    if not model:
        logger.debug("Contextual retrieval: no model configured (CONTEXTUAL_RETRIEVAL_MODEL and COMPACTION_MODEL both empty)")
        return None

    # Truncate document to keep prompt cheap
    doc_text = document_text[:_DOC_CONTEXT_CHARS]
    if len(document_text) > _DOC_CONTEXT_CHARS:
        doc_text += f"\n\n[... {len(document_text) - _DOC_CONTEXT_CHARS:,} chars truncated ...]"

    prompt = _PROMPT_TEMPLATE.format(document_text=doc_text, chunk_text=chunk_text)

    try:
        from app.services.providers import get_llm_client
        provider_id = settings.CONTEXTUAL_RETRIEVAL_PROVIDER_ID or None
        client = get_llm_client(provider_id)
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=settings.CONTEXTUAL_RETRIEVAL_MAX_TOKENS,
            temperature=0.0,
        )
        content = response.choices[0].message.content if response.choices else None
        description = content.strip() if content else None
        if description:
            _context_cache[cache_key] = description
            # Evict oldest entries if cache is over limit
            while len(_context_cache) > _MAX_CACHE_SIZE:
                _context_cache.popitem(last=False)
            return description
    except Exception:
        logger.debug("Contextual retrieval failed for chunk %d of '%s'", chunk_index, document_title, exc_info=True)

    return None


async def generate_batch_contexts(
    chunks: list[dict[str, Any]],
    document_text: str,
    document_title: str,
    content_hash: str,
) -> list[str | None]:
    """Generate contextual descriptions for a batch of chunks with bounded concurrency.

    Each chunk dict must have 'text' and 'index' keys.
    Returns a list parallel to chunks with description or None per chunk.
    """
    if not settings.CONTEXTUAL_RETRIEVAL_ENABLED:
        return [None] * len(chunks)

    sem = asyncio.Semaphore(settings.CONTEXTUAL_RETRIEVAL_BATCH_SIZE)

    async def _gen(chunk: dict) -> str | None:
        async with sem:
            return await generate_chunk_context(
                chunk["text"],
                document_text,
                document_title,
                chunk["index"],
                content_hash,
            )

    return await asyncio.gather(*[_gen(c) for c in chunks])


def build_embed_text(
    content: str,
    context_prefix: str | None = None,
    contextual_description: str | None = None,
    source_label: str | None = None,
) -> str:
    """Compose the final text that gets embedded.

    Layering order (each prepended if present):
    1. context_prefix — structural hierarchy (e.g. "# Doc > ## Section")
    2. contextual_description — LLM-generated semantic description
    3. content — the actual chunk text

    Falls back to source_label if no context_prefix is available.
    """
    parts = []
    if context_prefix:
        parts.append(context_prefix)
    elif source_label:
        parts.append(source_label)
    if contextual_description:
        parts.append(contextual_description)
    parts.append(content)
    return "\n\n".join(parts)


def warm_cache_from_metadata(rows: list[tuple[str, int, str | None]]) -> int:
    """Pre-populate cache from existing metadata_.contextual_description values.

    Takes list of (content_hash, chunk_index, description) tuples.
    Respects _MAX_CACHE_SIZE — stops loading once the limit is reached.
    Returns number of entries loaded.
    """
    loaded = 0
    for content_hash, chunk_index, description in rows:
        if description:
            if len(_context_cache) >= _MAX_CACHE_SIZE:
                break
            _context_cache[(content_hash, chunk_index)] = description
            loaded += 1
    return loaded


def get_effective_chunking_version(base_version: str) -> str:
    """Return the effective chunking version, including contextual retrieval marker."""
    if settings.CONTEXTUAL_RETRIEVAL_ENABLED:
        return f"{base_version}+cr"
    return base_version
