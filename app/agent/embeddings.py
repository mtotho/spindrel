"""Shared embedding helpers.

Every call passes ``dimensions=settings.EMBEDDING_DIMENSIONS`` so that models
supporting Matryoshka truncation (e.g. text-embedding-3-large) are automatically
truncated to match the DB vector column width.  No migration needed.

Local models (prefixed ``local/``) are routed to fastembed (ONNX) via
``app.agent.local_embeddings``.  Their native vectors are zero-padded to
``EMBEDDING_DIMENSIONS`` — mathematically lossless for cosine similarity
between same-model vectors, so no DB schema change is needed.

A per-request cache (via contextvars) deduplicates identical embed_text calls
within a single request lifecycle — typically saving 5+ redundant API calls per
request since skills, memory, knowledge, and tool retrieval all embed the same
user query.
"""
from __future__ import annotations

import asyncio
import logging
from contextvars import ContextVar

from openai import AsyncOpenAI

from app.agent.local_embeddings import is_local_model, embed_local_sync
from app.config import settings

logger = logging.getLogger(__name__)

_client = AsyncOpenAI(
    base_url=settings.LLM_BASE_URL,
    api_key=settings.LLM_API_KEY,
    timeout=120.0,
    max_retries=0,
)

# text-embedding-3-small/large have an 8191-token limit.
# Code-heavy content can be ~2 chars/token, so use a conservative ceiling.
_MAX_EMBED_CHARS = 16_000

# Per-request embedding cache.  Cleared automatically when the contextvar goes
# out of scope (end of request).  Keyed by (model, truncated_text).
_embed_cache: ContextVar[dict[tuple[str, str], list[float]]] = ContextVar("_embed_cache")


def clear_embed_cache() -> None:
    """Reset the per-request embedding cache (call at request start)."""
    _embed_cache.set({})


def _get_cache() -> dict[tuple[str, str], list[float]]:
    try:
        return _embed_cache.get()
    except LookupError:
        cache: dict[tuple[str, str], list[float]] = {}
        _embed_cache.set(cache)
        return cache


def _truncate(text: str) -> str:
    if len(text) <= _MAX_EMBED_CHARS:
        return text
    logger.warning("Truncating embedding input from %d to %d chars", len(text), _MAX_EMBED_CHARS)
    return text[:_MAX_EMBED_CHARS]


def _zero_pad(vector: list[float], target_dims: int) -> list[float]:
    """Pad a shorter vector with zeros to reach *target_dims*.

    This is mathematically lossless for cosine similarity between vectors from
    the same model — the extra zero dimensions don't affect the angle.
    """
    diff = target_dims - len(vector)
    if diff <= 0:
        return vector
    return vector + [0.0] * diff


async def _embed_local(texts: list[str], model: str) -> list[list[float]]:
    """Run fastembed in a thread executor and zero-pad results."""
    loop = asyncio.get_running_loop()
    vectors = await loop.run_in_executor(
        None, lambda: embed_local_sync(texts, model=model)
    )
    target = settings.EMBEDDING_DIMENSIONS
    return [_zero_pad(v, target) for v in vectors]


async def embed_text(text: str, *, model: str | None = None) -> list[float]:
    """Embed a single text string, returning the embedding vector.

    Results are cached per-request — identical (model, text) pairs return the
    same vector without a second API call.
    """
    effective_model = model or settings.EMBEDDING_MODEL
    truncated = _truncate(text)
    cache_key = (effective_model, truncated)
    cache = _get_cache()

    cached = cache.get(cache_key)
    if cached is not None:
        logger.debug("Embedding cache hit for %d-char input (model=%s)", len(truncated), effective_model)
        return cached

    if is_local_model(effective_model):
        vectors = await _embed_local([truncated], effective_model)
        vector = vectors[0]
    else:
        response = await _client.embeddings.create(
            model=effective_model,
            input=[truncated],
            dimensions=settings.EMBEDDING_DIMENSIONS,
        )
        vector = response.data[0].embedding

    cache[cache_key] = vector
    return vector


async def embed_batch(texts: list[str], *, model: str | None = None) -> list[list[float]]:
    """Embed a batch of texts, returning a list of embedding vectors."""
    effective_model = model or settings.EMBEDDING_MODEL

    if is_local_model(effective_model):
        return await _embed_local([_truncate(t) for t in texts], effective_model)

    response = await _client.embeddings.create(
        model=effective_model,
        input=[_truncate(t) for t in texts],
        dimensions=settings.EMBEDDING_DIMENSIONS,
    )
    return [item.embedding for item in response.data]
