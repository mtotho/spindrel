"""Local tool: manage_bot_skill — self-authored skill CRUD for bots."""

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.agent.context import current_bot_id
from app.tools.registry import register

logger = logging.getLogger(__name__)

BOT_SKILL_COUNT_WARNING = 50
CONTENT_MIN_LENGTH = 50
CONTENT_MAX_LENGTH = 50_000  # 50KB
NAME_MAX_LENGTH = 100
MAX_SCRIPTS_PER_SKILL = 20
SCRIPT_BODY_MAX_LENGTH = 50_000
SCRIPT_DESCRIPTION_MAX_LENGTH = 300
SCRIPT_TIMEOUT_MAX = 300
STALE_NEVER_SURFACED_DAYS = 7   # never surfaced + older than this = stale
STALE_LAST_SURFACED_DAYS = 30   # last surfaced longer ago than this = stale

_SLUG_RE = re.compile(r"[^a-z0-9-]")


def _is_stale(created_at: datetime | None, last_surfaced_at: datetime | None, surface_count: int) -> bool:
    """A skill is stale if it was never surfaced and is older than 7 days,
    or its last surfacing was more than 30 days ago."""
    now = datetime.now(timezone.utc)
    if surface_count == 0 and last_surfaced_at is None:
        # Never surfaced — stale if older than the threshold
        if created_at and (now - created_at) > timedelta(days=STALE_NEVER_SURFACED_DAYS):
            return True
        return False
    if last_surfaced_at is not None:
        # Has a surfacing timestamp — stale if too old
        if (now - last_surfaced_at) > timedelta(days=STALE_LAST_SURFACED_DAYS):
            return True
        return False
    # surface_count > 0 but last_surfaced_at is None (data inconsistency) — not stale
    return False


def _slugify(name: str) -> str:
    """Normalize a name to a URL-safe slug."""
    slug = name.strip().lower().replace(" ", "-")
    slug = _SLUG_RE.sub("", slug)  # strip anything not alphanumeric or hyphen
    slug = re.sub(r"-+", "-", slug).strip("-")  # collapse multiple hyphens
    return slug


def _bot_skill_id(bot_id: str, name: str) -> str:
    """Build the canonical skill ID for a bot-authored skill.

    Raises ValueError if the name produces an empty slug.
    Strips the bots/{bot_id}/ prefix if the caller accidentally includes it.
    """
    # Guard against bots passing the full ID as the name
    prefix = f"bots/{bot_id}/"
    if name.startswith(prefix):
        name = name[len(prefix):]
    slug = _slugify(name)
    if not slug:
        raise ValueError(f"Invalid skill name: {name!r}")
    return f"bots/{bot_id}/{slug}"


def _safe_skill_id(bot_id: str, name: str) -> tuple[str | None, str | None]:
    """Return (skill_id, None) on success, or (None, error_json) on failure."""
    try:
        return _bot_skill_id(bot_id, name), None
    except ValueError:
        return None, json.dumps({
            "error": f"Invalid skill name: '{name}'. Use lowercase letters, numbers, and hyphens.",
        }, ensure_ascii=False)


def _validate_content(content: str) -> str | None:
    """Return an error string if content fails validation, else None."""
    if len(content) < CONTENT_MIN_LENGTH:
        return f"Content too short ({len(content)} chars). Minimum is {CONTENT_MIN_LENGTH} characters."
    if len(content) > CONTENT_MAX_LENGTH:
        return f"Content too large ({len(content)} chars). Maximum is {CONTENT_MAX_LENGTH} characters."
    return None


def _validate_name(name: str) -> str | None:
    """Return an error string if name fails validation, else None."""
    if len(name) > NAME_MAX_LENGTH:
        return f"Name too long ({len(name)} chars). Maximum is {NAME_MAX_LENGTH} characters."
    return None


def _normalize_script_name(name: str) -> str:
    return _slugify(name)


def _summarize_scripts(scripts: list[dict] | None) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for script in scripts or []:
        summary.append({
            "name": script.get("name", ""),
            "description": script.get("description", ""),
            "timeout_s": script.get("timeout_s"),
            "allowed_tools": script.get("allowed_tools"),
        })
    return summary


def _validate_scripts_payload(
    scripts: list[dict] | None,
    *,
    require_description: bool,
) -> tuple[list[dict], str | None]:
    if scripts is None:
        return [], None
    if not isinstance(scripts, list):
        return [], "scripts must be a list of objects."
    if len(scripts) > MAX_SCRIPTS_PER_SKILL:
        return [], f"Too many scripts ({len(scripts)}). Maximum is {MAX_SCRIPTS_PER_SKILL}."

    normalized: list[dict] = []
    seen: set[str] = set()
    for idx, raw in enumerate(scripts):
        if not isinstance(raw, dict):
            return [], f"scripts[{idx}] must be an object."
        name = str(raw.get("name") or "").strip()
        description = str(raw.get("description") or "").strip()
        script = str(raw.get("script") or "")
        timeout_raw = raw.get("timeout_s")
        normalized_name = _normalize_script_name(name)
        if not normalized_name:
            return [], f"scripts[{idx}].name is required."
        if normalized_name in seen:
            return [], f"Duplicate script name '{normalized_name}'."
        if normalized_name != name:
            return [], (
                f"scripts[{idx}].name must already be normalized as '{normalized_name}' "
                "using lowercase letters, numbers, and hyphens."
            )
        if require_description and not description:
            return [], f"scripts[{idx}].description is required."
        if len(description) > SCRIPT_DESCRIPTION_MAX_LENGTH:
            return [], (
                f"scripts[{idx}].description too long ({len(description)} chars). "
                f"Maximum is {SCRIPT_DESCRIPTION_MAX_LENGTH} characters."
            )
        if not script.strip():
            return [], f"scripts[{idx}].script is required."
        if len(script) > SCRIPT_BODY_MAX_LENGTH:
            return [], (
                f"scripts[{idx}].script too large ({len(script)} chars). "
                f"Maximum is {SCRIPT_BODY_MAX_LENGTH} characters."
            )
        timeout_s: int | None = None
        if timeout_raw not in (None, ""):
            try:
                timeout_s = int(timeout_raw)
            except (TypeError, ValueError):
                return [], f"scripts[{idx}].timeout_s must be an integer."
            if timeout_s < 5 or timeout_s > SCRIPT_TIMEOUT_MAX:
                return [], (
                    f"scripts[{idx}].timeout_s must be between 5 and {SCRIPT_TIMEOUT_MAX}."
                )
        # Optional explicit allowlist of tool names this stored script may
        # call via run_script. When set, the inner /internal/tools/exec
        # endpoint rejects any nested call outside the list (fail-closed),
        # and run_script pre-validates each declared tool through the
        # policy gate before exec. Inline scripts can't pre-declare; this
        # is a stored-script-only defense-in-depth control.
        allowed_tools_raw = raw.get("allowed_tools")
        normalized_allowed: list[str] | None = None
        if allowed_tools_raw is not None:
            if not isinstance(allowed_tools_raw, list):
                return [], f"scripts[{idx}].allowed_tools must be a list of tool names."
            cleaned: list[str] = []
            for tool_idx, tool_name in enumerate(allowed_tools_raw):
                if not isinstance(tool_name, str) or not tool_name.strip():
                    return [], (
                        f"scripts[{idx}].allowed_tools[{tool_idx}] must be a non-empty string."
                    )
                cleaned.append(tool_name.strip())
            normalized_allowed = cleaned or None
        entry: dict = {
            "name": normalized_name,
            "description": description,
            "script": script,
            "timeout_s": timeout_s,
        }
        if normalized_allowed is not None:
            entry["allowed_tools"] = normalized_allowed
        normalized.append(entry)
        seen.add(normalized_name)
    return normalized, None


def _get_script_by_name(scripts: list[dict] | None, script_name: str) -> dict | None:
    normalized = _normalize_script_name(script_name)
    for script in scripts or []:
        if script.get("name") == normalized:
            return script
    return None


def _extract_body(full_content: str) -> str:
    """Extract the markdown body from content that may have YAML frontmatter."""
    if full_content.startswith("---"):
        end = full_content.find("---", 3)
        if end != -1:
            return full_content[end + 3:].lstrip("\n")
    return full_content


def _extract_frontmatter(full_content: str) -> dict[str, str]:
    """Extract frontmatter values from content."""
    if not full_content.startswith("---"):
        return {}
    end = full_content.find("---", 3)
    if end == -1:
        return {}
    fm_text = full_content[3:end].strip()
    result: dict[str, str] = {}
    for line in fm_text.split("\n"):
        if ":" in line:
            key, _, val = line.partition(":")
            result[key.strip()] = val.strip()
    return result


def _sanitize_frontmatter_value(val: str) -> str:
    """Strip newlines and leading/trailing whitespace from frontmatter values."""
    return val.replace("\n", " ").replace("\r", " ").strip()


def _build_content(title: str, content: str, triggers: str = "", category: str = "") -> str:
    """Build skill content with YAML frontmatter."""
    lines = ["---"]
    lines.append(f"name: {_sanitize_frontmatter_value(title)}")
    if triggers:
        lines.append(f"triggers: {_sanitize_frontmatter_value(triggers)}")
    if category:
        lines.append(f"category: {_sanitize_frontmatter_value(category)}")
    lines.append("---")
    lines.append("")
    lines.append(content)
    return "\n".join(lines)


@dataclass(frozen=True)
class _SkillActionContext:
    bot_id: str
    prefix: str
    async_session: Any
    skill_row_model: Any


def _json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _error(message: str) -> str:
    return _json({"error": message})


def _triggers_list(triggers: str) -> list[str]:
    return [t.strip() for t in triggers.split(",") if t.strip()] if triggers else []


def _skill_payload(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "content": row.content,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "scripts": _summarize_scripts(row.scripts),
    }


def _summarize_skill_row(row: Any) -> dict[str, Any]:
    fm = _extract_frontmatter(row.content) if row.content else {}
    body_preview = _extract_body(row.content)[:120].strip() if row.content else ""
    stale = _is_stale(row.created_at, row.last_surfaced_at, row.surface_count)
    return {
        "id": row.id,
        "name": row.name,
        "category": fm.get("category", ""),
        "preview": body_preview,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "last_surfaced_at": row.last_surfaced_at.isoformat() if row.last_surfaced_at else None,
        "surface_count": row.surface_count,
        "stale": stale,
        "script_count": len(row.scripts or []),
        "scripts": _summarize_scripts(row.scripts),
    }


def _editable_skill_error(
    row: Any,
    prefix: str,
    source_verb: str,
    *,
    ownership_verb: str | None = None,
) -> str | None:
    if row.source_type not in ("tool", "manual"):
        return f"Cannot {source_verb} a file-managed or integration skill."
    if not row.id.startswith(prefix):
        return f"Cannot {ownership_verb or source_verb} another bot's skill."
    return None


def _scripts_edit_error(row: Any) -> str | None:
    if row.source_type not in ("tool", "manual"):
        return "Cannot edit scripts on a file-managed or integration skill."
    return None


def _sync_row_from_full_content(row: Any, full_content: str) -> None:
    patched_fm = _extract_frontmatter(full_content)
    patched_body = _extract_body(full_content)
    row.name = patched_fm.get("name", row.name)
    row.description = patched_body[:200].strip() if patched_body else row.description
    patched_triggers = patched_fm.get("triggers", "")
    row.triggers = _triggers_list(patched_triggers) if patched_triggers else (row.triggers or [])
    patched_category = patched_fm.get("category", "")
    if patched_category:
        row.category = patched_category.strip()


async def _resolve_upsert_action(ctx: _SkillActionContext, name: str) -> str | None:
    if not name:
        return _error("name is required for upsert action.")
    skill_id, err = _safe_skill_id(ctx.bot_id, name)
    if err or skill_id is None:
        return err
    async with ctx.async_session() as db:
        existing = await db.get(ctx.skill_row_model, skill_id)
    return "update" if existing else "create"


async def _handle_list_skills(ctx: _SkillActionContext, *, limit: int, offset: int) -> str:
    from sqlalchemy import func, select

    clamped_limit = max(1, min(limit, 100))
    clamped_offset = max(0, offset)
    async with ctx.async_session() as db:
        total = (await db.execute(
            select(func.count()).select_from(ctx.skill_row_model)
            .where(ctx.skill_row_model.id.like(f"{ctx.prefix}%"), ctx.skill_row_model.archived_at.is_(None))
        )).scalar_one()
        rows = (await db.execute(
            select(ctx.skill_row_model).where(
                ctx.skill_row_model.id.like(f"{ctx.prefix}%"),
                ctx.skill_row_model.archived_at.is_(None),
            )
            .order_by(ctx.skill_row_model.updated_at.desc())
            .limit(clamped_limit).offset(clamped_offset)
        )).scalars().all()
    if not rows and clamped_offset == 0:
        return _json({"skills": [], "total": 0, "message": "No self-authored skills yet."})

    summary = [_summarize_skill_row(row) for row in rows]
    stale_count = sum(1 for row in summary if row["stale"])
    result: dict[str, Any] = {
        "skills": summary,
        "total": total,
        "limit": clamped_limit,
        "offset": clamped_offset,
    }
    if stale_count > 0:
        noun = "skill" if stale_count == 1 else "skills"
        verb = "has" if stale_count == 1 else "have"
        result["hint"] = (
            f"{stale_count} {noun} {verb} never been surfaced or "
            f"{verb}n't been surfaced in 30+ days. Consider reviewing "
            f"trigger phrases or deleting stale skills."
        )
    return _json(result)


async def _handle_get_skill(ctx: _SkillActionContext, *, name: str, names: list[str] | None) -> str:
    if names:
        if len(names) > 50:
            return _error(f"Too many names ({len(names)}). Cap is 50 for batch get.")
        async with ctx.async_session() as db:
            out: list[dict] = []
            missing: list[str] = []
            for n in names:
                sid, err = _safe_skill_id(ctx.bot_id, n)
                if err or sid is None:
                    missing.append(n)
                    continue
                row = await db.get(ctx.skill_row_model, sid)
                if row is None:
                    missing.append(n)
                    continue
                out.append(_skill_payload(row))
        return _json({"skills": out, "missing": missing})

    if not name:
        return _error("name is required for get action.")
    skill_id, err = _safe_skill_id(ctx.bot_id, name)
    if err or skill_id is None:
        return err
    async with ctx.async_session() as db:
        row = await db.get(ctx.skill_row_model, skill_id)
    if not row:
        return _error(f"Skill '{skill_id}' not found.")
    return _json(_skill_payload(row))


async def _handle_get_script(ctx: _SkillActionContext, *, name: str, script_name: str) -> str:
    if not name or not script_name:
        return _error("name and script_name are required for get_script action.")
    skill_id, err = _safe_skill_id(ctx.bot_id, name)
    if err or skill_id is None:
        return err
    async with ctx.async_session() as db:
        row = await db.get(ctx.skill_row_model, skill_id)
    if not row:
        return _error(f"Skill '{skill_id}' not found.")
    script_row = _get_script_by_name(row.scripts, script_name)
    if not script_row:
        return _error(f"Script '{_normalize_script_name(script_name)}' not found on '{skill_id}'.")
    return _json({
        "ok": True,
        "id": row.id,
        "script_name": script_row["name"],
        "script_description": script_row.get("description", ""),
        "script_body": script_row.get("script", ""),
        "script_timeout_s": script_row.get("timeout_s"),
        "script_allowed_tools": script_row.get("allowed_tools"),
    })


async def _handle_create_skill(
    ctx: _SkillActionContext,
    *,
    name: str,
    title: str,
    content: str,
    triggers: str,
    category: str,
    scripts: list[dict] | None,
    force: bool,
) -> str:
    if not name or not title or not content:
        return _error("name, title, and content are required for create.")
    name_err = _validate_name(name)
    if name_err:
        return _error(name_err)
    content_err = _validate_content(content)
    if content_err:
        return _error(content_err)
    normalized_scripts, scripts_err = _validate_scripts_payload(scripts, require_description=True)
    if scripts_err:
        return _error(scripts_err)
    skill_id, err = _safe_skill_id(ctx.bot_id, name)
    if err or skill_id is None:
        return err

    if not force:
        dedup_result = await _check_skill_dedup(ctx.bot_id, content, ctx.prefix)
        if dedup_result:
            return dedup_result

    full_content = _build_content(title, content, triggers, category)
    content_hash = hashlib.sha256(full_content.encode()).hexdigest()
    from app.services.manifest_signing import sign_skill_payload
    signature = sign_skill_payload(full_content, normalized_scripts)
    async with ctx.async_session() as db:
        existing = await db.get(ctx.skill_row_model, skill_id)
        if existing:
            return _error(f"Skill '{skill_id}' already exists. Use update or patch.")

        now = datetime.now(timezone.utc)
        row = ctx.skill_row_model(
            id=skill_id,
            name=title.strip(),
            description=content[:200].strip() if content else None,
            category=category.strip() if category else None,
            triggers=_triggers_list(triggers),
            scripts=normalized_scripts,
            content=full_content,
            content_hash=content_hash,
            signature=signature,
            source_type="tool",
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        await db.commit()

    embedded = await _embed_skill_safe(skill_id)
    _invalidate_cache(ctx.bot_id)
    warning = await _check_count_warning(ctx.bot_id, ctx.prefix)
    msg = f"Skill '{skill_id}' created."
    if not embedded:
        msg += " Warning: embedding failed — skill saved but won't appear in RAG until re-embedded."
    if warning:
        msg += f" {warning}"
    return _json({"ok": True, "id": skill_id, "embedded": embedded, "message": msg})


async def _handle_update_skill(
    ctx: _SkillActionContext,
    *,
    name: str,
    title: str,
    content: str,
    triggers: str,
    category: str,
    scripts: list[dict] | None,
) -> str:
    if not name:
        return _error("name is required for update action.")
    skill_id, err = _safe_skill_id(ctx.bot_id, name)
    if err or skill_id is None:
        return err

    async with ctx.async_session() as db:
        row = await db.get(ctx.skill_row_model, skill_id)
        if not row:
            return _error(f"Skill '{skill_id}' not found.")
        editable_error = _editable_skill_error(row, ctx.prefix, "edit", ownership_verb="update")
        if editable_error:
            return _error(editable_error)
        if not title and not content and not triggers and not category and scripts is None:
            return _error("Provide at least one of: title, content, triggers, category, scripts.")
        if content:
            content_err = _validate_content(content)
            if content_err:
                return _error(content_err)
        normalized_scripts: list[dict] | None = None
        if scripts is not None:
            normalized_scripts, scripts_err = _validate_scripts_payload(scripts, require_description=True)
            if scripts_err:
                return _error(scripts_err)

        existing_fm = _extract_frontmatter(row.content)
        new_title = title.strip() if title else row.name
        new_triggers = triggers if triggers else existing_fm.get("triggers", "")
        new_category = category if category else existing_fm.get("category", "")
        if title:
            row.name = new_title
        body = content if content else _extract_body(row.content)
        full_content = _build_content(new_title, body, new_triggers, new_category)
        row.content = full_content
        row.content_hash = hashlib.sha256(full_content.encode()).hexdigest()
        row.triggers = _triggers_list(new_triggers)
        if new_category:
            row.category = new_category.strip()
        if content:
            row.description = content[:200].strip()
        if normalized_scripts is not None:
            row.scripts = normalized_scripts
        from app.services.manifest_signing import sign_skill_payload
        row.signature = sign_skill_payload(
            full_content,
            normalized_scripts if normalized_scripts is not None else (row.scripts or []),
        )
        row.updated_at = datetime.now(timezone.utc)
        await db.commit()

    asyncio.create_task(_embed_skill_safe(skill_id))
    _invalidate_cache(ctx.bot_id)
    return _json({"ok": True, "id": skill_id, "message": f"Skill '{skill_id}' updated."})


async def _handle_delete_skill(ctx: _SkillActionContext, *, name: str) -> str:
    if not name:
        return _error("name is required for delete action.")
    skill_id, err = _safe_skill_id(ctx.bot_id, name)
    if err or skill_id is None:
        return err

    async with ctx.async_session() as db:
        row = await db.get(ctx.skill_row_model, skill_id)
        if not row:
            return _error(f"Skill '{skill_id}' not found.")
        editable_error = _editable_skill_error(row, ctx.prefix, "delete")
        if editable_error:
            return _error(editable_error)
        if row.archived_at:
            return _error(f"Skill '{skill_id}' is already archived.")
        row.archived_at = datetime.now(timezone.utc)
        await db.commit()

    _invalidate_cache(ctx.bot_id)
    return _json({"ok": True, "id": skill_id, "message": f"Skill '{skill_id}' archived. Use action='restore' to undo."})


async def _handle_restore_skill(ctx: _SkillActionContext, *, name: str) -> str:
    if not name:
        return _error("name is required for restore action.")
    skill_id, err = _safe_skill_id(ctx.bot_id, name)
    if err or skill_id is None:
        return err

    async with ctx.async_session() as db:
        row = await db.get(ctx.skill_row_model, skill_id)
        if not row:
            return _error(f"Skill '{skill_id}' not found.")
        if not row.id.startswith(ctx.prefix):
            return _error("Cannot restore another bot's skill.")
        if not row.archived_at:
            return _error(f"Skill '{skill_id}' is not archived.")
        row.archived_at = None
        await db.commit()

    _invalidate_cache(ctx.bot_id)
    return _json({"ok": True, "id": skill_id, "message": f"Skill '{skill_id}' restored."})


async def _handle_patch_skill(ctx: _SkillActionContext, *, name: str, old_text: str, new_text: str) -> str:
    if not name:
        return _error("name is required for patch action.")
    if not old_text or not new_text:
        return _error("old_text and new_text are required for patch action.")
    skill_id, err = _safe_skill_id(ctx.bot_id, name)
    if err or skill_id is None:
        return err

    async with ctx.async_session() as db:
        row = await db.get(ctx.skill_row_model, skill_id)
        if not row:
            return _error(f"Skill '{skill_id}' not found.")
        editable_error = _editable_skill_error(row, ctx.prefix, "patch")
        if editable_error:
            return _error(editable_error)
        if old_text not in row.content:
            return _error("old_text not found in skill content.")
        patched = row.content.replace(old_text, new_text, 1)
        body_err = _validate_content(_extract_body(patched))
        if body_err:
            return _error(f"Patch would produce invalid content: {body_err}")
        row.content = patched
        row.content_hash = hashlib.sha256(row.content.encode()).hexdigest()
        _sync_row_from_full_content(row, patched)
        row.updated_at = datetime.now(timezone.utc)
        await db.commit()

    asyncio.create_task(_embed_skill_safe(skill_id))
    _invalidate_cache(ctx.bot_id)
    return _json({"ok": True, "id": skill_id, "message": f"Skill '{skill_id}' patched."})


async def _handle_merge_skills(
    ctx: _SkillActionContext,
    *,
    names: list[str] | None,
    name: str,
    title: str,
    content: str,
    triggers: str,
    category: str,
    scripts: list[dict] | None,
) -> str:
    if not names or len(names) < 2:
        return _error("names must contain at least 2 skill names to merge.")
    if not name or not title or not content:
        return _error("name, title, and content are required for the merged result skill.")
    name_err = _validate_name(name)
    if name_err:
        return _error(name_err)
    content_err = _validate_content(content)
    if content_err:
        return _error(content_err)
    normalized_scripts, scripts_err = _validate_scripts_payload(scripts, require_description=True)
    if scripts_err:
        return _error(scripts_err)
    merged_id, err = _safe_skill_id(ctx.bot_id, name)
    if err or merged_id is None:
        return err

    from sqlalchemy import delete as sa_delete
    from app.db.models import Document

    source_ids: list[str] = []
    seen: set[str] = set()
    for src_name in names:
        src_id, src_err = _safe_skill_id(ctx.bot_id, src_name)
        if src_err or src_id is None:
            return src_err
        if src_id not in seen:
            source_ids.append(src_id)
            seen.add(src_id)
    if len(source_ids) < 2:
        return _error("names must contain at least 2 distinct skill names to merge.")

    async with ctx.async_session() as db:
        source_rows: list[Any] = []
        for src_id in source_ids:
            row = await db.get(ctx.skill_row_model, src_id)
            if not row:
                return _error(f"Source skill '{src_id}' not found.")
            if row.source_type not in ("tool", "manual"):
                return _error(f"Cannot merge file-managed skill '{src_id}'.")
            if not row.id.startswith(ctx.prefix):
                return _error(f"Cannot merge another bot's skill '{src_id}'.")
            source_rows.append(row)

        merged_scripts = normalized_scripts
        if scripts is None:
            merged_scripts = []
            seen_script_names: set[str] = set()
            for row in source_rows:
                for attached in row.scripts or []:
                    attached_name = attached.get("name", "")
                    if attached_name in seen_script_names:
                        return _error(
                            "Cannot merge scripts automatically: duplicate attached script "
                            f"name '{attached_name}'. Provide scripts=[...] on the merge action."
                        )
                    merged_scripts.append(attached)
                    seen_script_names.add(attached_name)

        existing = await db.get(ctx.skill_row_model, merged_id)
        if existing and merged_id not in source_ids:
            return _error(f"Target skill '{merged_id}' already exists and is not one of the source skills.")

        deleted_names = []
        for row in source_rows:
            deleted_names.append(row.name)
            await db.delete(row)
            await db.execute(sa_delete(Document).where(Document.source == f"skill:{row.id}"))

        full_content = _build_content(title, content, triggers, category)
        now = datetime.now(timezone.utc)
        merged_row = ctx.skill_row_model(
            id=merged_id,
            name=title.strip(),
            description=content[:200].strip() if content else None,
            category=category.strip() if category else None,
            triggers=_triggers_list(triggers),
            scripts=merged_scripts,
            content=full_content,
            content_hash=hashlib.sha256(full_content.encode()).hexdigest(),
            source_type="tool",
            created_at=now,
            updated_at=now,
        )
        db.add(merged_row)
        await db.commit()

    embedded = await _embed_skill_safe(merged_id)
    _invalidate_cache(ctx.bot_id)
    return _json({
        "ok": True,
        "id": merged_id,
        "embedded": embedded,
        "deleted": source_ids,
        "message": (
            f"Merged {len(source_ids)} skills into '{merged_id}'. "
            f"Deleted: {', '.join(deleted_names)}."
        ),
    })


async def _handle_add_script(
    ctx: _SkillActionContext,
    *,
    name: str,
    script_name: str,
    script_description: str,
    script_body: str,
    script_timeout_s: int | None,
    script_allowed_tools: list[str] | None,
) -> str:
    if not name or not script_name or not script_body or not script_description:
        return _error("name, script_name, script_description, and script_body are required for add_script action.")
    skill_id, err = _safe_skill_id(ctx.bot_id, name)
    if err or skill_id is None:
        return err
    new_scripts, scripts_err = _validate_scripts_payload([{
        "name": script_name,
        "description": script_description,
        "script": script_body,
        "timeout_s": script_timeout_s,
        "allowed_tools": script_allowed_tools,
    }], require_description=True)
    if scripts_err:
        return _error(scripts_err)
    new_script = new_scripts[0]
    async with ctx.async_session() as db:
        row = await db.get(ctx.skill_row_model, skill_id)
        if not row:
            return _error(f"Skill '{skill_id}' not found.")
        scripts_error = _scripts_edit_error(row)
        if scripts_error:
            return _error(scripts_error)
        if _get_script_by_name(row.scripts, new_script["name"]):
            return _error(f"Script '{new_script['name']}' already exists on '{skill_id}'.")
        combined_scripts, combined_err = _validate_scripts_payload(
            [*(row.scripts or []), new_script],
            require_description=True,
        )
        if combined_err:
            return _error(combined_err)
        row.scripts = combined_scripts
        row.updated_at = datetime.now(timezone.utc)
        await db.commit()
    _invalidate_cache(ctx.bot_id)
    return _json({"ok": True, "id": skill_id, "message": f"Script '{new_script['name']}' added to '{skill_id}'."})


async def _handle_update_script(
    ctx: _SkillActionContext,
    *,
    name: str,
    script_name: str,
    script_description: str,
    script_body: str,
    script_timeout_s: int | None,
    script_allowed_tools: list[str] | None,
) -> str:
    if not name or not script_name:
        return _error("name and script_name are required for update_script action.")
    skill_id, err = _safe_skill_id(ctx.bot_id, name)
    if err or skill_id is None:
        return err
    normalized_name = _normalize_script_name(script_name)
    async with ctx.async_session() as db:
        row = await db.get(ctx.skill_row_model, skill_id)
        if not row:
            return _error(f"Skill '{skill_id}' not found.")
        scripts_error = _scripts_edit_error(row)
        if scripts_error:
            return _error(scripts_error)
        current = _get_script_by_name(row.scripts, normalized_name)
        if not current:
            return _error(f"Script '{normalized_name}' not found on '{skill_id}'.")
        next_name = current["name"]
        next_description = script_description or current.get("description", "")
        next_body = script_body or current.get("script", "")
        next_timeout = script_timeout_s if script_timeout_s is not None else current.get("timeout_s")
        next_allowed_tools = (
            script_allowed_tools
            if script_allowed_tools is not None
            else current.get("allowed_tools")
        )
        new_scripts, scripts_err = _validate_scripts_payload([{
            "name": next_name,
            "description": next_description,
            "script": next_body,
            "timeout_s": next_timeout,
            "allowed_tools": next_allowed_tools,
        }], require_description=True)
        if scripts_err:
            return _error(scripts_err)
        updated_script = new_scripts[0]
        row.scripts = [
            updated_script if attached.get("name") == normalized_name else attached
            for attached in row.scripts or []
        ]
        row.updated_at = datetime.now(timezone.utc)
        await db.commit()
    _invalidate_cache(ctx.bot_id)
    return _json({"ok": True, "id": skill_id, "message": f"Script '{normalized_name}' updated on '{skill_id}'."})


async def _handle_delete_script(ctx: _SkillActionContext, *, name: str, script_name: str) -> str:
    if not name or not script_name:
        return _error("name and script_name are required for delete_script action.")
    skill_id, err = _safe_skill_id(ctx.bot_id, name)
    if err or skill_id is None:
        return err
    normalized_name = _normalize_script_name(script_name)
    async with ctx.async_session() as db:
        row = await db.get(ctx.skill_row_model, skill_id)
        if not row:
            return _error(f"Skill '{skill_id}' not found.")
        scripts_error = _scripts_edit_error(row)
        if scripts_error:
            return _error(scripts_error)
        current_scripts = row.scripts or []
        if not _get_script_by_name(current_scripts, normalized_name):
            return _error(f"Script '{normalized_name}' not found on '{skill_id}'.")
        row.scripts = [attached for attached in current_scripts if attached.get("name") != normalized_name]
        row.updated_at = datetime.now(timezone.utc)
        await db.commit()
    _invalidate_cache(ctx.bot_id)
    return _json({"ok": True, "id": skill_id, "message": f"Script '{normalized_name}' deleted from '{skill_id}'."})


@register({
    "type": "function",
    "function": {
        "name": "manage_bot_skill",
        "description": (
            "Create, update, list, get, delete, patch, or merge your own reusable skills. "
            "Skills you author enter the RAG pipeline and are semantically retrievable "
            "in future sessions. Use this to capture solution patterns, domain knowledge, "
            "troubleshooting guides, and procedures you've learned."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "create", "update", "upsert",
                        "list", "get", "delete", "patch", "merge", "restore",
                        "get_script", "add_script", "update_script", "delete_script",
                    ],
                    "description": (
                        "The action to perform. `upsert` creates the skill if it doesn't "
                        "exist and updates it if it does — prefer this over `create` when "
                        "you're not sure, since `create` errors on duplicates and costs a "
                        "round-trip. `delete` archives the skill (reversible via restore)."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": (
                        "Skill slug (lowercase, hyphens). Becomes bots/{bot_id}/{name}. "
                        "Required for create, update, get, delete, patch, merge."
                    ),
                },
                "title": {
                    "type": "string",
                    "description": "Human-readable display name (required for create).",
                },
                "content": {
                    "type": "string",
                    "description": "Full markdown body (required for create, optional for update).",
                },
                "triggers": {
                    "type": "string",
                    "description": "Comma-separated trigger phrases for RAG surfacing.",
                },
                "category": {
                    "type": "string",
                    "description": (
                        "Organizational tag: troubleshooting, domain-knowledge, procedures, etc."
                    ),
                },
                "scripts": {
                    "type": "array",
                    "description": "Optional named run_script snippets attached to the skill.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "script": {"type": "string"},
                            "timeout_s": {"type": "integer"},
                            "allowed_tools": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Optional allowlist of tool names this stored script may call.",
                            },
                        },
                        "required": ["name", "description", "script"],
                    },
                },
                "script_name": {
                    "type": "string",
                    "description": "Named attached script to get/add/update/delete.",
                },
                "script_description": {
                    "type": "string",
                    "description": "Short use-when summary for a named script.",
                },
                "script_body": {
                    "type": "string",
                    "description": "Python source for the named script.",
                },
                "script_timeout_s": {
                    "type": "integer",
                    "description": "Optional default timeout for the named script.",
                },
                "script_allowed_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional allowlist of tool names this named script may call through "
                        "run_script. Use with add_script/update_script for deterministic workflows."
                    ),
                },
                "old_text": {
                    "type": "string",
                    "description": "Text to find in content (for patch action).",
                },
                "new_text": {
                    "type": "string",
                    "description": "Replacement text (for patch action).",
                },
                "force": {
                    "type": "boolean",
                    "description": "Skip duplicate check on create (default false).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max skills to return for list action (default 20, max 100).",
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of skills to skip for list action (for pagination).",
                },
                "names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "For merge action: source skills to merge (deleted after merge; "
                        "provide `name` + `title` + `content` for the merged result). "
                        "For get action: batch-fetch multiple skill bodies in one call "
                        "(returns `{skills: [...], missing: [...]}`). Cap 50. "
                        "Prefer this over issuing N sequential `action=\"get\"` calls."
                    ),
                },
            },
            "required": ["action"],
        },
    },
}, returns={
    "oneOf": [
        {
            "description": "list action",
            "type": "object",
            "properties": {
                "skills": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"},
                            "category": {"type": "string"},
                            "preview": {"type": "string"},
                            "created_at": {"type": ["string", "null"]},
                            "updated_at": {"type": ["string", "null"]},
                            "last_surfaced_at": {"type": ["string", "null"]},
                            "surface_count": {"type": "integer"},
                            "stale": {"type": "boolean"},
                            "script_count": {"type": "integer"},
                            "scripts": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "description": {"type": "string"},
                                        "timeout_s": {"type": ["integer", "null"]},
                                        "allowed_tools": {
                                            "type": ["array", "null"],
                                            "items": {"type": "string"},
                                        },
                                    },
                                    "required": ["name", "description"],
                                },
                            },
                        },
                        "required": ["id", "name"],
                    },
                },
                "total": {"type": "integer"},
                "limit": {"type": "integer"},
                "offset": {"type": "integer"},
                "hint": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["skills"],
        },
        {
            "description": "get action (single name)",
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
                "content": {"type": "string"},
                "updated_at": {"type": ["string", "null"]},
                "scripts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "timeout_s": {"type": ["integer", "null"]},
                            "allowed_tools": {
                                "type": ["array", "null"],
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["name", "description"],
                    },
                },
            },
            "required": ["id", "content"],
        },
        {
            "description": "get action (batch via names=[...])",
            "type": "object",
            "properties": {
                "skills": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"},
                            "content": {"type": "string"},
                            "updated_at": {"type": ["string", "null"]},
                            "scripts": {"type": "array"},
                        },
                        "required": ["id", "content"],
                    },
                },
                "missing": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["skills", "missing"],
        },
        {
            "description": "get_script action",
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "id": {"type": "string"},
                "script_name": {"type": "string"},
                "script_description": {"type": "string"},
                "script_body": {"type": "string"},
                "script_timeout_s": {"type": ["integer", "null"]},
                "script_allowed_tools": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                },
            },
            "required": ["ok", "id", "script_name", "script_body"],
        },
        {
            "description": "create/update/delete/restore/patch/merge — success",
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "id": {"type": "string"},
                "embedded": {"type": "boolean"},
                "deleted": {"type": "array", "items": {"type": "string"}},
                "message": {"type": "string"},
            },
            "required": ["ok", "id"],
        },
        {
            "description": "duplicate warning (create without force)",
            "type": "object",
            "properties": {
                "warning": {"type": "string"},
                "similar_skill_id": {"type": "string"},
                "similarity": {"type": "number"},
                "message": {"type": "string"},
            },
            "required": ["warning"],
        },
        {
            "description": "error",
            "type": "object",
            "properties": {"error": {"type": "string"}},
            "required": ["error"],
        },
    ],
}, safety_tier="control_plane", requires_bot_context=True, tool_metadata={
    "domains": ["skill_authoring"],
    "capabilities": ["skill.read", "skill.write"],
    "exposure": "ambient",
    "auto_inject": ["workspace_files_memory"],
    "context_policy": {
        "sticky_when": {"arg": "action", "equals": "get"}
    },
})
async def manage_bot_skill(
    action: str,
    name: str = "",
    title: str = "",
    content: str = "",
    triggers: str = "",
    category: str = "",
    scripts: list[dict] | None = None,
    script_name: str = "",
    script_description: str = "",
    script_body: str = "",
    script_timeout_s: int | None = None,
    script_allowed_tools: list[str] | None = None,
    old_text: str = "",
    new_text: str = "",
    force: bool = False,
    limit: int = 20,
    offset: int = 0,
    names: list[str] | None = None,
) -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return _error("No bot context — cannot manage skills.")

    from app.db.engine import async_session
    from app.db.models import Skill as SkillRow

    ctx = _SkillActionContext(
        bot_id=bot_id,
        prefix=f"bots/{bot_id}/",
        async_session=async_session,
        skill_row_model=SkillRow,
    )

    if action == "upsert":
        resolved_action = await _resolve_upsert_action(ctx, name)
        if resolved_action not in {"create", "update"}:
            return resolved_action or _error("name is required for upsert action.")
        action = resolved_action

    if action == "list":
        return await _handle_list_skills(ctx, limit=limit, offset=offset)
    if action == "get":
        return await _handle_get_skill(ctx, name=name, names=names)
    if action == "get_script":
        return await _handle_get_script(ctx, name=name, script_name=script_name)
    if action == "create":
        return await _handle_create_skill(
            ctx,
            name=name,
            title=title,
            content=content,
            triggers=triggers,
            category=category,
            scripts=scripts,
            force=force,
        )
    if action == "update":
        return await _handle_update_skill(
            ctx,
            name=name,
            title=title,
            content=content,
            triggers=triggers,
            category=category,
            scripts=scripts,
        )
    if action == "delete":
        return await _handle_delete_skill(ctx, name=name)
    if action == "restore":
        return await _handle_restore_skill(ctx, name=name)
    if action == "patch":
        return await _handle_patch_skill(ctx, name=name, old_text=old_text, new_text=new_text)
    if action == "merge":
        return await _handle_merge_skills(
            ctx,
            names=names,
            name=name,
            title=title,
            content=content,
            triggers=triggers,
            category=category,
            scripts=scripts,
        )
    if action == "add_script":
        return await _handle_add_script(
            ctx,
            name=name,
            script_name=script_name,
            script_description=script_description,
            script_body=script_body,
            script_timeout_s=script_timeout_s,
            script_allowed_tools=script_allowed_tools,
        )
    if action == "update_script":
        return await _handle_update_script(
            ctx,
            name=name,
            script_name=script_name,
            script_description=script_description,
            script_body=script_body,
            script_timeout_s=script_timeout_s,
            script_allowed_tools=script_allowed_tools,
        )
    if action == "delete_script":
        return await _handle_delete_script(ctx, name=name, script_name=script_name)

    return _error(
        f"Unknown action: {action}. Use create, update, upsert, list, get, delete, "
        "patch, merge, restore, get_script, add_script, update_script, or delete_script."
    )


def _invalidate_cache(bot_id: str) -> None:
    """Invalidate the auto-discovery cache so next context assembly sees changes."""
    try:
        from app.agent.context_assembly import invalidate_bot_skill_cache
        invalidate_bot_skill_cache(bot_id)
    except Exception:
        pass  # non-critical
    try:
        from app.agent.rag import invalidate_skill_index_cache
        invalidate_skill_index_cache()
    except Exception:
        pass  # non-critical
    # Also clear the repeated-lookup cache so the nudge stops firing
    # after the bot creates/merges a skill (it already acted on the nudge).
    try:
        from app.agent.repeated_lookup_detection import _cache as _lookup_cache
        _lookup_cache.pop(bot_id, None)
    except Exception:
        pass


async def _embed_skill_safe(skill_id: str) -> bool:
    """Re-embed a skill, returning True on success.

    Swallows errors so fire-and-forget callers don't crash.
    """
    try:
        from app.agent.skills import re_embed_skill
        await re_embed_skill(skill_id)
        return True
    except Exception:
        logger.warning("Failed to re-embed skill '%s'", skill_id, exc_info=True)
        return False


async def _check_count_warning(bot_id: str, prefix: str) -> str | None:
    """Return a warning string if bot exceeds the soft skill count limit."""
    from sqlalchemy import func, select
    from app.db.engine import async_session
    from app.db.models import Skill as SkillRow

    async with async_session() as db:
        count = (await db.execute(
            select(func.count()).select_from(SkillRow)
            .where(SkillRow.id.like(f"{prefix}%"))
        )).scalar_one()

    if count >= BOT_SKILL_COUNT_WARNING:
        return (
            f"Warning: You now have {count} self-authored skills. "
            f"Consider merging related skills or deleting stale ones to keep your skill library focused."
        )
    return None


DEDUP_SIMILARITY_THRESHOLD = 0.85


async def _check_skill_dedup(bot_id: str, content: str, prefix: str) -> str | None:
    """Check for semantically similar existing bot skills. Returns warning JSON or None."""
    try:
        from sqlalchemy import select
        from app.agent.embeddings import embed_text
        from app.agent.vector_ops import halfvec_cosine_distance
        from app.db.engine import async_session
        from app.db.models import Document

        query_embedding = await embed_text(content[:2000])  # embed first 2k chars

        async with async_session() as db:
            distance_expr = halfvec_cosine_distance(Document.embedding, query_embedding)
            rows = (await db.execute(
                select(Document.source, distance_expr.label("distance"))
                .where(Document.source.like(f"skill:{prefix}%"))
                .order_by(distance_expr)
                .limit(1)
            )).all()

        if rows:
            best = rows[0]
            similarity = 1.0 - best.distance
            if similarity >= DEDUP_SIMILARITY_THRESHOLD:
                similar_skill_id = best.source.removeprefix("skill:")
                return json.dumps({
                    "warning": "similar_skill_exists",
                    "similar_skill_id": similar_skill_id,
                    "similarity": round(similarity, 3),
                    "message": (
                        f"A similar skill already exists: '{similar_skill_id}' "
                        f"(similarity: {similarity:.1%}). "
                        f"Consider using action='patch' or action='update' on the existing skill instead. "
                        f"To create anyway, re-run with force=true."
                    ),
                }, ensure_ascii=False)
    except Exception:
        logger.debug("Skill dedup check failed (non-blocking)", exc_info=True)
    return None
