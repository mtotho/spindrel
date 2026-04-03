"""Cross-encoder reranking via fastembed ONNX models.

Lazy-loads a TextCrossEncoder on first use; runs scoring in a thread executor
to avoid blocking the event loop (ONNX inference is CPU-bound).

Pattern mirrors app/agent/local_embeddings.py.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Singleton cache: model_name -> loaded TextCrossEncoder
_loaded_models: dict[str, object] = {}
_load_lock = threading.Lock()


def _fastembed_rerank_available() -> bool:
    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder  # noqa: F401
        return True
    except ImportError:
        return False


def _get_cache_dir() -> str | None:
    from app.config import settings
    return settings.FASTEMBED_CACHE_DIR or None


def _get_or_load_model(model_name: str) -> object:
    """Lazy-load a fastembed TextCrossEncoder model (thread-safe)."""
    if model_name in _loaded_models:
        return _loaded_models[model_name]

    with _load_lock:
        # Double-check after acquiring lock
        if model_name in _loaded_models:
            return _loaded_models[model_name]

        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
        except ImportError:
            raise RuntimeError(
                "fastembed rerank support not available. "
                "Install fastembed with: pip install fastembed"
            )

        cache_dir = _get_cache_dir()
        logger.info("Loading cross-encoder model: %s (first use may download)", model_name)
        model = TextCrossEncoder(model_name=model_name, cache_dir=cache_dir)
        _loaded_models[model_name] = model
        logger.info("Loaded cross-encoder model: %s", model_name)
        return model


def rerank_sync(
    query: str,
    documents: list[str],
    *,
    model_name: str,
) -> list[float]:
    """Score query-document pairs using a cross-encoder (synchronous, CPU-bound).

    Returns a list of relevance scores (one per document), in the same order
    as the input documents. Higher scores = more relevant.
    """
    if not documents:
        return []

    encoder = _get_or_load_model(model_name)
    # fastembed TextCrossEncoder.rerank returns Iterable[float] in document order
    return list(encoder.rerank(query, documents))  # type: ignore[union-attr]


async def rerank_async(
    query: str,
    documents: list[str],
    *,
    model_name: str,
) -> list[float]:
    """Async wrapper: runs cross-encoder scoring in a thread executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, lambda: rerank_sync(query, documents, model_name=model_name)
    )
