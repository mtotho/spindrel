"""Bot-readable internal docs.

Mirrors the read shape of `app/agent/skills.py` for the `docs/` tree. No DB,
no embedding — `docs/` is shipped read-only with the image (`COPY docs/ docs/`
in the Dockerfile) and addressed by extension-less ID, e.g. ``get_doc(
"reference/widgets/sdk")`` -> ``docs/reference/widgets/sdk.md``.

Out-of-scope here: embedding, write paths, arbitrary repo files. Skill
discovery is unchanged; this is a separate fetch surface.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

DOCS_DIR = Path("docs")


@dataclass(frozen=True)
class DocSummary:
    id: str
    title: str | None
    summary: str | None
    tags: list[str]


@dataclass(frozen=True)
class Doc:
    id: str
    title: str | None
    summary: str | None
    tags: list[str]
    body: str


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        return {}, content
    import yaml
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except Exception:
        meta = {}
    body = content[match.end():]
    return (meta if isinstance(meta, dict) else {}), body


def _resolve_doc_path(doc_id: str, docs_dir: Path | None = None) -> Path | None:
    """Resolve a doc ID to a real path under docs_dir, or None if unsafe / missing.

    Rejects IDs containing ``..`` segments or starting with ``/``. Accepts the
    ID with or without a trailing ``.md``.
    """
    if docs_dir is None:
        docs_dir = DOCS_DIR
    if not doc_id or doc_id.startswith("/") or doc_id.startswith("\\"):
        return None
    if ".." in doc_id.replace("\\", "/").split("/"):
        return None

    rel = doc_id[:-3] if doc_id.endswith(".md") else doc_id
    candidate = (docs_dir / f"{rel}.md").resolve()
    base = docs_dir.resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def load_doc(doc_id: str, docs_dir: Path | None = None) -> Doc | None:
    if docs_dir is None:
        docs_dir = DOCS_DIR
    path = _resolve_doc_path(doc_id, docs_dir)
    if path is None:
        return None
    raw = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(raw)
    rel = path.relative_to(docs_dir.resolve()) if path.is_absolute() else path.relative_to(docs_dir)
    canonical_id = str(rel.with_suffix("")).replace("\\", "/")
    tags = meta.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    return Doc(
        id=canonical_id,
        title=meta.get("title") if isinstance(meta.get("title"), str) else None,
        summary=meta.get("summary") if isinstance(meta.get("summary"), str) else None,
        tags=[str(t) for t in tags],
        body=body,
    )


def list_docs(area: str | None = None, docs_dir: Path | None = None) -> list[DocSummary]:
    """Walk ``docs/`` and return frontmatter summaries.

    ``area`` filters by top-level directory (e.g. ``"reference"`` ->
    ``docs/reference/**``). Files outside that subtree are skipped. Files
    without YAML frontmatter still appear with empty title/summary/tags so
    bots can discover them.
    """
    if docs_dir is None:
        docs_dir = DOCS_DIR
    if not docs_dir.exists() or not docs_dir.is_dir():
        return []

    if area:
        if area.startswith("/") or ".." in area.split("/"):
            return []
        root = docs_dir / area
        if not root.is_dir():
            return []
    else:
        root = docs_dir

    results: list[DocSummary] = []
    for path in sorted(root.rglob("*.md")):
        try:
            rel = path.relative_to(docs_dir)
        except ValueError:
            continue
        doc_id = str(rel.with_suffix("")).replace("\\", "/")
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            continue
        meta, _ = _parse_frontmatter(raw)
        tags = meta.get("tags") or []
        if not isinstance(tags, list):
            tags = []
        results.append(
            DocSummary(
                id=doc_id,
                title=meta.get("title") if isinstance(meta.get("title"), str) else None,
                summary=meta.get("summary") if isinstance(meta.get("summary"), str) else None,
                tags=[str(t) for t in tags],
            )
        )
    return results
