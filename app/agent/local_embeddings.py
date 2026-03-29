"""Local embedding models via fastembed (ONNX-based, no PyTorch required).

Models are identified by a ``local/`` prefix, e.g. ``local/BAAI/bge-small-en-v1.5``.
The fastembed library is optional — when not installed, ``list_local_models()``
returns an empty list and ``embed_local()`` raises a clear error.

Models are lazy-loaded on first use and cached in a module-level dict.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

LOCAL_PREFIX = "local/"

# Curated list of known lightweight embedding models.
# (model_name, native_dimensions, approximate_size_mb)
KNOWN_MODELS: list[tuple[str, int, int]] = [
    ("BAAI/bge-small-en-v1.5", 384, 67),
    ("BAAI/bge-base-en-v1.5", 768, 220),
    ("sentence-transformers/all-MiniLM-L6-v2", 384, 86),
    ("nomic-ai/nomic-embed-text-v1.5", 768, 548),
]

# Singleton cache: stripped model name -> loaded TextEmbedding instance
_loaded_models: dict[str, object] = {}


def is_local_model(model: str) -> bool:
    """Return True if the model string uses the local/ prefix."""
    return model.startswith(LOCAL_PREFIX)


def strip_prefix(model: str) -> str:
    """Remove the ``local/`` prefix from a model name."""
    if model.startswith(LOCAL_PREFIX):
        return model[len(LOCAL_PREFIX):]
    return model


def _fastembed_available() -> bool:
    try:
        import fastembed  # noqa: F401
        return True
    except ImportError:
        return False


def _get_cache_dir() -> str | None:
    """Return the configured fastembed cache dir, or None for default."""
    from app.config import settings
    return settings.FASTEMBED_CACHE_DIR or None


def is_model_cached(model_name: str) -> bool:
    """Check if a fastembed model is already downloaded in the cache.

    Uses huggingface_hub.scan_cache_dir to inspect the cache without loading.
    ``model_name`` should be the bare HF name (e.g. ``BAAI/bge-small-en-v1.5``).
    Returns False if fastembed is not installed or on any error.
    """
    if not _fastembed_available():
        return False
    try:
        from huggingface_hub import scan_cache_dir

        cache_dir = _get_cache_dir()
        if cache_dir:
            cache_path = Path(cache_dir)
        else:
            # fastembed default: ~/.cache/fastembed (uses HF hub under the hood)
            cache_path = Path.home() / ".cache" / "huggingface" / "hub"

        if not cache_path.exists():
            return False

        info = scan_cache_dir(cache_path)
        # HF hub stores repos as "models--{org}--{name}"
        for repo in info.repos:
            if repo.repo_id == model_name:
                # Has at least one revision with some files
                return any(rev.nb_files > 0 for rev in repo.revisions)
        return False
    except Exception:
        logger.debug("Failed to check cache for %s", model_name, exc_info=True)
        return False


def get_model_size_mb(model_name: str) -> int | None:
    """Return the approximate model size in MB from the curated list."""
    for name, _dims, size_mb in KNOWN_MODELS:
        if name == model_name:
            return size_mb
    return None


def list_local_models() -> list[dict]:
    """Return curated local models with download status. Empty list if fastembed not installed."""
    if not _fastembed_available():
        return []
    models = []
    for name, dims, size_mb in KNOWN_MODELS:
        cached = is_model_cached(name)
        models.append({
            "id": f"{LOCAL_PREFIX}{name}",
            "display": name,
            "dimensions": dims,
            "size_mb": size_mb,
            "download_status": "cached" if cached else "not_downloaded",
        })
    return models


def download_model_sync(model_name: str) -> None:
    """Download a fastembed model by instantiating TextEmbedding (synchronous, blocking).

    ``model_name`` should be the bare HF name (e.g. ``BAAI/bge-small-en-v1.5``).
    This is intended to be run in an executor for async callers.
    """
    try:
        from fastembed import TextEmbedding
    except ImportError:
        raise RuntimeError(
            "fastembed is not installed. Install it with: "
            "pip install fastembed  (or add 'local-embeddings' optional dep)"
        )

    cache_dir = _get_cache_dir()
    logger.info("Downloading local embedding model: %s", model_name)
    model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
    # Cache it so subsequent embed calls don't re-load
    _loaded_models[model_name] = model
    logger.info("Download complete: %s", model_name)


def _get_or_load_model(model_name: str) -> object:
    """Lazy-load a fastembed TextEmbedding model (downloads on first use)."""
    if model_name in _loaded_models:
        return _loaded_models[model_name]

    try:
        from fastembed import TextEmbedding
    except ImportError:
        raise RuntimeError(
            "fastembed is not installed. Install it with: "
            "pip install fastembed  (or add 'local-embeddings' optional dep)"
        )

    cache_dir = _get_cache_dir()
    logger.info("Loading local embedding model: %s (first use may download)", model_name)
    model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
    _loaded_models[model_name] = model
    logger.info("Loaded local embedding model: %s", model_name)
    return model


def embed_local_sync(texts: list[str], *, model: str) -> list[list[float]]:
    """Embed texts using a local fastembed model (synchronous, CPU-bound).

    ``model`` should be the full prefixed name (e.g. ``local/BAAI/bge-small-en-v1.5``).
    Returns a list of embedding vectors.
    """
    bare_name = strip_prefix(model)
    te = _get_or_load_model(bare_name)
    # fastembed returns a generator of numpy arrays
    embeddings = list(te.embed(texts))  # type: ignore[union-attr]
    return [emb.tolist() for emb in embeddings]
