"""Shared chunking module — single source of truth for text splitting strategies.

Used by skills embedding and filesystem indexing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Bump to force re-embedding of all skills/chunks using this module.
CHUNKING_VERSION = "v2"

_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


@dataclass
class ChunkResult:
    """A single chunk produced by any chunking strategy."""
    content: str              # chunk text for storage + display
    context_prefix: str = ""  # hierarchy path, prepended for embedding only
    language: str | None = None
    symbol: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Markdown chunking (hierarchy-aware)
# ---------------------------------------------------------------------------

def chunk_markdown(
    body: str,
    *,
    source_label: str = "",
    max_chunk: int = 1500,
    preserve_hierarchy: bool = True,
) -> list[ChunkResult]:
    """Split markdown into chunks respecting header hierarchy.

    Each chunk gets a ``context_prefix`` built from ancestor headers, e.g.
    ``"# Top > ## Section > ### Sub"``.  Preamble text (before the first
    header) becomes its own chunk.

    Parameters
    ----------
    body:
        Raw markdown body (frontmatter already stripped).
    source_label:
        Human label prepended to context_prefix (e.g. ``"[Skill: Arch Linux]"``).
    max_chunk:
        Max characters per chunk.  Oversized sections are paragraph-split.
    preserve_hierarchy:
        When True, build hierarchical context_prefix from ancestor headers.
    """
    if not body or not body.strip():
        return []

    # Collect all header positions
    headers: list[tuple[int, int, str, int]] = []  # (pos, level, title, line_start)
    for m in _HEADER_RE.finditer(body):
        level = len(m.group(1))
        title = m.group(2).strip()
        headers.append((m.start(), level, title, body[:m.start()].count("\n")))

    if not headers:
        # No headers at all — single chunk
        return _split_oversized(body.strip(), "", source_label, max_chunk)

    chunks: list[ChunkResult] = []

    # Preamble: text before the first header
    preamble = body[:headers[0][0]].strip()
    if preamble:
        chunks.extend(_split_oversized(preamble, "", source_label, max_chunk))

    # Stack-based hierarchy tracking: list of (level, title)
    stack: list[tuple[int, str]] = []

    for idx, (pos, level, title, _line) in enumerate(headers):
        # Pop entries with level >= current (current replaces them)
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))

        # Build context_prefix from the full stack
        if preserve_hierarchy:
            header_path = " > ".join(
                f"{'#' * lvl} {t}" for lvl, t in stack
            )
        else:
            header_path = f"{'#' * level} {title}"

        prefix = f"{source_label}\n{header_path}" if source_label else header_path

        # Extract section content (from this header to next header of same or higher level)
        section_start = pos
        if idx + 1 < len(headers):
            section_end = headers[idx + 1][0]
        else:
            section_end = len(body)

        section_text = body[section_start:section_end].strip()
        if not section_text:
            continue

        chunks.extend(_split_oversized(section_text, prefix, source_label, max_chunk))

    return chunks


def _split_oversized(
    text: str,
    context_prefix: str,
    source_label: str,
    max_chunk: int,
) -> list[ChunkResult]:
    """Split text into chunks respecting max_chunk, using paragraph boundaries."""
    if len(text) <= max_chunk:
        return [ChunkResult(content=text, context_prefix=context_prefix)]

    paragraphs = text.split("\n\n")
    chunks: list[ChunkResult] = []
    current = ""

    for para in paragraphs:
        if current and len(current) + len(para) + 2 > max_chunk:
            chunks.append(ChunkResult(
                content=current.strip(),
                context_prefix=context_prefix,
            ))
            current = para
        else:
            current += ("\n\n" if current else "") + para

    if current.strip():
        chunks.append(ChunkResult(
            content=current.strip(),
            context_prefix=context_prefix,
        ))

    return chunks


# ---------------------------------------------------------------------------
# Sliding window chunking (boundary-aware)
# ---------------------------------------------------------------------------

_PARAGRAPH_BOUNDARY = re.compile(r"\n\n")
_SENTENCE_BOUNDARY = re.compile(r"\.\s|\.\n")


def chunk_sliding_window(
    source: str,
    *,
    source_label: str = "",
    window: int = 2000,
    overlap: int = 200,
    language: str | None = None,
    break_on_boundaries: bool = True,
) -> list[ChunkResult]:
    """Sliding window chunker that snaps to semantic boundaries.

    When ``break_on_boundaries`` is True, the window endpoint is retracted to
    the nearest paragraph (``\\n\\n``) or sentence boundary (``. `` / ``.\\n``).
    Falls back to a hard cut if no boundary exists within 20% of window size.
    Overlap start is also adjusted to the nearest paragraph boundary.

    Parameters
    ----------
    source:
        Full text to chunk.
    source_label:
        Prefix for context_prefix on each chunk (e.g. file path).
    window:
        Target chunk size in characters.
    overlap:
        Overlap between consecutive chunks in characters.
    language:
        Language tag for the chunks.
    break_on_boundaries:
        If False, use hard character cuts (legacy behavior).
    """
    if not source:
        return []

    if len(source) <= window:
        return [ChunkResult(
            content=source,
            context_prefix=source_label,
            language=language,
        )]

    chunks: list[ChunkResult] = []
    i = 0

    while i < len(source):
        raw_end = min(i + window, len(source))

        if raw_end == len(source):
            # Last chunk — take everything remaining
            end = raw_end
        elif break_on_boundaries:
            end = _find_break_point(source, i, raw_end, window)
        else:
            end = raw_end

        chunk_text = source[i:end]
        start_line = source[:i].count("\n") + 1
        end_line = source[:end].count("\n") + 1

        chunks.append(ChunkResult(
            content=chunk_text,
            context_prefix=source_label,
            language=language,
            start_line=start_line,
            end_line=end_line,
        ))

        if end >= len(source):
            break

        # Calculate next start with overlap, snapping to paragraph boundary
        next_start = end - overlap
        if break_on_boundaries and next_start > i:
            # Try to find a paragraph boundary near the overlap start
            para_match = _PARAGRAPH_BOUNDARY.search(source, next_start, end)
            if para_match:
                next_start = para_match.end()

        # Ensure forward progress
        if next_start <= i:
            next_start = end

        i = next_start

    return chunks


def _find_break_point(source: str, start: int, raw_end: int, window: int) -> int:
    """Find the best break point near raw_end, preferring paragraph then sentence boundaries."""
    # Search zone: last 20% of the window
    min_end = raw_end - int(window * 0.2)
    if min_end <= start:
        min_end = start + 1

    search_region = source[min_end:raw_end]

    # Try paragraph boundary (last \n\n in the search region)
    para_breaks = list(_PARAGRAPH_BOUNDARY.finditer(search_region))
    if para_breaks:
        return min_end + para_breaks[-1].end()

    # Try sentence boundary (last ". " or ".\n" in the search region)
    sent_breaks = list(_SENTENCE_BOUNDARY.finditer(search_region))
    if sent_breaks:
        return min_end + sent_breaks[-1].end()

    # Hard cut fallback
    return raw_end
