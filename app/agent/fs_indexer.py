"""Filesystem indexer: chunk, embed, and semantically retrieve files from arbitrary directories."""
from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import delete, func, select

from app.agent.chunking import CHUNKING_VERSION, ChunkResult, chunk_markdown as _shared_chunk_markdown, chunk_sliding_window as _shared_chunk_sliding_window
from app.agent.contextual_retrieval import build_embed_text, generate_batch_contexts, get_effective_chunking_version
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
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache", ".ruff_cache", "dist", "build", ".next", ".history", ".tox", ".eggs", ".cache", ".pytest_cache"}

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


def _normalize_path_prefix(prefix: str) -> tuple[str, str]:
    """Return (directory prefix with trailing slash, exact path without slash)."""
    exact = prefix.rstrip("/")
    return (prefix if prefix.endswith("/") else prefix + "/", exact)


def _path_prefix_include_filters(prefixes: list[str] | None) -> list[Any]:
    """Build SQLAlchemy filters matching paths under or exactly equal to prefixes."""
    if not prefixes:
        return []
    from sqlalchemy import or_

    filters = []
    for prefix in dict.fromkeys(p for p in prefixes if p):
        normalized, exact = _normalize_path_prefix(prefix)
        filters.append(
            or_(
                FilesystemChunk.file_path.startswith(normalized),
                FilesystemChunk.file_path == exact,
            )
        )
    return filters


def _path_prefix_exclude_filters(prefixes: list[str] | None) -> list[Any]:
    """Build SQLAlchemy filters excluding paths under or exactly equal to prefixes."""
    if not prefixes:
        return []
    filters = []
    for prefix in dict.fromkeys(p for p in prefixes if p):
        normalized, exact = _normalize_path_prefix(prefix)
        filters.append(~FilesystemChunk.file_path.startswith(normalized))
        filters.append(FilesystemChunk.file_path != exact)
    return filters


def _knowledge_document_chunk_metadata(rel_path: str, file_text: str) -> dict[str, Any]:
    """Return indexed metadata for Knowledge Document markdown files."""
    normalized = rel_path.replace("\\", "/").strip("/")
    scope: str | None = None
    owner_user_id: str | None = None
    owner_bot_id: str | None = None
    channel_id: str | None = None
    project_scoped = False

    parts = normalized.split("/")
    if len(parts) >= 5 and parts[0] == "users" and parts[2:4] == ["knowledge-base", "notes"]:
        scope = "user"
        owner_user_id = parts[1]
    elif len(parts) >= 5 and parts[0] == "bots" and parts[2:4] == ["knowledge-base", "notes"]:
        scope = "bot"
        owner_bot_id = parts[1]
    elif len(parts) >= 5 and parts[0] == "channels" and parts[2:4] == ["knowledge-base", "notes"]:
        scope = "channel"
        channel_id = parts[1]
    elif len(parts) >= 4 and parts[:3] == [".spindrel", "knowledge-base", "notes"]:
        scope = "project"
        project_scoped = True

    if scope is None:
        return {}

    try:
        from app.services.knowledge_documents import parse_frontmatter

        frontmatter, _body = parse_frontmatter(file_text)
    except Exception:
        frontmatter = {}

    metadata: dict[str, Any] = {
        "knowledge_scope": scope,
        "kd_status": str(frontmatter.get("status") or "accepted"),
    }
    if frontmatter.get("entry_id"):
        metadata["entry_id"] = str(frontmatter["entry_id"])
    if owner_user_id:
        metadata["owner_user_id"] = owner_user_id
    elif frontmatter.get("user_id"):
        metadata["owner_user_id"] = str(frontmatter["user_id"])
    if owner_bot_id:
        metadata["owner_bot_id"] = owner_bot_id
    elif frontmatter.get("bot_id"):
        metadata["owner_bot_id"] = str(frontmatter["bot_id"])
    if channel_id:
        metadata["channel_id"] = channel_id
    elif frontmatter.get("channel_id"):
        metadata["channel_id"] = str(frontmatter["channel_id"])
    if project_scoped and frontmatter.get("project_id"):
        metadata["project_id"] = str(frontmatter["project_id"])
    return metadata


def _split_patterns(patterns: list[str]) -> tuple[list[str], list[str]]:
    """Split patterns into (include, exclude) lists.

    Patterns starting with ``!`` are exclusion patterns — any file matching an
    exclusion pattern is removed from the result set even if it matches an
    include pattern.  The leading ``!`` is stripped before returning.
    """
    include: list[str] = []
    exclude: list[str] = []
    for p in patterns:
        stripped = p.strip()
        if stripped.startswith("!"):
            exclude.append(stripped[1:])
        else:
            include.append(stripped)
    return include, exclude


def _glob_with_exclusions(
    base_dir: Path,
    patterns: list[str],
    accept: "Any",
) -> set[Path]:
    """Glob *base_dir* with *patterns*, honouring ``!``-prefixed exclusions."""
    include, exclude = _split_patterns(patterns)
    seen: set[Path] = set()
    for pattern in include:
        for p in base_dir.glob(pattern):
            if p not in seen and accept(p):
                seen.add(p)
    if exclude:
        excluded: set[Path] = set()
        for pattern in exclude:
            for p in base_dir.glob(pattern):
                excluded.add(p)
                # Path.glob("dir/**") only matches the directory itself in
                # Python 3.12+; also glob dir/**/* to catch files underneath.
                if p.is_dir():
                    for child in p.rglob("*"):
                        excluded.add(child)
        seen -= excluded
    return seen


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
# Per-file result for concurrent processing
# ---------------------------------------------------------------------------

@dataclass
class _FileResult:
    status: str  # "indexed" | "skipped" | "error"
    rel_path: str = ""
    dims: int | None = None
    chunk_count: int = 0


async def _process_file(
    path: Path,
    root_path: Path,
    bot_id: str | None,
    client_id: str | None,
    base_model: str,
    segments: list[dict] | None,
    existing_hashes: dict[str, str],
    existing_models: dict[str, str | None],
    existing_versions: dict[str, str | None],
    scope_conds: list,
    sem: asyncio.Semaphore,
    progress_state: dict | None,
) -> _FileResult:
    """Process a single file: chunk, embed, insert. Runs under semaphore."""
    rel = str(PurePosixPath(path.relative_to(root_path)))
    result: _FileResult | None = None

    async with sem:
        chunks = chunk_file(path, root_path)
        if not chunks:
            result = _FileResult(status="skipped", rel_path=rel)
        else:
            try:
                raw = path.read_bytes()
            except Exception:
                result = _FileResult(status="error", rel_path=rel)

        if result is None:
            file_hash = hashlib.sha256(raw).hexdigest()

            # Determine effective embedding model
            seg = _match_segment(rel, segments)
            effective_model = seg["embedding_model"] if seg else base_model

            # Skip if content, model, and chunking version unchanged
            # Treat existing_model=None as matching the default embedding model
            # (legacy rows pre-dating the embedding_model column)
            existing_model = existing_models.get(rel)
            model_matches = (existing_model == effective_model) or (existing_model is None and effective_model == base_model)
            effective_version = get_effective_chunking_version(CHUNKING_VERSION)
            version_matches = existing_versions.get(rel) == effective_version
            if existing_hashes.get(rel) == file_hash and model_matches and version_matches:
                result = _FileResult(status="skipped", rel_path=rel)

        if result is None:
            # Contextual retrieval: generate LLM descriptions for chunks
            file_text = raw.decode("utf-8", errors="replace")

            cr_chunks = [{"text": c.content, "index": i} for i, c in enumerate(chunks)]
            cr_descriptions = await generate_batch_contexts(cr_chunks, file_text, rel, file_hash)

            # Build embedding texts with contextual descriptions
            texts = []
            for i, c in enumerate(chunks):
                texts.append(build_embed_text(
                    c.content,
                    context_prefix=f"File: {rel}",
                    contextual_description=cr_descriptions[i],
                ))

            try:
                embeddings: list[list[float]] = []
                for i in range(0, len(texts), 50):
                    embeddings.extend(await embed_batch(texts[i:i + 50], model=effective_model))
            except Exception:
                logger.exception("Failed to embed %s", rel)
                result = _FileResult(status="error", rel_path=rel)

        if result is None:
            if not embeddings:
                result = _FileResult(status="error", rel_path=rel)

        if result is None:
            dims = len(embeddings[0])
            if dims != settings.EMBEDDING_DIMENSIONS:
                logger.error(
                    "Embedding dimension mismatch after zero-pad: model %s returned %d dims, "
                    "expected %d. This should not happen — check embeddings.py routing.",
                    effective_model, dims, settings.EMBEDDING_DIMENSIONS,
                )
                result = _FileResult(status="error", rel_path=rel, dims=dims)

        if result is None:
            # Write to DB
            try:
                kd_metadata = _knowledge_document_chunk_metadata(rel, file_text)
                async with async_session() as db:
                    await db.execute(
                        delete(FilesystemChunk).where(
                            *scope_conds,
                            FilesystemChunk.file_path == rel,
                        )
                    )
                    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
                        chunk_meta = {"chunking_version": effective_version, **kd_metadata}
                        if cr_descriptions[i]:
                            chunk_meta["contextual_description"] = cr_descriptions[i]
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
                            embedding_model=effective_model,
                            metadata_=chunk_meta,
                        ))
                    await db.commit()
            except Exception:
                logger.exception("Failed to insert chunks for %s (bot=%s, root=%s)", rel, bot_id, root_path)
                result = _FileResult(status="error", rel_path=rel)

        if result is None:
            # Populate tsvector (non-fatal)
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

            logger.debug("Indexed %s (%d chunks, model=%s)", rel, len(chunks), effective_model)
            result = _FileResult(status="indexed", rel_path=rel, dims=dims, chunk_count=len(chunks))

    # Update progress after semaphore release — always runs regardless of outcome
    # (single-threaded asyncio = safe to mutate shared dict)
    if progress_state is not None:
        progress_state["n"] += 1
        from app.services import progress
        progress.update(progress_state["op_id"], current=progress_state["n"], message=rel)

    return result


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
    _progress_op_id: str | None = None,
    skip_stale_cleanup: bool = False,
) -> dict:
    """
    Index a directory for semantic search.

    - bot_id=None: cross-bot index (accessible to all bots).
    - client_id=None: cross-client index (accessible from all channels/clients).
    - force=True: bypass cooldown (used on startup and by the agent tool).
    - file_paths: if provided, only re-index those specific files (watcher use).
    - skip_stale_cleanup: if True, don't remove DB entries for files not on disk
      (use when indexing a subset of patterns, e.g. memory-only).
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
    def _accept(p: Path) -> bool:
        """Return True if the file should be indexed (passes all filters)."""
        if not p.is_file():
            return False
        parts = p.relative_to(root_path).parts
        if any(part in _SKIP_DIRS for part in parts):
            return False
        if p.suffix.lower() in _SKIP_EXTENSIONS:
            return False
        if _is_auto_injected(parts):
            return False
        if spec:
            try:
                rel = str(PurePosixPath(p.relative_to(root_path)))
                if spec.match_file(rel):
                    return False
            except ValueError:
                pass
        return True

    if file_paths is not None:
        candidates = [
            p.resolve() for p in file_paths
            if p.is_file() and not _is_auto_injected(p.resolve().relative_to(root_path).parts)
        ]
    elif segments:
        # Segment-exclusive discovery: only walk within segment path prefixes.
        # Each segment defines its own scope; files outside all segments are skipped.
        seen: set[Path] = set()
        for seg in segments:
            seg_prefix = seg["path_prefix"].rstrip("/")
            seg_dir = root_path / seg_prefix
            if not seg_dir.is_dir():
                logger.debug("Segment dir %s does not exist, skipping", seg_dir)
                continue
            seg_patterns = seg.get("patterns") or patterns
            seen |= _glob_with_exclusions(seg_dir, seg_patterns, _accept)
        candidates = list(seen)
    else:
        candidates = list(_glob_with_exclusions(root_path, patterns, _accept))

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

    # Fetch existing content_hashes + embedding_model + chunking_version in bulk
    async with async_session() as db:
        _fs_sub = (
            select(
                FilesystemChunk.file_path,
                FilesystemChunk.content_hash,
                FilesystemChunk.embedding_model,
                FilesystemChunk.metadata_["chunking_version"].as_string().label("chunking_version"),
                func.row_number().over(
                    partition_by=FilesystemChunk.file_path,
                    order_by=FilesystemChunk.id,
                ).label("_rn"),
            )
            .where(*_scope_filter())
            .subquery()
        )
        rows = (await db.execute(
            select(_fs_sub.c.file_path, _fs_sub.c.content_hash, _fs_sub.c.embedding_model, _fs_sub.c.chunking_version)
            .where(_fs_sub.c._rn == 1)
        )).all()
    existing_hashes: dict[str, str] = {row.file_path: row.content_hash for row in rows}
    existing_models: dict[str, str | None] = {row.file_path: row.embedding_model for row in rows}
    existing_versions: dict[str, str | None] = {row.file_path: row.chunking_version for row in rows}

    # Resolve the base embedding model for this index run
    base_model = embedding_model or settings.EMBEDDING_MODEL

    # Process candidates concurrently
    scope_conds = _scope_filter()
    sem = asyncio.Semaphore(settings.FS_INDEX_CONCURRENCY)

    # Progress tracking (if an operation is registered for this call)
    progress_state: dict | None = None
    if _progress_op_id:
        from app.services import progress
        progress.update(_progress_op_id, total=len(candidates))
        progress_state = {"n": 0, "op_id": _progress_op_id}

    coros = [
        _process_file(
            path, root_path, bot_id, client_id,
            base_model, segments,
            existing_hashes, existing_models, existing_versions,
            scope_conds, sem, progress_state,
        )
        for path in candidates
    ]
    results = await asyncio.gather(*coros, return_exceptions=True)

    # Aggregate stats from results
    for r in results:
        if isinstance(r, BaseException):
            logger.exception("Unexpected error in _process_file: %s", r)
            stats["errors"] += 1
        elif r.status == "indexed":
            stats["indexed"] += 1
        elif r.status == "skipped":
            stats["skipped"] += 1
        elif r.status == "error":
            stats["errors"] += 1

    # Remove stale DB entries for files no longer on disk (full re-index only)
    if file_paths is None and not skip_stale_cleanup:
        disk_set = {str(PurePosixPath(p.relative_to(root_path))) for p in candidates}
        stale = set(existing_hashes.keys()) - disk_set
        # When using segments, protect memory files (indexed by Phase 1) from
        # being purged by the segment-based Phase 2.  But DO purge files from
        # removed segments — if a file doesn't match any current segment prefix
        # and isn't a memory file, it's orphaned.
        if segments and stale:
            # Protect memory files (indexed by Phase 1) from being purged by
            # the segment-based Phase 2.  Everything else is fair game — files
            # within current segments that were deleted from disk, AND files
            # from removed segments that are no longer in scope.
            # Standalone bots: memory/   Shared workspace bots: bots/{id}/memory/
            _memory_prefixes = ["memory/"]
            if bot_id:
                _memory_prefixes.append(f"bots/{bot_id}/memory/")
            stale = {fp for fp in stale if not any(fp.startswith(p) for p in _memory_prefixes)}
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

    # Touch indexed_at on skipped (unchanged) files so the timestamp reflects
    # "last verified" rather than "last content change".  This prevents the UI
    # from showing stale dates when indexing is running but nothing changed.
    skipped_paths = [r.rel_path for r in results if isinstance(r, _FileResult) and r.status == "skipped" and r.rel_path]
    if skipped_paths:
        try:
            async with async_session() as db:
                from sqlalchemy import text as _sa_text, bindparam
                await db.execute(
                    _sa_text(
                        "UPDATE filesystem_chunks SET indexed_at = now() "
                        "WHERE root = :rt AND "
                        + ("bot_id = :bid" if bot_id is not None else "bot_id IS NULL")
                        + " AND "
                        + ("client_id = :cid" if client_id is not None else "client_id IS NULL")
                        + " AND file_path = ANY(:fps)"
                    ).bindparams(
                        rt=str(root_path),
                        **({"bid": bot_id} if bot_id is not None else {}),
                        **({"cid": client_id} if client_id is not None else {}),
                        fps=skipped_paths,
                    )
                )
                await db.commit()
        except Exception:
            logger.warning("Failed to touch indexed_at for skipped files (bot=%s, root=%s)", bot_id, root_path)

    # Backfill tsvector for any chunks still missing it (e.g. pre-migration rows
    # that were skipped because content_hash was unchanged).  Non-fatal.
    try:
        async with async_session() as db:
            from sqlalchemy import text as _sa_text
            if bot_id is not None:
                result = await db.execute(_sa_text(
                    "UPDATE filesystem_chunks SET tsv = to_tsvector('english', content) "
                    "WHERE root = :rt AND bot_id = :bid AND tsv IS NULL"
                ).bindparams(rt=str(root_path), bid=bot_id))
            else:
                result = await db.execute(_sa_text(
                    "UPDATE filesystem_chunks SET tsv = to_tsvector('english', content) "
                    "WHERE root = :rt AND bot_id IS NULL AND tsv IS NULL"
                ).bindparams(rt=str(root_path)))
            await db.commit()
            backfilled = result.rowcount
            if backfilled:
                logger.info("Backfilled tsvector for %d chunks (bot=%s, root=%s)", backfilled, bot_id, root_path)
    except Exception:
        logger.warning("TSVector backfill failed for bot=%s root=%s", bot_id, root_path)

    logger.info(
        "Indexed %s for bot %s client %s: %d new, %d skipped, %d removed, %d errors",
        root, bot_id, client_id, stats["indexed"], stats["skipped"], stats["removed"], stats["errors"],
    )
    return stats


async def cleanup_stale_roots(bot_id: str, valid_roots: list[str]) -> int:
    """Delete chunks for a bot whose root no longer matches any current root.

    Call on startup after the workspace root computation changes to purge
    orphaned chunks from old root paths.  Returns the number of deleted rows.
    """
    resolved = [str(Path(r).resolve()) for r in valid_roots]
    async with async_session() as db:
        result = await db.execute(
            delete(FilesystemChunk).where(
                FilesystemChunk.bot_id == bot_id,
                FilesystemChunk.root.notin_(resolved),
            )
        )
        await db.commit()
        return result.rowcount


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


async def _fs_bm25_search(
    query: str,
    bot_id: str | None,
    client_id: str | None,
    abs_roots: list[str] | None,
    top_k: int,
    included_prefixes: list[str] | None = None,
    excluded_prefixes: list[str] | None = None,
    excluded_paths: list[str] | None = None,
    metadata_equals: dict[str, Any] | None = None,
    metadata_not_equals: dict[str, Any] | None = None,
) -> list[tuple[str, str, str | None, int | None, int | None, float]]:
    """BM25 full-text search on filesystem_chunks. Returns [] on SQLite or error."""
    try:
        from sqlalchemy import text as _sa_text
        async with async_session() as db:
            dialect = db.bind.dialect.name if db.bind else ""
            if dialect != "postgresql":
                return []

            # Build scope WHERE clauses
            wheres = ["tsv IS NOT NULL", "tsv @@ plainto_tsquery('english', :q)"]
            params: dict = {"q": query, "lim": top_k * 2}

            if bot_id is not None:
                wheres.append("(bot_id = :bid OR bot_id IS NULL)")
                params["bid"] = bot_id
            else:
                wheres.append("bot_id IS NULL")

            if client_id is not None:
                wheres.append("(client_id = :cid OR client_id IS NULL)")
                params["cid"] = client_id
            else:
                wheres.append("client_id IS NULL")

            if abs_roots:
                wheres.append("root = ANY(:roots)")
                params["roots"] = abs_roots

            if included_prefixes:
                include_terms: list[str] = []
                for i, prefix in enumerate(dict.fromkeys(p for p in included_prefixes if p)):
                    normalized, exact = _normalize_path_prefix(prefix)
                    param_name = f"incl_{i}"
                    include_terms.append(f"(file_path LIKE :{param_name} OR file_path = :{param_name}_exact)")
                    params[param_name] = normalized + "%"
                    params[f"{param_name}_exact"] = exact
                if include_terms:
                    wheres.append(f"({' OR '.join(include_terms)})")

            # Apply channel-gated segment exclusion
            if excluded_prefixes:
                for i, prefix in enumerate(excluded_prefixes):
                    normalized, exact = _normalize_path_prefix(prefix)
                    param_name = f"excl_{i}"
                    wheres.append(f"NOT (file_path LIKE :{param_name} OR file_path = :{param_name}_exact)")
                    params[param_name] = normalized + "%"
                    params[f"{param_name}_exact"] = exact
            if excluded_paths:
                for i, path in enumerate(excluded_paths):
                    param_name = f"expath_{i}"
                    wheres.append(f"file_path != :{param_name}")
                    params[param_name] = path
            for i, (key, value) in enumerate((metadata_equals or {}).items()):
                key_param = f"meta_eq_key_{i}"
                value_param = f"meta_eq_val_{i}"
                wheres.append(f"(metadata_ ->> :{key_param}) = :{value_param}")
                params[key_param] = str(key)
                params[value_param] = str(value)
            for i, (key, value) in enumerate((metadata_not_equals or {}).items()):
                key_param = f"meta_ne_key_{i}"
                value_param = f"meta_ne_val_{i}"
                wheres.append(f"((metadata_ ->> :{key_param}) IS NULL OR (metadata_ ->> :{key_param}) != :{value_param})")
                params[key_param] = str(key)
                params[value_param] = str(value)

            sql = _sa_text(f"""
                SELECT content, file_path, symbol, start_line, end_line,
                       ts_rank(tsv, plainto_tsquery('english', :q)) AS rank
                FROM filesystem_chunks
                WHERE {' AND '.join(wheres)}
                ORDER BY rank DESC
                LIMIT :lim
            """).bindparams(**params)

            result = await db.execute(sql)
            return [
                (row[0], row[1], row[2], row[3], row[4], float(row[5]))
                for row in result.all()
            ]
    except Exception:
        logger.debug("FS BM25 search failed, falling back to vector-only", exc_info=True)
        return []


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
    include_path_prefixes: list[str] | None = None,
    exclude_path_prefixes: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    metadata_equals: dict[str, Any] | None = None,
    metadata_not_equals: dict[str, Any] | None = None,
) -> tuple[list[str], float]:
    """Legacy-shape wrapper around :func:`retrieve_filesystem_chunks`.

    Returns ``(formatted_chunks, best_similarity)``. New callers should
    prefer ``retrieve_filesystem_chunks`` so trace events can attribute
    admitted excerpts to specific files and similarities.
    """
    chunks, best_sim = await _retrieve_filesystem_rows(
        query,
        bot_id,
        client_id=client_id,
        roots=roots,
        top_k=top_k,
        threshold=threshold,
        embedding_model=embedding_model,
        segments=segments,
        channel_id=channel_id,
        include_path_prefixes=include_path_prefixes,
        exclude_path_prefixes=exclude_path_prefixes,
        exclude_paths=exclude_paths,
        metadata_equals=metadata_equals,
        metadata_not_equals=metadata_not_equals,
    )
    return [c.formatted for c in chunks], best_sim


async def _retrieve_filesystem_rows(
    query: str,
    bot_id: str | None,
    client_id: str | None = None,
    roots: list[str] | None = None,
    top_k: int | None = None,
    threshold: float | None = None,
    embedding_model: str | None = None,
    segments: list[dict] | None = None,
    channel_id: str | None = None,
    include_path_prefixes: list[str] | None = None,
    exclude_path_prefixes: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    metadata_equals: dict[str, Any] | None = None,
    metadata_not_equals: dict[str, Any] | None = None,
) -> tuple[list[FsRetrievalChunk], float]:
    """Embed query, cosine-search filesystem_chunks, return per-chunk structured records.

    Scope semantics (matches knowledge system):
    - bot_id: returns chunks where chunk.bot_id == bot_id OR chunk.bot_id IS NULL
    - client_id: returns chunks where chunk.client_id == client_id OR chunk.client_id IS NULL
    - channel_id: segments with a channel_id are skipped unless the active channel matches
    - include_path_prefixes: optional positive path filter; only matching chunks are retrieved
    - exclude_path_prefixes / exclude_paths: retrieval-time path filters applied before formatting
    - metadata_equals / metadata_not_equals: JSON metadata filters applied before ranking
    """
    top_k = top_k or settings.FS_INDEX_TOP_K
    threshold = threshold if threshold is not None else settings.FS_INDEX_SIMILARITY_THRESHOLD
    base_model = embedding_model or settings.EMBEDDING_MODEL

    # Build list of path prefixes to exclude (channel-gated segments that don't match)
    _excl = _excluded_prefixes(segments, channel_id)
    if exclude_path_prefixes:
        _excl = list(dict.fromkeys([*_excl, *exclude_path_prefixes]))

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

    _path_include_filters = _path_prefix_include_filters(include_path_prefixes)
    _path_excl_filters = _path_prefix_exclude_filters(_excl)
    if exclude_paths:
        for path in exclude_paths:
            _path_excl_filters.append(FilesystemChunk.file_path != path)
    _metadata_filters = []
    for key, value in (metadata_equals or {}).items():
        _metadata_filters.append(FilesystemChunk.metadata_[str(key)].as_string() == str(value))
    for key, value in (metadata_not_equals or {}).items():
        expr = FilesystemChunk.metadata_[str(key)].as_string()
        _metadata_filters.append(or_(expr.is_(None), expr != str(value)))

    # Fetch more results when hybrid search will fuse them
    vector_limit = top_k * 2 if settings.HYBRID_SEARCH_ENABLED else top_k

    # Single-model fast path (most common case: no segments or all same model)
    if len(unique_models) == 1:
        model = next(iter(unique_models))
        try:
            query_embedding = await embed_text(query, model=model)
        except Exception:
            logger.exception("Failed to embed query for filesystem retrieval")
            return [], 0.0

        from app.agent.vector_ops import halfvec_cosine_distance
        distance_expr = halfvec_cosine_distance(FilesystemChunk.embedding, query_embedding)
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
            .where(bot_filter, client_filter, model_filter, *_path_include_filters, *_path_excl_filters, *_metadata_filters)
            .order_by(distance_expr)
            .limit(vector_limit)
        )
        if abs_roots:
            stmt = stmt.where(FilesystemChunk.root.in_(abs_roots))

        try:
            async with async_session() as db:
                rows = (await db.execute(stmt)).all()
        except Exception:
            logger.exception("Filesystem retrieval query failed")
            return [], 0.0

        if settings.HYBRID_SEARCH_ENABLED:
            bm25_rows = await _fs_bm25_search(
                query,
                bot_id,
                client_id,
                abs_roots,
                top_k,
                included_prefixes=include_path_prefixes,
                excluded_prefixes=_excl or None,
                excluded_paths=exclude_paths,
                metadata_equals=metadata_equals,
                metadata_not_equals=metadata_not_equals,
            )
            if bm25_rows:
                return _detailed_hybrid_fs_results(rows, bm25_rows, threshold, top_k, query)

        return _detailed_retrieval_results(rows, threshold, query, top_k)

    # Multi-model path: embed query once per unique model, query separately, merge
    all_rows: list = []
    for model in unique_models:
        try:
            query_embedding = await embed_text(query, model=model)
        except Exception:
            logger.exception("Failed to embed query with model %s", model)
            continue

        distance_expr = halfvec_cosine_distance(FilesystemChunk.embedding, query_embedding)
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
            .where(bot_filter, client_filter, model_filter, *_path_include_filters, *_path_excl_filters, *_metadata_filters)
            .order_by(distance_expr)
            .limit(vector_limit)
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
    all_rows = all_rows[:vector_limit]

    if settings.HYBRID_SEARCH_ENABLED:
        bm25_rows = await _fs_bm25_search(
            query,
            bot_id,
            client_id,
            abs_roots,
            top_k,
            included_prefixes=include_path_prefixes,
            excluded_prefixes=_excl or None,
            excluded_paths=exclude_paths,
            metadata_equals=metadata_equals,
            metadata_not_equals=metadata_not_equals,
        )
        if bm25_rows:
            return _detailed_hybrid_fs_results(all_rows, bm25_rows, threshold, top_k, query)

    return _detailed_retrieval_results(all_rows, threshold, query, top_k)


@dataclass(frozen=True)
class FsRetrievalChunk:
    """Per-chunk retrieval result with the structured trace fields agents need.

    ``formatted`` is the same ``[File: ...]\\n\\n<content>`` block the legacy
    ``retrieve_filesystem_context`` returns. Carry it alongside the structured
    fields so callers do not have to re-format.
    """

    file_path: str
    similarity: float
    chars: int
    formatted: str


def _format_retrieval_results(
    rows: list, threshold: float, query: str, top_k: int | None = None,
) -> tuple[list[str], float]:
    """Format DB rows into retrieval results (legacy string-only shape)."""
    detailed, best_sim = _detailed_retrieval_results(rows, threshold, query, top_k)
    return [c.formatted for c in detailed], best_sim


def _detailed_retrieval_results(
    rows: list, threshold: float, query: str, top_k: int | None = None,
) -> tuple[list[FsRetrievalChunk], float]:
    """Format DB rows into ``FsRetrievalChunk`` records keyed by per-chunk similarity."""
    if not rows:
        return [], 0.0

    best_sim = 1.0 - rows[0].distance
    logger.info(
        "Filesystem retrieval: best_similarity=%.3f threshold=%.3f query=%s...",
        best_sim, threshold, query[:60],
    )

    results: list[FsRetrievalChunk] = []
    limit = int(top_k or settings.FS_INDEX_TOP_K)
    for row in rows:
        similarity = 1.0 - row.distance
        if similarity < threshold:
            break
        formatted = _format_fs_row(row.content, row.file_path, row.symbol, row.start_line, row.end_line)
        results.append(FsRetrievalChunk(
            file_path=row.file_path,
            similarity=similarity,
            chars=len(formatted),
            formatted=formatted,
        ))
        if len(results) >= limit:
            break

    return results, best_sim


def _format_fs_row(
    content: str, file_path: str, symbol: str | None,
    start_line: int | None, end_line: int | None,
) -> str:
    """Format a single filesystem chunk for display."""
    location = file_path
    if symbol:
        location += f" ({symbol})"
    if start_line and end_line:
        location += f" L{start_line}–{end_line}"
    return f"[File: {location}]\n\n{content}"


def _format_hybrid_fs_results(
    vector_rows: list, bm25_rows: list, threshold: float, top_k: int, query: str,
) -> tuple[list[str], float]:
    """Fuse vector and BM25 filesystem results using RRF (legacy shape)."""
    detailed, best_sim = _detailed_hybrid_fs_results(vector_rows, bm25_rows, threshold, top_k, query)
    return [c.formatted for c in detailed], best_sim


def _detailed_hybrid_fs_results(
    vector_rows: list, bm25_rows: list, threshold: float, top_k: int, query: str,
) -> tuple[list[FsRetrievalChunk], float]:
    """Fuse vector and BM25 filesystem results using RRF; emit structured chunks."""
    from app.agent.hybrid_search import reciprocal_rank_fusion

    k = settings.HYBRID_SEARCH_RRF_K

    # Build ranked lists using (content, file_path) as dedup identity
    vector_list = [
        (row.content, row.file_path, row.symbol, row.start_line, row.end_line)
        for row in vector_rows
    ]
    bm25_list = [
        (content, file_path, symbol, start_line, end_line)
        for content, file_path, symbol, start_line, end_line, rank in bm25_rows
    ]

    fused = reciprocal_rank_fusion(vector_list, bm25_list, k=k)

    # Build similarity lookup keyed by (content, file_path) for accurate matching
    vector_sims: dict[tuple[str, str], float] = {
        (row.content, row.file_path): 1.0 - row.distance for row in vector_rows
    }
    bm25_set = {(content, file_path) for content, file_path, _, _, _, _ in bm25_rows}

    best_similarity = max(vector_sims.values()) if vector_sims else 0.0

    results: list[FsRetrievalChunk] = []
    for (item, rrf_score) in fused:
        content, file_path, symbol, start_line, end_line = item
        lookup_key = (content, file_path)
        vec_sim = vector_sims.get(lookup_key)

        chunk_sim: float | None = None
        if vec_sim is not None and vec_sim >= threshold:
            chunk_sim = vec_sim
        elif lookup_key in bm25_set:
            # BM25 match — include regardless of vector threshold; surface the
            # vector similarity if known so traces still get a numeric anchor.
            chunk_sim = vec_sim if vec_sim is not None else 0.0

        if chunk_sim is None:
            continue

        formatted = _format_fs_row(content, file_path, symbol, start_line, end_line)
        results.append(FsRetrievalChunk(
            file_path=file_path,
            similarity=chunk_sim,
            chars=len(formatted),
            formatted=formatted,
        ))

        if len(results) >= top_k:
            break

    logger.info(
        "Hybrid FS retrieval: %d vector + %d BM25 → %d fused chunks (query=%s...)",
        len(vector_rows), len(bm25_rows), len(results), query[:60],
    )

    return results, best_similarity


async def retrieve_filesystem_chunks(
    query: str,
    bot_id: str | None,
    client_id: str | None = None,
    roots: list[str] | None = None,
    top_k: int | None = None,
    threshold: float | None = None,
    embedding_model: str | None = None,
    segments: list[dict] | None = None,
    channel_id: str | None = None,
    include_path_prefixes: list[str] | None = None,
    exclude_path_prefixes: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    metadata_equals: dict[str, Any] | None = None,
    metadata_not_equals: dict[str, Any] | None = None,
) -> tuple[list[FsRetrievalChunk], float]:
    """Like :func:`retrieve_filesystem_context` but returns per-chunk structured records.

    Used by the bot-curated memory/reference and bot knowledge-base injectors so
    trace events can attribute admitted chunks to specific files and similarity
    scores. The legacy string-only entry point still works for callers that just
    need to drop the formatted excerpts into a system message.
    """
    chunks, best_sim = await _retrieve_filesystem_rows(
        query,
        bot_id,
        client_id=client_id,
        roots=roots,
        top_k=top_k,
        threshold=threshold,
        embedding_model=embedding_model,
        segments=segments,
        channel_id=channel_id,
        include_path_prefixes=include_path_prefixes,
        exclude_path_prefixes=exclude_path_prefixes,
        exclude_paths=exclude_paths,
        metadata_equals=metadata_equals,
        metadata_not_equals=metadata_not_equals,
    )
    return chunks, best_sim
