"""Channel/project knowledge-base Notes service."""
from __future__ import annotations

import difflib
import hashlib
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import Channel, Session
from app.services.file_versions import save_file_backup

logger = logging.getLogger(__name__)

NOTES_DIR = "notes"
NOTE_KIND = "note"
NOTE_SESSION_KIND = "note_session"

_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


@dataclass(frozen=True)
class NotesSurface:
    root: str
    kb_rel: str
    scope: str
    project_id: str | None = None

    @property
    def notes_root(self) -> str:
        return os.path.join(self.root, self.kb_rel, NOTES_DIR)


def slugify_note_title(title: str) -> str:
    base = title.strip().lower()
    base = re.sub(r"\s+", "-", base)
    base = _SLUG_RE.sub("-", base).strip("-._")
    return (base or "untitled-note")[:80]


def note_path_for_slug(slug: str) -> str:
    clean = slugify_note_title(slug.removesuffix(".md"))
    return f"{NOTES_DIR}/{clean}.md"


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_scalar(value: str) -> Any:
    raw = value.strip()
    if raw == "[]":
        return []
    if raw.startswith("[") and raw.endswith("]"):
        return [part.strip().strip('"').strip("'") for part in raw[1:-1].split(",") if part.strip()]
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    return raw


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
    meta: dict[str, Any] = {}
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = _parse_scalar(value)
    return meta, content[body_start:]


def render_frontmatter(meta: dict[str, Any]) -> str:
    lines = ["---"]
    for key in ("spindrel_kind", "title", "category", "summary", "tags", "created_at", "updated_at"):
        if key not in meta or meta[key] in (None, ""):
            continue
        value = meta[key]
        if isinstance(value, list):
            escaped = ", ".join(json.dumps(str(item)) for item in value)
            lines.append(f"{key}: [{escaped}]")
        else:
            text = str(value).replace("\n", " ").strip()
            if ":" in text or text.startswith(("[", "{", "#", "-", "*")):
                lines.append(f"{key}: {json.dumps(text)}")
            else:
                lines.append(f"{key}: {text}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def ensure_note_frontmatter(content: str, *, title: str | None = None) -> str:
    meta, body = parse_frontmatter(content)
    now = _utc_now()
    meta.setdefault("spindrel_kind", NOTE_KIND)
    meta.setdefault("title", title or _title_from_body(body) or "Untitled note")
    meta.setdefault("tags", [])
    meta.setdefault("created_at", now)
    meta["updated_at"] = now
    return render_frontmatter(meta) + body.lstrip("\n")


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


async def resolve_notes_surface(db: AsyncSession, channel: Channel, bot: Any) -> NotesSurface:
    from app.services.channel_workspace import ensure_channel_workspace, get_channel_workspace_root

    channel_root = os.path.realpath(ensure_channel_workspace(str(channel.id), bot, display_name=channel.name))
    try:
        from app.services.projects import PROJECT_KB_PATH, is_project_like_surface, resolve_channel_work_surface

        surface = await resolve_channel_work_surface(db, channel, bot)
        if is_project_like_surface(surface):
            root = os.path.realpath(surface.root_host_path)
            return NotesSurface(
                root=root,
                kb_rel=PROJECT_KB_PATH,
                scope="project",
                project_id=str(getattr(channel, "project_id", "") or "") or None,
            )
    except Exception:
        if getattr(channel, "project_id", None):
            raise HTTPException(status_code=409, detail="Project work surface could not be resolved")
    return NotesSurface(root=os.path.realpath(get_channel_workspace_root(str(channel.id), bot)), kb_rel="knowledge-base", scope="channel")


def ensure_notes_dir(surface: NotesSurface) -> str:
    root = surface.notes_root
    os.makedirs(root, exist_ok=True)
    return root


def resolve_note_abs_path(surface: NotesSurface, slug: str) -> tuple[str, str]:
    rel = note_path_for_slug(slug)
    root = os.path.realpath(os.path.join(surface.root, surface.kb_rel))
    target = os.path.realpath(os.path.join(root, rel))
    if not target.startswith(root + os.sep):
        raise HTTPException(404, "Note not found")
    return target, rel


def serialize_note(surface: NotesSurface, abs_path: str) -> dict[str, Any]:
    content = Path(abs_path).read_text(encoding="utf-8")
    meta, body = parse_frontmatter(content)
    stat = os.stat(abs_path)
    title = str(meta.get("title") or _title_from_body(body) or Path(abs_path).stem.replace("-", " ").title())
    tags = meta.get("tags") if isinstance(meta.get("tags"), list) else []
    rel = os.path.relpath(abs_path, os.path.join(surface.root, surface.kb_rel)).replace(os.sep, "/")
    return {
        "slug": Path(abs_path).stem,
        "path": rel,
        "title": title,
        "summary": meta.get("summary") or "",
        "excerpt": _excerpt(body),
        "category": meta.get("category") or "",
        "tags": tags,
        "word_count": _word_count(body),
        "bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
        "scope": surface.scope,
        "content_hash": content_hash(content),
    }


def list_notes(surface: NotesSurface) -> list[dict[str, Any]]:
    ensure_notes_dir(surface)
    notes = []
    for path in sorted(Path(surface.notes_root).glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.is_file():
            notes.append(serialize_note(surface, str(path)))
    return notes


def create_note(surface: NotesSurface, *, title: str, content: str | None = None, slug: str | None = None) -> dict[str, Any]:
    ensure_notes_dir(surface)
    base_slug = slugify_note_title(slug or title)
    candidate = base_slug
    index = 1
    while True:
        abs_path, _rel = resolve_note_abs_path(surface, candidate)
        if not os.path.exists(abs_path):
            break
        index += 1
        candidate = f"{base_slug}-{index}"
    body = content if content is not None else f"# {title.strip() or 'Untitled note'}\n\n"
    note_content = ensure_note_frontmatter(body, title=title.strip() or "Untitled note")
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    Path(abs_path).write_text(note_content, encoding="utf-8")
    return {**serialize_note(surface, abs_path), "content": note_content}


def read_note(surface: NotesSurface, slug: str) -> dict[str, Any]:
    abs_path, _rel = resolve_note_abs_path(surface, slug)
    if not os.path.isfile(abs_path):
        raise HTTPException(404, "Note not found")
    content = Path(abs_path).read_text(encoding="utf-8")
    return {**serialize_note(surface, abs_path), "content": content, "content_hash": content_hash(content)}


def write_note(surface: NotesSurface, slug: str, content: str, base_hash: str | None) -> dict[str, Any]:
    abs_path, _rel = resolve_note_abs_path(surface, slug)
    if not os.path.isfile(abs_path):
        raise HTTPException(404, "Note not found")
    current = Path(abs_path).read_text(encoding="utf-8")
    current_hash = content_hash(current)
    if base_hash and base_hash != current_hash:
        raise HTTPException(status_code=409, detail={"message": "Note changed on disk", "content_hash": current_hash, "content": current})
    next_content = ensure_note_frontmatter(content)
    save_file_backup(abs_path)
    Path(abs_path).write_text(next_content, encoding="utf-8")
    return {**serialize_note(surface, abs_path), "content": next_content, "content_hash": content_hash(next_content)}


def build_assist_proposal(content: str, *, selection: dict[str, Any] | None, instruction: str | None, mode: str) -> dict[str, Any]:
    """Return a conservative proposal scaffold; note chat handles open-ended AI work."""
    target = "selection" if selection and selection.get("text") else "document"
    source = str(selection.get("text")) if target == "selection" else content
    replacement = source.strip()
    if mode == "clarify_structure":
        if not re.search(r"^#{1,3}\s+", replacement, flags=re.MULTILINE):
            replacement = "## Notes\n\n" + replacement
        replacement = re.sub(r"\n{3,}", "\n\n", replacement).strip() + "\n"
    elif instruction:
        replacement = replacement.strip() + f"\n\n<!-- Requested change: {instruction.strip()} -->\n"
    diff = "\n".join(difflib.unified_diff(source.splitlines(), replacement.splitlines(), fromfile="current.md", tofile="proposal.md", lineterm=""))
    return {
        "target": target,
        "replacement_markdown": replacement,
        "rationale": "Prepared a Markdown-safe proposal. Use note chat for deeper AI rewriting before accepting.",
        "diff": diff,
    }


async def build_ai_assist_proposal(
    *,
    bot: Any,
    channel: Channel,
    content: str,
    selection: dict[str, Any] | None,
    instruction: str | None,
    mode: str,
) -> dict[str, Any]:
    """Ask the channel bot model for a Markdown-safe note proposal."""
    target = "selection" if selection and selection.get("text") else "document"
    source = str(selection.get("text")) if target == "selection" else content
    default = build_assist_proposal(content, selection=selection, instruction=instruction, mode=mode)

    try:
        from app.services.providers import get_llm_client, resolve_effective_provider

        model = getattr(channel, "model_override", None) or bot.model
        provider_id = resolve_effective_provider(
            getattr(channel, "model_override", None),
            None,
            getattr(bot, "model_provider_id", None),
        )
        client = get_llm_client(provider_id)
        prompt = {
            "mode": mode,
            "target": target,
            "instruction": instruction or "Clarify and structure the Markdown while preserving the user's meaning.",
            "markdown": source,
        }
        response = await client.chat.completions.create(
            model=model,
            temperature=0.2,
            max_tokens=3000,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You assist with Spindrel Notes. Return only JSON with keys "
                        "replacement_markdown and rationale. Preserve user-authored facts, "
                        "write valid Markdown, do not remove content unless explicitly asked, "
                        "and occasionally suggest summary/tags/category inside Markdown/frontmatter "
                        "only when the provided text supports them."
                    ),
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
        )
        raw = response.choices[0].message.content or ""
        parsed = _parse_json_object(raw)
        replacement = str(parsed.get("replacement_markdown") or "").strip()
        if not replacement:
            return default
        rationale = str(parsed.get("rationale") or "Generated a Markdown-safe proposal.")
        diff = "\n".join(difflib.unified_diff(source.splitlines(), replacement.splitlines(), fromfile="current.md", tofile="proposal.md", lineterm=""))
        return {
            "target": target,
            "replacement_markdown": replacement + ("\n" if not replacement.endswith("\n") else ""),
            "rationale": rationale,
            "diff": diff,
        }
    except Exception:
        logger.warning("Note assist LLM proposal failed; falling back to local proposal", exc_info=True)
        return default


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < start:
            return {}
        parsed = json.loads(text[start:end + 1])
    return parsed if isinstance(parsed, dict) else {}


async def get_or_create_note_session(
    db: AsyncSession,
    *,
    channel: Channel,
    bot: Any,
    surface: NotesSurface,
    note_path: str,
    title: str,
) -> Session:
    rows = (await db.execute(
        select(Session).where(
            Session.bot_id == bot.id,
            Session.parent_channel_id == channel.id,
            Session.session_type == "ephemeral",
        )
    )).scalars().all()
    for row in rows:
        meta = row.metadata_ or {}
        if meta.get("kind") == NOTE_SESSION_KIND and meta.get("note_path") == note_path:
            return row

    from app.services.sub_sessions import spawn_ephemeral_session

    context = {
        "page_name": f"Notes: {title}",
        "tags": ["notes", "knowledge-base", "markdown"],
        "tool_hints": ["workspace/notes", "workspace/knowledge_bases", "grill_me"],
        "payload": {
            "kind": NOTE_SESSION_KIND,
            "note_path": note_path,
            "surface_scope": surface.scope,
            "notes_directory": f"{surface.kb_rel}/{NOTES_DIR}",
            "instruction": "Assist with this Markdown note. Preserve user-written content, propose changes before overwriting, and occasionally suggest category, summary, and tag updates.",
        },
    }
    session = await spawn_ephemeral_session(db, bot_id=bot.id, parent_channel_id=channel.id, context=context)
    session.metadata_ = {
        **(session.metadata_ or {}),
        "kind": NOTE_SESSION_KIND,
        "note_path": note_path,
        "surface_scope": surface.scope,
        "channel_id": str(channel.id),
        "project_id": surface.project_id,
        "title": title,
    }
    flag_modified(session, "metadata_")
    return session
