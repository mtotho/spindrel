"""Filesystem indexer: chunk, embed, and semantically retrieve files from arbitrary directories."""
from __future__ import annotations

import ast
import hashlib
import json
import logging
import re
import time
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import delete, func, select

from app.agent.chunking import ChunkResult, chunk_markdown as _shared_chunk_markdown, chunk_sliding_window as _shared_chunk_sliding_window
from app.agent.embeddings import embed_batch, embed_text
from app.config import settings
from app.db.engine import async_session
from app.db.models import FilesystemChunk

logger = logging.getLogger(__name__)

# In-memory cooldown: (abs_root, bot_id, client_id) -> monotonic timestamp of last full index
_last_indexed: dict[tuple[str, str, str], float] = {}

# Extensions to always skip
_SKIP_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe", ".bin",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z",
    ".lock", ".sum", ".mod",
}
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache", ".ruff_cache", "dist", "build", ".next", ".history"}

# Workspace convention files that are auto-injected via dedicated mechanisms
# (persona, skills, base prompt).  Indexing them would cause double-injection.
_AUTO_INJECTED_PATTERNS: list[tuple[str, ...]] = [
    # persona.md at bot root
    ("persona.md",),
    # skills/ subtree (pinned, rag, on-demand, top-level) — bot or common
    ("skills",),
    ("common", "skills"),
    # prompts/base.md — bot or common
    ("prompts", "base.md"),
    ("common", "prompts", "base.md"),
]


def _is_auto_injected(rel_parts: tuple[str, ...]) -> bool:
    """Return True if the file matches a workspace convention path that is auto-injected."""
    for pattern in _AUTO_INJECTED_PATTERNS:
        if len(pattern) == 1:
            if pattern[0] == rel_parts[-1] and len(rel_parts) == 1:
                # Exact filename at root (e.g. persona.md)
                return True
            if rel_parts[0] == pattern[0]:
                # Entire subtree (e.g. skills/...)
                return True
        else:
            if rel_parts[:len(pattern)] == pattern:
                return True
    return False


# ---------------------------------------------------------------------------
# Chunkers
# ---------------------------------------------------------------------------

def _chunk_sliding_window(source: str, rel_path: str, language: str | None) -> list[ChunkResult]:
    """Generic fallback: boundary-aware sliding window via shared module."""
    header = f"# {rel_path}\n"
    window = settings.FS_INDEX_CHUNK_WINDOW
    overlap = settings.FS_INDEX_CHUNK_OVERLAP
    if len(source) <= window:
        return [ChunkResult(content=header + source, language=language)]
    chunks = _shared_chunk_sliding_window(
        source,
        source_label=rel_path,
        window=window,
        overlap=overlap,
        language=language,
        break_on_boundaries=True,
    )
    # Prepend file header to content for display
    for c in chunks:
        c.content = header + c.content
    return chunks


def _chunk_python(source: str, rel_path: str) -> list[ChunkResult]:
    """AST-based: one chunk per top-level or class-level function/class definition."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _chunk_sliding_window(source, rel_path, "python")

    lines = source.splitlines(keepends=True)
    chunks: list[ChunkResult] = []

    # Collect only top-level and class-member nodes (not nested)
    top_nodes: list[ast.stmt] = list(tree.body)
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            top_nodes.extend(node.body)

    for node in top_nodes:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if not hasattr(node, "end_lineno"):
            continue
        start = node.lineno - 1
        end = node.end_lineno
        body = "".join(lines[start:end])
        chunks.append(ChunkResult(
            content=f"# {rel_path}\n{body}",
            symbol=node.name,
            start_line=node.lineno,
            end_line=node.end_lineno,
            language="python",
        ))

    if not chunks:
        return _chunk_sliding_window(source, rel_path, "python")

    # If any single chunk exceeds the window, sub-chunk it
    result: list[ChunkResult] = []
    for c in chunks:
        if len(c.content) > settings.FS_INDEX_CHUNK_WINDOW * 2:
            sub = _chunk_sliding_window(c.content, rel_path, "python")
            for s in sub:
                s.symbol = c.symbol
                s.start_line = c.start_line
                s.end_line = c.end_line
            result.extend(sub)
        else:
            result.append(c)
    return result


def _chunk_markdown(source: str, rel_path: str) -> list[ChunkResult]:
    """Hierarchy-aware markdown chunking via shared module."""
    chunk_results = _shared_chunk_markdown(
        source,
        source_label=rel_path,
        max_chunk=settings.FS_INDEX_CHUNK_WINDOW,
    )
    for cr in chunk_results:
        cr.language = "markdown"
        # Prepend file path header for display (like other chunkers)
        if not cr.content.startswith(f"# {rel_path}"):
            cr.content = f"# {rel_path}\n{cr.content}"
    return chunk_results


def _chunk_yaml(source: str, rel_path: str) -> list[ChunkResult]:
    """Whole file if short; else split by top-level keys."""
    if len(source) <= settings.FS_INDEX_CHUNK_WINDOW:
        return [ChunkResult(content=f"# {rel_path}\n{source}", language="yaml")]
    try:
        import yaml
        data = yaml.safe_load(source)
    except Exception:
        return _chunk_sliding_window(source, rel_path, "yaml")
    if not isinstance(data, dict):
        return _chunk_sliding_window(source, rel_path, "yaml")
    chunks: list[ChunkResult] = []
    for key, value in data.items():
        import yaml as _yaml
        chunk_str = _yaml.dump({key: value}, default_flow_style=False)
        chunks.append(ChunkResult(
            content=f"# {rel_path} — {key}\n{chunk_str}",
            symbol=str(key),
            language="yaml",
        ))
    return chunks or _chunk_sliding_window(source, rel_path, "yaml")


def _chunk_json(source: str, rel_path: str) -> list[ChunkResult]:
    """Whole file if short; else split by top-level keys."""
    if len(source) <= settings.FS_INDEX_CHUNK_WINDOW:
        return [ChunkResult(content=f"# {rel_path}\n{source}", language="json")]
    try:
        data = json.loads(source)
    except Exception:
        return _chunk_sliding_window(source, rel_path, "json")
    if not isinstance(data, dict):
        return _chunk_sliding_window(source, rel_path, "json")
    chunks: list[ChunkResult] = []
    for key, value in data.items():
        chunk_str = json.dumps({key: value}, indent=2)
        chunks.append(ChunkResult(
            content=f"# {rel_path} — {key}\n{chunk_str}",
            symbol=str(key),
            language="json",
        ))
    return chunks or _chunk_sliding_window(source, rel_path, "json")


_TS_SYMBOLS = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\*?\s+|class\s+)(\w+)",
    re.MULTILINE,
)
_GO_SYMBOLS = re.compile(
    r"^func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\(",
    re.MULTILINE,
)
_RUST_SYMBOLS = re.compile(
    r"^(?:pub\s+)?(?:async\s+)?fn\s+(\w+)\s*[(<]",
    re.MULTILINE,
)


def _chunk_code_regex(
    source: str, rel_path: str, language: str, pattern: re.Pattern[str]
) -> list[ChunkResult]:
    """Split by regex-detected symbol boundaries."""
    matches = list(pattern.finditer(source))
    if len(matches) < 2:
        return _chunk_sliding_window(source, rel_path, language)
    chunks: list[ChunkResult] = []
    for i, m in enumerate(matches):
        start_char = m.start()
        end_char = matches[i + 1].start() if i + 1 < len(matches) else len(source)
        body = source[start_char:end_char].strip()
        start_line = source[:start_char].count("\n") + 1
        end_line = source[:end_char].count("\n") + 1
        chunk_text = f"// {rel_path}\n{body}"
        if len(chunk_text) > settings.FS_INDEX_CHUNK_WINDOW * 2:
            chunks.extend(_chunk_sliding_window(body, rel_path, language))
        else:
            chunks.append(ChunkResult(
                content=chunk_text,
                symbol=m.group(1),
                start_line=start_line,
                end_line=end_line,
                language=language,
            ))
    return chunks


def _chunk_code_treesitter_or_fallback(
    source: str, rel_path: str, language: str, regex_pattern: re.Pattern[str],
) -> list[ChunkResult]:
    """Try tree-sitter chunking, fall back to regex on import/parse failure."""
    try:
        from app.agent.chunking_treesitter import chunk_code_treesitter
        result = chunk_code_treesitter(source, rel_path, language)
        if result is not None:
            return result
    except ImportError:
        logger.debug("tree-sitter not available for %s, falling back to regex", language)
    except Exception:
        logger.debug("tree-sitter parse failed for %s, falling back to regex", rel_path, exc_info=True)
    return _chunk_code_regex(source, rel_path, language, regex_pattern)


_EXT_DISPATCH: dict[str, Any] = {
    ".py": _chunk_python,
    ".md": _chunk_markdown,
    ".yaml": _chunk_yaml,
    ".yml": _chunk_yaml,
    ".json": _chunk_json,
    ".ts": lambda s, r: _chunk_code_treesitter_or_fallback(s, r, "typescript", _TS_SYMBOLS),
    ".tsx": lambda s, r: _chunk_code_treesitter_or_fallback(s, r, "typescript", _TS_SYMBOLS),
    ".js": lambda s, r: _chunk_code_treesitter_or_fallback(s, r, "javascript", _TS_SYMBOLS),
    ".jsx": lambda s, r: _chunk_code_treesitter_or_fallback(s, r, "javascript", _TS_SYMBOLS),
    ".go": lambda s, r: _chunk_code_treesitter_or_fallback(s, r, "go", _GO_SYMBOLS),
    ".rs": lambda s, r: _chunk_code_treesitter_or_fallback(s, r, "rust", _RUST_SYMBOLS),
}


def chunk_file(path: Path, root: Path) -> list[ChunkResult]:
    """Read and chunk a single file. Returns [] on binary/read errors."""
    if path.suffix.lower() in _SKIP_EXTENSIONS:
        return []
    if path.stat().st_size > settings.FS_INDEX_MAX_FILE_BYTES:
        return []
    try:
        source = path.read_text(errors="ignore")
    except Exception:
        return []
    rel = str(PurePosixPath(path.relative_to(root)))
    dispatch = _EXT_DISPATCH.get(path.suffix.lower())
    if dispatch:
        return dispatch(source, rel)
    return _chunk_sliding_window(source, rel, None)


def _match_segment(file_rel_path: str, segments: list[dict] | None) -> dict | None:
    """Return the most-specific matching segment (longest path_prefix) or None."""
    if not segments:
        return None
    best: dict | None = None
    best_len = -1
    for seg in segments:
        prefix = seg["path_prefix"]
        # Normalize: ensure prefix ends with / for directory matching (unless it's exact)
        if file_rel_path == prefix or file_rel_path.startswith(prefix if prefix.endswith("/") else prefix + "/"):
            if len(prefix) > best_len:
                best = seg
                best_len = len(prefix)
    return best


# ---------------------------------------------------------------------------
# Indexer
# ---------------------------------------------------------------------------

def _build_pathspec(root: Path):
    """Return a pathspec from .gitignore, or None if not found."""
    try:
        import pathspec
    except ImportError:
        return None
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        return None
    return pathspec.PathSpec.from_lines("gitwildmatch", gitignore.read_text().splitlines())


async def index_directory(
    root: str,
    bot_id: str | None,
    patterns: list[str],
    *,
    client_id: str | None = None,
    force: bool = False,
    file_paths: list[Path] | None = None,
    cooldown_seconds: int | None = None,
    embedding_model: str | None = None,
    segments: list[dict] | None = None,
) -> dict:
    """
    Index a directory for semantic search.

    - bot_id=None: cross-bot index (accessible to all bots).
    - client_id=None: cross-client index (accessible from all channels/clients).
    - force=True: bypass cooldown (used on startup and by the agent tool).
    - file_paths: if provided, only re-index those specific files (watcher use).
    - Returns stats: {indexed, skipped, removed, errors, cooldown}.
    """
    root_path = Path(root).resolve()
    key = (str(root_path), bot_id or "", client_id or "")
    now = time.monotonic()
    cd = cooldown_seconds if cooldown_seconds is not None else settings.FS_INDEX_COOLDOWN_SECONDS

    if not force and file_paths is None:
        last = _last_indexed.get(key, 0.0)
        if now - last < cd:
            logger.info("Skipping index of %s for bot %s (cooldown, %.0fs remaining)", root, bot_id, cd - (now - last))
            return {"indexed": 0, "skipped": 0, "removed": 0, "errors": 0, "cooldown": True}

    spec = _build_pathspec(root_path)

    # Discover candidate files
    if file_paths is not None:
        candidates = [
            p.resolve() for p in file_paths
            if p.is_file() and not _is_auto_injected(p.resolve().relative_to(root_path).parts)
        ]
    else:
        seen: set[Path] = set()
        for pattern in patterns:
            for p in root_path.glob(pattern):
                if not p.is_file():
                    continue
                if p in seen:
                    continue
                # Skip ignored dirs
                parts = p.relative_to(root_path).parts
                if any(part in _SKIP_DIRS for part in parts):
                    continue
                if p.suffix.lower() in _SKIP_EXTENSIONS:
                    continue
                if _is_auto_injected(parts):
                    continue
                if spec:
                    try:
                        rel = str(PurePosixPath(p.relative_to(root_path)))
                        if spec.match_file(rel):
                            continue
                    except ValueError:
                        pass
                seen.add(p)
        candidates = list(seen)

    stats = {"indexed": 0, "skipped": 0, "removed": 0, "errors": 0, "cooldown": False}

    # Build scope filter helpers
    def _scope_filter():
        """Return WHERE conditions matching this index's exact scope."""
        conds = [FilesystemChunk.root == str(root_path)]
        if bot_id is None:
            conds.append(FilesystemChunk.bot_id.is_(None))
        else:
            conds.append(FilesystemChunk.bot_id == bot_id)
        if client_id is None:
            conds.append(FilesystemChunk.client_id.is_(None))
        else:
            conds.append(FilesystemChunk.client_id == client_id)
        return conds

    # Fetch existing content_hashes + embedding_model in bulk for this (bot_id, client_id, root)
    async with async_session() as db:
        _fs_sub = (
            select(
                FilesystemChunk.file_path,
                FilesystemChunk.content_hash,
                FilesystemChunk.embedding_model,
                func.row_number().over(
                    partition_by=FilesystemChunk.file_path,
                    order_by=FilesystemChunk.id,
                ).label("_rn"),
            )
            .where(*_scope_filter())
            .subquery()
        )
        rows = (await db.execute(
            select(_fs_sub.c.file_path, _fs_sub.c.content_hash, _fs_sub.c.embedding_model)
            .where(_fs_sub.c._rn == 1)
        )).all()
    existing_hashes: dict[str, str] = {row.file_path: row.content_hash for row in rows}
    existing_models: dict[str, str | None] = {row.file_path: row.embedding_model for row in rows}

    # Resolve the base embedding model for this index run
    base_model = embedding_model or settings.EMBEDDING_MODEL

    # Process each candidate
    _dims_validated = False
    for path in candidates:
        rel = str(PurePosixPath(path.relative_to(root_path)))
        chunks = chunk_file(path, root_path)
        if not chunks:
            continue

        raw = path.read_bytes()
        file_hash = hashlib.sha256(raw).hexdigest()

        # Determine effective embedding model for this file (segment override or base)
        seg = _match_segment(rel, segments)
        effective_model = seg["embedding_model"] if seg else base_model

        # Re-embed if content changed OR if the embedding model changed
        content_unchanged = existing_hashes.get(rel) == file_hash
        model_unchanged = existing_models.get(rel) == effective_model
        if content_unchanged and model_unchanged:
            stats["skipped"] += 1
            continue

        # Embed all chunks for this file
        texts = [c.content for c in chunks]
        try:
            # Batch in groups of 50
            embeddings: list[list[float]] = []
            for i in range(0, len(texts), 50):
                embeddings.extend(await embed_batch(texts[i:i + 50], model=effective_model))
        except Exception:
            logger.exception("Failed to embed %s", rel)
            stats["errors"] += 1
            continue

        # Validate dimensions on first successful batch
        if not _dims_validated and embeddings:
            dim = len(embeddings[0])
            if dim != settings.EMBEDDING_DIMENSIONS:
                logger.error(
                    "Embedding dimension mismatch: model %s returned %d dims, expected %d",
                    effective_model, dim, settings.EMBEDDING_DIMENSIONS,
                )
                stats["errors"] += 1
                continue
            _dims_validated = True

        try:
            async with async_session() as db:
                # Delete old chunks for this file
                await db.execute(
                    delete(FilesystemChunk).where(
                        *_scope_filter(),
                        FilesystemChunk.file_path == rel,
                    )
                )
                # Insert new chunks
                for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
                    row = FilesystemChunk(
                        bot_id=bot_id,
                        client_id=client_id,
                        root=str(root_path),
                        file_path=rel,
                        content_hash=file_hash,
                        chunk_index=i,
                        content=chunk.content,
                        embedding=emb,
                        language=chunk.language,
                        symbol=chunk.symbol,
                        start_line=chunk.start_line,
                        end_line=chunk.end_line,
                        embedding_model=effective_model,
                    )
                    db.add(row)
                # Commit chunks first — ensures they persist even if tsvector fails
                await db.commit()
        except Exception:
            logger.exception("Failed to insert chunks for %s (bot=%s, root=%s)", rel, bot_id, root_path)
            stats["errors"] += 1
            continue

        # Populate tsvector column (non-fatal — chunks are saved without FTS on failure)
        try:
            async with async_session() as db:
                from sqlalchemy import text as _sa_text
                await db.execute(_sa_text(
                    "UPDATE filesystem_chunks SET tsv = to_tsvector('english', content) "
                    "WHERE file_path = :fp AND root = :rt AND tsv IS NULL"
                ).bindparams(fp=rel, rt=str(root_path)))
                await db.commit()
        except Exception:
            logger.warning("TSVector population failed for %s (chunks saved without FTS)", rel)

        stats["indexed"] += 1
        logger.debug("Indexed %s (%d chunks, model=%s)", rel, len(chunks), effective_model)

    # Remove stale DB entries for files no longer on disk (full re-index only)
    if file_paths is None:
        disk_set = {str(PurePosixPath(p.relative_to(root_path))) for p in candidates}
        stale = set(existing_hashes.keys()) - disk_set
        if stale:
            async with async_session() as db:
                await db.execute(
                    delete(FilesystemChunk).where(
                        *_scope_filter(),
                        FilesystemChunk.file_path.in_(stale),
                    )
                )
                await db.commit()
            stats["removed"] = len(stale)
        _last_indexed[key] = time.monotonic()

    logger.info(
        "Indexed %s for bot %s client %s: %d new, %d skipped, %d removed, %d errors",
        root, bot_id, client_id, stats["indexed"], stats["skipped"], stats["removed"], stats["errors"],
    )
    return stats


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def _excluded_prefixes(segments: list[dict] | None, channel_id: str | None) -> list[str]:
    """Return path prefixes of segments whose channel_id doesn't match the active channel.

    A segment with channel_id=None is always included (matches all channels).
    A segment with channel_id set is included only if it matches the active channel_id.
    """
    if not segments:
        return []
    excluded: list[str] = []
    for seg in segments:
        seg_ch = seg.get("channel_id")
        if seg_ch is None:
            continue  # no channel restriction → always included
        # Segment is channel-gated: exclude unless active channel matches
        if channel_id is None or seg_ch != str(channel_id):
            excluded.append(seg["path_prefix"])
    return excluded


async def retrieve_filesystem_context(
    query: str,
    bot_id: str | None,
    client_id: str | None = None,
    roots: list[str] | None = None,
    top_k: int | None = None,
    threshold: float | None = None,
    embedding_model: str | None = None,
    segments: list[dict] | None = None,
    channel_id: str | None = None,
) -> tuple[list[str], float]:
    """Embed query, cosine-search filesystem_chunks, return (formatted_chunks, best_similarity).

    Scope semantics (matches knowledge system):
    - bot_id: returns chunks where chunk.bot_id == bot_id OR chunk.bot_id IS NULL
    - client_id: returns chunks where chunk.client_id == client_id OR chunk.client_id IS NULL
    - channel_id: segments with a channel_id are skipped unless the active channel matches
    """
    top_k = top_k or settings.FS_INDEX_TOP_K
    threshold = threshold if threshold is not None else settings.FS_INDEX_SIMILARITY_THRESHOLD
    base_model = embedding_model or settings.EMBEDDING_MODEL

    # Build list of path prefixes to exclude (channel-gated segments that don't match)
    _excl = _excluded_prefixes(segments, channel_id)

    # Collect unique embedding models: base + any segment-specific models (only from included segments)
    unique_models: set[str] = {base_model}
    if segments:
        for seg in segments:
            if seg["path_prefix"] not in _excl:
                unique_models.add(seg["embedding_model"])

    from sqlalchemy import and_, or_

    bot_filter = (
        or_(FilesystemChunk.bot_id == bot_id, FilesystemChunk.bot_id.is_(None))
        if bot_id is not None
        else FilesystemChunk.bot_id.is_(None)
    )
    client_filter = (
        or_(FilesystemChunk.client_id == client_id, FilesystemChunk.client_id.is_(None))
        if client_id is not None
        else FilesystemChunk.client_id.is_(None)
    )
    abs_roots = [str(Path(r).resolve()) for r in roots] if roots else None

    # Build path-prefix exclusion filters for channel-gated segments
    _path_excl_filters = []
    for prefix in _excl:
        normalized = prefix if prefix.endswith("/") else prefix + "/"
        _path_excl_filters.append(~FilesystemChunk.file_path.startswith(normalized))
        # Also exclude exact match (e.g. file_path == prefix without trailing slash)
        _path_excl_filters.append(FilesystemChunk.file_path != prefix.rstrip("/"))

    # Single-model fast path (most common case: no segments or all same model)
    if len(unique_models) == 1:
        model = next(iter(unique_models))
        try:
            query_embedding = await embed_text(query, model=model)
        except Exception:
            logger.exception("Failed to embed query for filesystem retrieval")
            return [], 0.0

        distance_expr = FilesystemChunk.embedding.cosine_distance(query_embedding)
        # Match chunks with this model or legacy NULL (embedded with default model)
        model_filter = or_(
            FilesystemChunk.embedding_model == model,
            FilesystemChunk.embedding_model.is_(None),
        )
        stmt = (
            select(
                FilesystemChunk.content,
                FilesystemChunk.file_path,
                FilesystemChunk.symbol,
                FilesystemChunk.start_line,
                FilesystemChunk.end_line,
                distance_expr.label("distance"),
            )
            .where(bot_filter, client_filter, model_filter, *_path_excl_filters)
            .order_by(distance_expr)
            .limit(top_k)
        )
        if abs_roots:
            stmt = stmt.where(FilesystemChunk.root.in_(abs_roots))

        try:
            async with async_session() as db:
                rows = (await db.execute(stmt)).all()
        except Exception:
            logger.exception("Filesystem retrieval query failed")
            return [], 0.0

        return _format_retrieval_results(rows, threshold, query)

    # Multi-model path: embed query once per unique model, query separately, merge
    all_rows: list = []
    for model in unique_models:
        try:
            query_embedding = await embed_text(query, model=model)
        except Exception:
            logger.exception("Failed to embed query with model %s", model)
            continue

        distance_expr = FilesystemChunk.embedding.cosine_distance(query_embedding)
        model_filter = or_(
            FilesystemChunk.embedding_model == model,
            # Legacy NULL chunks only queried with default model
            FilesystemChunk.embedding_model.is_(None),
        ) if model == base_model else (FilesystemChunk.embedding_model == model)

        stmt = (
            select(
                FilesystemChunk.content,
                FilesystemChunk.file_path,
                FilesystemChunk.symbol,
                FilesystemChunk.start_line,
                FilesystemChunk.end_line,
                distance_expr.label("distance"),
            )
            .where(bot_filter, client_filter, model_filter, *_path_excl_filters)
            .order_by(distance_expr)
            .limit(top_k)
        )
        if abs_roots:
            stmt = stmt.where(FilesystemChunk.root.in_(abs_roots))

        try:
            async with async_session() as db:
                rows = (await db.execute(stmt)).all()
            all_rows.extend(rows)
        except Exception:
            logger.exception("Filesystem retrieval query failed for model %s", model)

    # Merge: sort by distance, take top_k
    all_rows.sort(key=lambda r: r.distance)
    all_rows = all_rows[:top_k]
    return _format_retrieval_results(all_rows, threshold, query)


def _format_retrieval_results(
    rows: list, threshold: float, query: str,
) -> tuple[list[str], float]:
    """Format DB rows into retrieval results."""
    if not rows:
        return [], 0.0

    best_sim = 1.0 - rows[0].distance
    logger.info(
        "Filesystem retrieval: best_similarity=%.3f threshold=%.3f query=%s...",
        best_sim, threshold, query[:60],
    )

    results: list[str] = []
    for row in rows:
        similarity = 1.0 - row.distance
        if similarity < threshold:
            break
        location = row.file_path
        if row.symbol:
            location += f" ({row.symbol})"
        if row.start_line and row.end_line:
            location += f" L{row.start_line}–{row.end_line}"
        results.append(f"[File: {location}]\n\n{row.content}")

    return results, best_sim
