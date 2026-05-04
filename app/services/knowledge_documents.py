"""Unified Knowledge Document primitive.

Knowledge Documents are markdown files with preserving YAML frontmatter. Notes
are one scope-binding of this primitive; user/bot scope support lands here so
capture can write to the same substrate instead of a parallel store.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import HTTPException

from app.services.file_versions import save_file_backup

KNOWLEDGE_DOCUMENT_KIND = "knowledge_document"
DEFAULT_KNOWLEDGE_DOCUMENT_TYPE = "note"
KNOWLEDGE_DOCUMENTS_DIR = "notes"

KnowledgeScope = Literal["channel", "project", "user", "bot"]
KnowledgeAction = Literal["list", "read", "write", "accept", "reject", "session_binding", "assist"]
SessionBindingMode = Literal["dedicated", "inline", "attached"]

_SLUG_RE = re.compile(r"[^a-z0-9._-]+")
_DEFAULT_FRONTMATTER_ORDER = (
    "spindrel_kind",
    "entry_id",
    "type",
    "status",
    "title",
    "category",
    "summary",
    "tags",
    "user_id",
    "bot_id",
    "channel_id",
    "project_id",
    "session_binding",
    "created_at",
    "updated_at",
)


@dataclass(frozen=True)
class KnowledgeDocumentSurface:
    root: str
    kb_rel: str
    scope: KnowledgeScope
    channel_id: str | None = None
    project_id: str | None = None
    user_id: str | None = None
    bot_id: str | None = None
    extra_scope: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.scope == "channel" and not self.channel_id:
            raise ValueError("channel scope requires channel_id")
        if self.scope == "project" and not self.project_id:
            raise ValueError("project scope requires project_id")
        if self.scope == "user" and not self.user_id:
            raise ValueError("user scope requires user_id")
        if self.scope == "bot" and not self.bot_id:
            raise ValueError("bot scope requires bot_id")
        invalid = {
            "channel": ["user_id", "bot_id"],
            "project": ["user_id", "bot_id"],
            "user": ["channel_id", "project_id", "bot_id"],
            "bot": ["channel_id", "project_id", "user_id"],
        }[self.scope]
        for field_name in invalid:
            if getattr(self, field_name):
                raise ValueError(f"{self.scope} scope cannot set {field_name}")

    @property
    def documents_root(self) -> str:
        return os.path.join(self.root, self.kb_rel, KNOWLEDGE_DOCUMENTS_DIR)

    @property
    def notes_root(self) -> str:
        return self.documents_root

    def workspace_path_for(self, rel_path: str) -> str:
        return f"{self.kb_rel}/{rel_path}"

    def tool_path_for(self, rel_path: str) -> str:
        workspace_path = self.workspace_path_for(rel_path)
        if self.scope == "channel" and self.channel_id:
            return f"/workspace/channels/{self.channel_id}/{workspace_path}"
        if self.scope == "user" and self.user_id:
            return f"/workspace/users/{self.user_id}/knowledge-base/{rel_path}"
        if self.scope == "bot" and self.bot_id:
            return f"/workspace/bots/{self.bot_id}/{workspace_path}"
        return workspace_path


def user_knowledge_surface(*, workspace_root: str, user_id: str) -> KnowledgeDocumentSurface:
    _validate_scope_id(user_id, "user_id")
    return KnowledgeDocumentSurface(
        root=os.path.realpath(workspace_root),
        kb_rel=f"users/{user_id}/knowledge-base",
        scope="user",
        user_id=user_id,
    )


def bot_knowledge_surface(*, workspace_root: str, bot_id: str) -> KnowledgeDocumentSurface:
    _validate_scope_id(bot_id, "bot_id")
    return KnowledgeDocumentSurface(
        root=os.path.realpath(workspace_root),
        kb_rel=f"bots/{bot_id}/knowledge-base",
        scope="bot",
        bot_id=bot_id,
    )


def slugify_document_title(title: str) -> str:
    base = title.strip().lower()
    base = re.sub(r"\s+", "-", base)
    base = _SLUG_RE.sub("-", base).strip("-._")
    return (base or "untitled-note")[:80]


def _validate_scope_id(value: str, label: str) -> None:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"invalid {label}")


def document_path_for_slug(slug: str) -> str:
    clean = slugify_document_title(slug.removesuffix(".md"))
    return f"{KNOWLEDGE_DOCUMENTS_DIR}/{clean}.md"


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_entry_id() -> str:
    return uuid.uuid4().hex


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    if not content.startswith("---\n"):
        return {}, content
    end = content.find("\n---", 4)
    if end < 0:
        return {}, content
    raw = content[4:end]
    body_start = end + len("\n---")
    while content[body_start:body_start + 1] in {"\r", "\n"}:
        body_start += 1
    try:
        parsed = yaml.safe_load(raw) if raw.strip() else {}
    except yaml.YAMLError:
        parsed = {}
    return (parsed if isinstance(parsed, dict) else {}), content[body_start:]


def render_frontmatter(meta: dict[str, Any]) -> str:
    ordered: dict[str, Any] = {}
    for key in _DEFAULT_FRONTMATTER_ORDER:
        if key in meta and meta[key] not in (None, ""):
            ordered[key] = meta[key]
    for key, value in meta.items():
        if key not in ordered and value not in (None, ""):
            ordered[key] = value
    dumped = yaml.safe_dump(
        ordered,
        sort_keys=False,
        allow_unicode=False,
        default_flow_style=False,
    ).strip()
    return f"---\n{dumped}\n---\n\n"


def default_session_binding(mode: SessionBindingMode = "dedicated", session_id: str | None = None) -> dict[str, Any]:
    if mode not in {"dedicated", "inline", "attached"}:
        raise ValueError(f"unsupported session binding mode: {mode}")
    if mode == "attached" and not session_id:
        raise ValueError("attached session binding requires session_id")
    return {"mode": mode, "session_id": session_id}


def ensure_document_frontmatter(
    content: str,
    *,
    title: str | None = None,
    surface: KnowledgeDocumentSurface | None = None,
    defaults: dict[str, Any] | None = None,
) -> str:
    meta, body = parse_frontmatter(content)
    now = utc_now()
    merged = {**(defaults or {}), **meta}
    merged.setdefault("spindrel_kind", KNOWLEDGE_DOCUMENT_KIND)
    merged.setdefault("entry_id", new_entry_id())
    merged.setdefault("type", DEFAULT_KNOWLEDGE_DOCUMENT_TYPE)
    merged.setdefault("status", "accepted")
    merged.setdefault("title", title or _title_from_body(body) or "Untitled note")
    merged.setdefault("tags", [])
    merged.setdefault("session_binding", default_session_binding())
    merged.setdefault("created_at", now)
    if surface is not None:
        if getattr(surface, "user_id", None):
            merged.setdefault("user_id", surface.user_id)
        if getattr(surface, "bot_id", None):
            merged.setdefault("bot_id", surface.bot_id)
        if getattr(surface, "channel_id", None):
            merged.setdefault("channel_id", surface.channel_id)
        if getattr(surface, "project_id", None):
            merged.setdefault("project_id", surface.project_id)
    merged["updated_at"] = now
    return render_frontmatter(merged) + body.lstrip("\n")


def ensure_documents_dir(surface: KnowledgeDocumentSurface) -> str:
    root = surface.documents_root
    os.makedirs(root, exist_ok=True)
    return root


def resolve_document_abs_path(surface: KnowledgeDocumentSurface, slug: str) -> tuple[str, str]:
    rel = document_path_for_slug(slug)
    root = os.path.realpath(os.path.join(surface.root, surface.kb_rel))
    target = os.path.realpath(os.path.join(root, rel))
    if not target.startswith(root + os.sep):
        raise HTTPException(404, "Knowledge document not found")
    return target, rel


def serialize_document(surface: KnowledgeDocumentSurface, abs_path: str) -> dict[str, Any]:
    content = Path(abs_path).read_text(encoding="utf-8")
    meta, body = parse_frontmatter(content)
    stat = os.stat(abs_path)
    title = str(meta.get("title") or _title_from_body(body) or Path(abs_path).stem.replace("-", " ").title())
    tags = meta.get("tags") if isinstance(meta.get("tags"), list) else []
    rel = os.path.relpath(abs_path, os.path.join(surface.root, surface.kb_rel)).replace(os.sep, "/")
    return {
        "slug": Path(abs_path).stem,
        "entry_id": meta.get("entry_id"),
        "type": meta.get("type") or DEFAULT_KNOWLEDGE_DOCUMENT_TYPE,
        "status": meta.get("status") or "accepted",
        "path": rel,
        "workspace_path": surface.workspace_path_for(rel),
        "tool_path": surface.tool_path_for(rel),
        "title": title,
        "summary": meta.get("summary") or "",
        "excerpt": _excerpt(body),
        "category": meta.get("category") or "",
        "tags": tags,
        "word_count": _word_count(body),
        "bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
        "scope": surface.scope,
        "session_binding": _normalize_session_binding(meta.get("session_binding")),
        "content_hash": content_hash(content),
        "frontmatter": meta,
    }


def list_documents(surface: KnowledgeDocumentSurface, *, status: str | None = None) -> list[dict[str, Any]]:
    ensure_documents_dir(surface)
    docs = []
    for path in sorted(Path(surface.documents_root).glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        if not path.is_file():
            continue
        doc = serialize_document(surface, str(path))
        if status is None or doc.get("status") == status:
            docs.append(doc)
    return docs


def create_document(
    surface: KnowledgeDocumentSurface,
    *,
    title: str,
    content: str | None = None,
    slug: str | None = None,
    frontmatter: dict[str, Any] | None = None,
    session_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_documents_dir(surface)
    base_slug = slugify_document_title(slug or title)
    candidate = base_slug
    index = 1
    while True:
        abs_path, _rel = resolve_document_abs_path(surface, candidate)
        if not os.path.exists(abs_path):
            break
        index += 1
        candidate = f"{base_slug}-{index}"
    body = content if content is not None else f"# {title.strip() or 'Untitled note'}\n\n"
    defaults = dict(frontmatter or {})
    if session_binding is not None:
        defaults["session_binding"] = session_binding
    doc_content = ensure_document_frontmatter(body, title=title.strip() or "Untitled note", surface=surface, defaults=defaults)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    Path(abs_path).write_text(doc_content, encoding="utf-8")
    return {**serialize_document(surface, abs_path), "content": doc_content}


def read_document(surface: KnowledgeDocumentSurface, slug: str) -> dict[str, Any]:
    abs_path, _rel = resolve_document_abs_path(surface, slug)
    if not os.path.isfile(abs_path):
        raise HTTPException(404, "Knowledge document not found")
    content = Path(abs_path).read_text(encoding="utf-8")
    return {**serialize_document(surface, abs_path), "content": content, "content_hash": content_hash(content)}


def write_document(surface: KnowledgeDocumentSurface, slug: str, content: str, base_hash: str | None) -> dict[str, Any]:
    abs_path, _rel = resolve_document_abs_path(surface, slug)
    if not os.path.isfile(abs_path):
        raise HTTPException(404, "Knowledge document not found")
    current = Path(abs_path).read_text(encoding="utf-8")
    current_hash = content_hash(current)
    if base_hash and base_hash != current_hash:
        raise HTTPException(status_code=409, detail={"message": "Knowledge document changed on disk", "content_hash": current_hash, "content": current})
    next_content = ensure_document_frontmatter(content, surface=surface)
    save_file_backup(abs_path)
    Path(abs_path).write_text(next_content, encoding="utf-8")
    return {**serialize_document(surface, abs_path), "content": next_content, "content_hash": content_hash(next_content)}


def set_document_status(surface: KnowledgeDocumentSurface, slug: str, status: str) -> dict[str, Any]:
    doc = read_document(surface, slug)
    meta, body = parse_frontmatter(doc["content"])
    meta["status"] = status
    content = render_frontmatter(meta) + body.lstrip("\n")
    return write_document(surface, slug, content, doc["content_hash"])


def delete_document(surface: KnowledgeDocumentSurface, slug: str) -> dict[str, Any]:
    doc = read_document(surface, slug)
    abs_path, _rel = resolve_document_abs_path(surface, slug)
    save_file_backup(abs_path)
    os.remove(abs_path)
    return doc


def update_session_binding(surface: KnowledgeDocumentSurface, slug: str, binding: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_session_binding(binding)
    doc = read_document(surface, slug)
    meta, body = parse_frontmatter(doc["content"])
    meta["session_binding"] = normalized
    content = render_frontmatter(meta) + body.lstrip("\n")
    return write_document(surface, slug, content, doc["content_hash"])


def authorize_knowledge_document(actor: Any, surface: KnowledgeDocumentSurface, action: KnowledgeAction) -> None:
    """Central authorization seam for Knowledge Document actions.

    Route-level scope checks still gate channel/project calls. This seam adds
    the per-user hard boundary needed once user-scope documents exist.
    """
    if getattr(actor, "is_admin", False):
        return
    if surface.scope == "user":
        actor_id = str(getattr(actor, "id", "") or "")
        if actor_id and actor_id == str(surface.user_id):
            return
        raise HTTPException(status_code=403, detail="Knowledge document belongs to another user")
    if surface.scope == "bot" and action in {"accept", "reject"}:
        raise HTTPException(status_code=403, detail="Admin required for bot knowledge review")


def _normalize_session_binding(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        mode = str(value.get("mode") or "dedicated")
        session_id = value.get("session_id")
    else:
        mode = "dedicated"
        session_id = None
    if mode not in {"dedicated", "inline", "attached"}:
        mode = "dedicated"
        session_id = None
    if session_id is not None:
        session_id = str(session_id)
    return {"mode": mode, "session_id": session_id}


def _title_from_body(body: str) -> str | None:
    for line in body.splitlines():
        m = re.match(r"^#\s+(.+)$", line.strip())
        if m:
            return m.group(1).strip()[:120]
    return None


def _excerpt(body: str, limit: int = 220) -> str:
    text = re.sub(r"`{3}[\s\S]*?`{3}", " ", body)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_`>#\[\]()-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit].rstrip()


def _word_count(body: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", body))
