"""Shared embedding helpers.

Every call passes ``dimensions=settings.EMBEDDING_DIMENSIONS`` so that models
supporting Matryoshka truncation (e.g. text-embedding-3-large) are automatically
truncated to match the DB vector column width.  No migration needed.
"""
from __future__ import annotations

import logging

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

_client = AsyncOpenAI(
    base_url=settings.LITELLM_BASE_URL,
    api_key=settings.LITELLM_API_KEY,
    timeout=120.0,
    max_retries=0,
)

# text-embedding-3-small/large have an 8191-token limit.
# ~4 chars per token → 30K chars is a safe ceiling.
_MAX_EMBED_CHARS = 30_000


def _truncate(text: str) -> str:
    if len(text) <= _MAX_EMBED_CHARS:
        return text
    logger.warning("Truncating embedding input from %d to %d chars", len(text), _MAX_EMBED_CHARS)
    return text[:_MAX_EMBED_CHARS]


async def embed_text(text: str, *, model: str | None = None) -> list[float]:
    """Embed a single text string, returning the embedding vector."""
    response = await _client.embeddings.create(
        model=model or settings.EMBEDDING_MODEL,
        input=[_truncate(text)],
        dimensions=settings.EMBEDDING_DIMENSIONS,
    )
    return response.data[0].embedding


async def embed_batch(texts: list[str], *, model: str | None = None) -> list[list[float]]:
    """Embed a batch of texts, returning a list of embedding vectors."""
    response = await _client.embeddings.create(
        model=model or settings.EMBEDDING_MODEL,
        input=[_truncate(t) for t in texts],
        dimensions=settings.EMBEDDING_DIMENSIONS,
    )
    return [item.embedding for item in response.data]
