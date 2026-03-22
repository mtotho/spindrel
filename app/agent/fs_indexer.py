"""Filesystem indexer: chunk, embed, and semantically retrieve files from arbitrary directories."""
from __future__ import annotations

import ast
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from openai import AsyncOpenAI
from sqlalchemy import delete, func, select

from app.config import settings
from app.db.engine import async_session
from app.db.models import FilesystemChunk

logger = logging.getLogger(__name__)

_client = AsyncOpenAI(
    base_url=settings.LITELLM_BASE_URL,
    api_key=settings.LITELLM_API_KEY,
    timeout=120.0,
)

# In-memory cooldown: (abs_root, bot_id, client_id) -> monotonic timestamp of last full index
_last_indexed: dict[tuple[str, str, str], float] = {}

# Extensions to always skip
_SKIP_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe", ".bin",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z",
    ".lock", ".sum", ".mod",
}
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache", ".ruff_cache", "dist", "build", ".next"}


@dataclass
class ChunkResult:
    content: str
    language: str | None = None
    symbol: str | None = None
    start_line: int | None = None
    end_line: int | None = None


# ---------------------------------------------------------------------------
# Chunkers
# ---------------------------------------------------------------------------

def _chunk_sliding_window(source: str, rel_path: str, language: str | None) -> list[ChunkResult]:
    """Generic fallback: split by character window with overlap."""
    header = f"# {rel_path}\n"
    window = settings.FS_INDEX_CHUNK_WINDOW
    overlap = settings.FS_INDEX_CHUNK_OVERLAP
    if len(source) <= window:
        return [ChunkResult(content=header + source, language=language)]
    chunks: list[ChunkResult] = []
    i = 0
    while i < len(source):
        end = min(i + window, len(source))
        chunks.append(ChunkResult(content=header + source[i:end], language=language))
        if end == len(source):
            break
        i += window - overlap
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
    """Split by ## headers, same as skills chunker."""
    from app.agent.skills import _chunk_markdown as _skills_chunk
    chunks_text = _skills_chunk(source, rel_path, max_chunk=settings.FS_INDEX_CHUNK_WINDOW)
    return [
        ChunkResult(content=t, language="markdown")
        for t in chunks_text
    ]


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


_EXT_DISPATCH: dict[str, Any] = {
    ".py": _chunk_python,
    ".md": _chunk_markdown,
    ".yaml": _chunk_yaml,
    ".yml": _chunk_yaml,
    ".json": _chunk_json,
    ".ts": lambda s, r: _chunk_code_regex(s, r, "typescript", _TS_SYMBOLS),
    ".tsx": lambda s, r: _chunk_code_regex(s, r, "typescript", _TS_SYMBOLS),
    ".js": lambda s, r: _chunk_code_regex(s, r, "javascript", _TS_SYMBOLS),
    ".jsx": lambda s, r: _chunk_code_regex(s, r, "javascript", _TS_SYMBOLS),
    ".go": lambda s, r: _chunk_code_regex(s, r, "go", _GO_SYMBOLS),
    ".rs": lambda s, r: _chunk_code_regex(s, r, "rust", _RUST_SYMBOLS),
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


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

async def _embed_batch(texts: list[str]) -> list[list[float]]:
    response = await _client.embeddings.create(
        model=settings.EMBEDDING_MODEL,
        input=texts,
    )
    return [item.embedding for item in response.data]


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
        candidates = [p.resolve() for p in file_paths if p.is_file()]
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

    # Fetch existing content_hashes in bulk for this (bot_id, client_id, root)
    async with async_session() as db:
        _fs_sub = (
            select(
                FilesystemChunk.file_path,
                FilesystemChunk.content_hash,
                func.row_number().over(
                    partition_by=FilesystemChunk.file_path,
                    order_by=FilesystemChunk.id,
                ).label("_rn"),
            )
            .where(*_scope_filter())
            .subquery()
        )
        rows = (await db.execute(
            select(_fs_sub.c.file_path, _fs_sub.c.content_hash)
            .where(_fs_sub.c._rn == 1)
        )).all()
    existing_hashes: dict[str, str] = {row.file_path: row.content_hash for row in rows}

    # Process each candidate
    for path in candidates:
        rel = str(PurePosixPath(path.relative_to(root_path)))
        chunks = chunk_file(path, root_path)
        if not chunks:
            continue

        raw = path.read_bytes()
        file_hash = hashlib.sha256(raw).hexdigest()

        if existing_hashes.get(rel) == file_hash:
            stats["skipped"] += 1
            continue

        # Embed all chunks for this file
        texts = [c.content for c in chunks]
        try:
            # Batch in groups of 50
            embeddings: list[list[float]] = []
            for i in range(0, len(texts), 50):
                embeddings.extend(await _embed_batch(texts[i:i + 50]))
        except Exception:
            logger.exception("Failed to embed %s", rel)
            stats["errors"] += 1
            continue

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
                db.add(FilesystemChunk(
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
                ))
            await db.commit()

        stats["indexed"] += 1
        logger.debug("Indexed %s (%d chunks)", rel, len(chunks))

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

async def retrieve_filesystem_context(
    query: str,
    bot_id: str | None,
    client_id: str | None = None,
    roots: list[str] | None = None,
    top_k: int | None = None,
    threshold: float | None = None,
) -> tuple[list[str], float]:
    """Embed query, cosine-search filesystem_chunks, return (formatted_chunks, best_similarity).

    Scope semantics (matches knowledge system):
    - bot_id: returns chunks where chunk.bot_id == bot_id OR chunk.bot_id IS NULL
    - client_id: returns chunks where chunk.client_id == client_id OR chunk.client_id IS NULL
    """
    top_k = top_k or settings.FS_INDEX_TOP_K
    threshold = threshold if threshold is not None else settings.FS_INDEX_SIMILARITY_THRESHOLD

    try:
        response = await _client.embeddings.create(
            model=settings.EMBEDDING_MODEL,
            input=[query],
        )
        query_embedding = response.data[0].embedding
    except Exception:
        logger.exception("Failed to embed query for filesystem retrieval")
        return [], 0.0

    distance_expr = FilesystemChunk.embedding.cosine_distance(query_embedding)

    from sqlalchemy import or_

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

    stmt = (
        select(
            FilesystemChunk.content,
            FilesystemChunk.file_path,
            FilesystemChunk.symbol,
            FilesystemChunk.start_line,
            FilesystemChunk.end_line,
            distance_expr.label("distance"),
        )
        .where(bot_filter, client_filter)
        .order_by(distance_expr)
        .limit(top_k)
    )

    if roots:
        abs_roots = [str(Path(r).resolve()) for r in roots]
        stmt = stmt.where(FilesystemChunk.root.in_(abs_roots))

    try:
        async with async_session() as db:
            rows = (await db.execute(stmt)).all()
    except Exception:
        logger.exception("Filesystem retrieval query failed")
        return [], 0.0

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
        # Format: header with file path + optional symbol/lines, then content
        location = row.file_path
        if row.symbol:
            location += f" ({row.symbol})"
        if row.start_line and row.end_line:
            location += f" L{row.start_line}–{row.end_line}"
        results.append(f"[File: {location}]\n\n{row.content}")

    return results, best_sim
