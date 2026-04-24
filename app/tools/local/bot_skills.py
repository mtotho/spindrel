"""Local tool: manage_bot_skill — self-authored skill CRUD for bots."""

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone

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


def _summarize_scripts(scripts: list[dict] | None) -> list[dict[str, str | int | None]]:
    summary: list[dict[str, str | int | None]] = []
    for script in scripts or []:
        summary.append({
            "name": script.get("name", ""),
            "description": script.get("description", ""),
            "timeout_s": script.get("timeout_s"),
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
        normalized.append({
            "name": normalized_name,
            "description": description,
            "script": script,
            "timeout_s": timeout_s,
        })
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
}, safety_tier="control_plane", requires_bot_context=True)
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
    old_text: str = "",
    new_text: str = "",
    force: bool = False,
    limit: int = 20,
    offset: int = 0,
    names: list[str] | None = None,
) -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context — cannot manage skills."}, ensure_ascii=False)

    from app.db.engine import async_session
    from app.db.models import Skill as SkillRow

    prefix = f"bots/{bot_id}/"

    # --- LIST ---
    if action == "list":
        from sqlalchemy import func, select
        clamped_limit = max(1, min(limit, 100))
        clamped_offset = max(0, offset)
        async with async_session() as db:
            total = (await db.execute(
                select(func.count()).select_from(SkillRow)
                .where(SkillRow.id.like(f"{prefix}%"), SkillRow.archived_at.is_(None))
            )).scalar_one()
            rows = (await db.execute(
                select(SkillRow).where(
                    SkillRow.id.like(f"{prefix}%"), SkillRow.archived_at.is_(None),
                )
                .order_by(SkillRow.updated_at.desc())
                .limit(clamped_limit).offset(clamped_offset)
            )).scalars().all()
        if not rows and clamped_offset == 0:
            return json.dumps({"skills": [], "total": 0, "message": "No self-authored skills yet."}, ensure_ascii=False)
        summary = []
        stale_count = 0
        for r in rows:
            fm = _extract_frontmatter(r.content) if r.content else {}
            body_preview = _extract_body(r.content)[:120].strip() if r.content else ""
            stale = _is_stale(r.created_at, r.last_surfaced_at, r.surface_count)
            if stale:
                stale_count += 1
            summary.append({
                "id": r.id,
                "name": r.name,
                "category": fm.get("category", ""),
                "preview": body_preview,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                "last_surfaced_at": r.last_surfaced_at.isoformat() if r.last_surfaced_at else None,
                "surface_count": r.surface_count,
                "stale": stale,
                "script_count": len(r.scripts or []),
                "scripts": _summarize_scripts(r.scripts),
            })
        result: dict = {
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
        return json.dumps(result, ensure_ascii=False)

    # --- GET ---
    if action == "get":
        # Batch form: action="get" + names=[...] — fetch several skills in
        # one call so hygiene / skill-review runs don't burn an iteration
        # per skill body. Single-name form below is preserved unchanged.
        if names:
            if len(names) > 50:
                return json.dumps({
                    "error": f"Too many names ({len(names)}). Cap is 50 for batch get.",
                }, ensure_ascii=False)
            async with async_session() as db:
                out: list[dict] = []
                missing: list[str] = []
                for n in names:
                    sid, err = _safe_skill_id(bot_id, n)
                    if err or sid is None:
                        missing.append(n)
                        continue
                    row = await db.get(SkillRow, sid)
                    if row is None:
                        missing.append(n)
                        continue
                    out.append({
                        "id": row.id,
                        "name": row.name,
                        "content": row.content,
                        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                        "scripts": _summarize_scripts(row.scripts),
                    })
            return json.dumps({"skills": out, "missing": missing}, ensure_ascii=False)

        if not name:
            return json.dumps({"error": "name is required for get action."}, ensure_ascii=False)
        skill_id, err = _safe_skill_id(bot_id, name)
        if err:
            return err
        async with async_session() as db:
            row = await db.get(SkillRow, skill_id)
        if not row:
            return json.dumps({"error": f"Skill '{skill_id}' not found."}, ensure_ascii=False)
        return json.dumps({
            "id": row.id,
            "name": row.name,
            "content": row.content,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "scripts": _summarize_scripts(row.scripts),
        }, ensure_ascii=False)

    # --- GET SCRIPT ---
    if action == "get_script":
        if not name or not script_name:
            return json.dumps({"error": "name and script_name are required for get_script action."}, ensure_ascii=False)
        skill_id, err = _safe_skill_id(bot_id, name)
        if err:
            return err
        async with async_session() as db:
            row = await db.get(SkillRow, skill_id)
        if not row:
            return json.dumps({"error": f"Skill '{skill_id}' not found."}, ensure_ascii=False)
        script_row = _get_script_by_name(row.scripts, script_name)
        if not script_row:
            return json.dumps({"error": f"Script '{_normalize_script_name(script_name)}' not found on '{skill_id}'."}, ensure_ascii=False)
        return json.dumps({
            "ok": True,
            "id": row.id,
            "script_name": script_row["name"],
            "script_description": script_row.get("description", ""),
            "script_body": script_row.get("script", ""),
            "script_timeout_s": script_row.get("timeout_s"),
        }, ensure_ascii=False)

    # --- UPSERT ---
    # Resolves to create-or-update based on existence, so callers don't have
    # to round-trip to check first. Falls through to the regular branches.
    if action == "upsert":
        if not name:
            return json.dumps({"error": "name is required for upsert action."}, ensure_ascii=False)
        skill_id, err = _safe_skill_id(bot_id, name)
        if err:
            return err
        async with async_session() as db:
            existing = await db.get(SkillRow, skill_id)
        action = "update" if existing else "create"

    # --- CREATE ---
    if action == "create":
        if not name or not title or not content:
            return json.dumps({"error": "name, title, and content are required for create."}, ensure_ascii=False)
        name_err = _validate_name(name)
        if name_err:
            return json.dumps({"error": name_err}, ensure_ascii=False)
        content_err = _validate_content(content)
        if content_err:
            return json.dumps({"error": content_err}, ensure_ascii=False)
        normalized_scripts, scripts_err = _validate_scripts_payload(scripts, require_description=True)
        if scripts_err:
            return json.dumps({"error": scripts_err}, ensure_ascii=False)
        skill_id, err = _safe_skill_id(bot_id, name)
        if err:
            return err

        # Dedup check: find semantically similar existing skills
        if not force:
            dedup_result = await _check_skill_dedup(bot_id, content, prefix)
            if dedup_result:
                return dedup_result

        full_content = _build_content(title, content, triggers, category)
        content_hash = hashlib.sha256(full_content.encode()).hexdigest()

        async with async_session() as db:
            existing = await db.get(SkillRow, skill_id)
            if existing:
                return json.dumps({"error": f"Skill '{skill_id}' already exists. Use update or patch."}, ensure_ascii=False)

            now = datetime.now(timezone.utc)
            # Parse triggers into list for the DB column
            _triggers_list = [t.strip() for t in triggers.split(",") if t.strip()] if triggers else []
            row = SkillRow(
                id=skill_id,
                name=title.strip(),
                description=content[:200].strip() if content else None,
                category=category.strip() if category else None,
                triggers=_triggers_list,
                scripts=normalized_scripts,
                content=full_content,
                content_hash=content_hash,
                source_type="tool",
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            await db.commit()

        # Synchronous embedding so the bot knows immediately if it worked
        embedded = await _embed_skill_safe(skill_id)
        _invalidate_cache(bot_id)

        # Count warning
        warning = await _check_count_warning(bot_id, prefix)
        msg = f"Skill '{skill_id}' created."
        if not embedded:
            msg += " Warning: embedding failed — skill saved but won't appear in RAG until re-embedded."
        if warning:
            msg += f" {warning}"
        return json.dumps({"ok": True, "id": skill_id, "embedded": embedded, "message": msg}, ensure_ascii=False)

    # --- UPDATE ---
    if action == "update":
        if not name:
            return json.dumps({"error": "name is required for update action."}, ensure_ascii=False)
        skill_id, err = _safe_skill_id(bot_id, name)
        if err:
            return err

        async with async_session() as db:
            row = await db.get(SkillRow, skill_id)
            if not row:
                return json.dumps({"error": f"Skill '{skill_id}' not found."}, ensure_ascii=False)
            if row.source_type not in ("tool", "manual"):
                return json.dumps({"error": "Cannot edit a file-managed or integration skill."}, ensure_ascii=False)
            if not row.id.startswith(prefix):
                return json.dumps({"error": "Cannot update another bot's skill."}, ensure_ascii=False)

            if not title and not content and not triggers and not category:
                if scripts is None:
                    return json.dumps({"error": "Provide at least one of: title, content, triggers, category, scripts."}, ensure_ascii=False)

            if content:
                content_err = _validate_content(content)
                if content_err:
                    return json.dumps({"error": content_err}, ensure_ascii=False)
            normalized_scripts: list[dict] | None = None
            if scripts is not None:
                normalized_scripts, scripts_err = _validate_scripts_payload(scripts, require_description=True)
                if scripts_err:
                    return json.dumps({"error": scripts_err}, ensure_ascii=False)

            # Merge with existing frontmatter so partial updates don't drop fields
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

            # Keep DB columns in sync with frontmatter
            _triggers_list = [t.strip() for t in new_triggers.split(",") if t.strip()] if new_triggers else []
            row.triggers = _triggers_list
            if new_category:
                row.category = new_category.strip()
            if content:
                row.description = content[:200].strip()
            if normalized_scripts is not None:
                row.scripts = normalized_scripts

            row.updated_at = datetime.now(timezone.utc)
            await db.commit()

        # Fire-and-forget for updates (skill already in RAG, re-embed in background)
        asyncio.create_task(_embed_skill_safe(skill_id))
        _invalidate_cache(bot_id)
        return json.dumps({"ok": True, "id": skill_id, "message": f"Skill '{skill_id}' updated."}, ensure_ascii=False)

    # --- DELETE (archive) ---
    if action == "delete":
        if not name:
            return json.dumps({"error": "name is required for delete action."}, ensure_ascii=False)
        skill_id, err = _safe_skill_id(bot_id, name)
        if err:
            return err

        async with async_session() as db:
            row = await db.get(SkillRow, skill_id)
            if not row:
                return json.dumps({"error": f"Skill '{skill_id}' not found."}, ensure_ascii=False)
            if row.source_type not in ("tool", "manual"):
                return json.dumps({"error": "Cannot delete a file-managed or integration skill."}, ensure_ascii=False)
            if not row.id.startswith(prefix):
                return json.dumps({"error": "Cannot delete another bot's skill."}, ensure_ascii=False)
            if row.archived_at:
                return json.dumps({"error": f"Skill '{skill_id}' is already archived."}, ensure_ascii=False)
            row.archived_at = datetime.now(timezone.utc)
            await db.commit()

        _invalidate_cache(bot_id)
        return json.dumps({"ok": True, "id": skill_id, "message": f"Skill '{skill_id}' archived. Use action='restore' to undo."}, ensure_ascii=False)

    # --- RESTORE ---
    if action == "restore":
        if not name:
            return json.dumps({"error": "name is required for restore action."}, ensure_ascii=False)
        skill_id, err = _safe_skill_id(bot_id, name)
        if err:
            return err

        async with async_session() as db:
            row = await db.get(SkillRow, skill_id)
            if not row:
                return json.dumps({"error": f"Skill '{skill_id}' not found."}, ensure_ascii=False)
            if not row.id.startswith(prefix):
                return json.dumps({"error": "Cannot restore another bot's skill."}, ensure_ascii=False)
            if not row.archived_at:
                return json.dumps({"error": f"Skill '{skill_id}' is not archived."}, ensure_ascii=False)
            row.archived_at = None
            await db.commit()

        _invalidate_cache(bot_id)
        return json.dumps({"ok": True, "id": skill_id, "message": f"Skill '{skill_id}' restored."}, ensure_ascii=False)

    # --- PATCH ---
    if action == "patch":
        if not name:
            return json.dumps({"error": "name is required for patch action."}, ensure_ascii=False)
        if not old_text or not new_text:
            return json.dumps({"error": "old_text and new_text are required for patch action."}, ensure_ascii=False)
        skill_id, err = _safe_skill_id(bot_id, name)
        if err:
            return err

        async with async_session() as db:
            row = await db.get(SkillRow, skill_id)
            if not row:
                return json.dumps({"error": f"Skill '{skill_id}' not found."}, ensure_ascii=False)
            if row.source_type not in ("tool", "manual"):
                return json.dumps({"error": "Cannot patch a file-managed or integration skill."}, ensure_ascii=False)
            if not row.id.startswith(prefix):
                return json.dumps({"error": "Cannot patch another bot's skill."}, ensure_ascii=False)

            if old_text not in row.content:
                return json.dumps({"error": "old_text not found in skill content."}, ensure_ascii=False)

            patched = row.content.replace(old_text, new_text, 1)
            # Validate resulting content (patch could shrink below min or expand above max)
            body = _extract_body(patched)
            body_err = _validate_content(body)
            if body_err:
                return json.dumps({"error": f"Patch would produce invalid content: {body_err}"}, ensure_ascii=False)

            row.content = patched
            row.content_hash = hashlib.sha256(row.content.encode()).hexdigest()

            # Keep DB columns in sync with patched content
            patched_fm = _extract_frontmatter(patched)
            patched_body = _extract_body(patched)
            row.name = patched_fm.get("name", row.name)
            row.description = patched_body[:200].strip() if patched_body else row.description
            _patched_triggers = patched_fm.get("triggers", "")
            row.triggers = [t.strip() for t in _patched_triggers.split(",") if t.strip()] if _patched_triggers else (row.triggers or [])
            _patched_category = patched_fm.get("category", "")
            if _patched_category:
                row.category = _patched_category.strip()

            row.updated_at = datetime.now(timezone.utc)
            await db.commit()

        asyncio.create_task(_embed_skill_safe(skill_id))
        _invalidate_cache(bot_id)
        return json.dumps({"ok": True, "id": skill_id, "message": f"Skill '{skill_id}' patched."}, ensure_ascii=False)

    # --- MERGE ---
    if action == "merge":
        if not names or len(names) < 2:
            return json.dumps({"error": "names must contain at least 2 skill names to merge."}, ensure_ascii=False)
        if not name or not title or not content:
            return json.dumps({
                "error": "name, title, and content are required for the merged result skill.",
            }, ensure_ascii=False)
        name_err = _validate_name(name)
        if name_err:
            return json.dumps({"error": name_err}, ensure_ascii=False)
        content_err = _validate_content(content)
        if content_err:
            return json.dumps({"error": content_err}, ensure_ascii=False)
        normalized_scripts, scripts_err = _validate_scripts_payload(scripts, require_description=True)
        if scripts_err:
            return json.dumps({"error": scripts_err}, ensure_ascii=False)
        merged_id, err = _safe_skill_id(bot_id, name)
        if err:
            return err

        from sqlalchemy import delete as sa_delete
        from app.db.models import Document

        # Resolve all source skill IDs and verify they exist + are owned
        source_ids: list[str] = []
        seen: set[str] = set()
        for src_name in names:
            src_id, src_err = _safe_skill_id(bot_id, src_name)
            if src_err:
                return src_err
            if src_id not in seen:
                source_ids.append(src_id)
                seen.add(src_id)
        if len(source_ids) < 2:
            return json.dumps({"error": "names must contain at least 2 distinct skill names to merge."}, ensure_ascii=False)

        async with async_session() as db:
            # Load all source skills in one pass — validate and keep refs for deletion
            source_rows: list = []
            for src_id in source_ids:
                row = await db.get(SkillRow, src_id)
                if not row:
                    return json.dumps({"error": f"Source skill '{src_id}' not found."}, ensure_ascii=False)
                if row.source_type not in ("tool", "manual"):
                    return json.dumps({"error": f"Cannot merge file-managed skill '{src_id}'."}, ensure_ascii=False)
                if not row.id.startswith(prefix):
                    return json.dumps({"error": f"Cannot merge another bot's skill '{src_id}'."}, ensure_ascii=False)
                source_rows.append(row)

            merged_scripts = normalized_scripts
            if scripts is None:
                merged_scripts = []
                seen_script_names: set[str] = set()
                for row in source_rows:
                    for attached in row.scripts or []:
                        attached_name = attached.get("name", "")
                        if attached_name in seen_script_names:
                            return json.dumps({
                                "error": (
                                    f"Cannot merge scripts automatically: duplicate attached script "
                                    f"name '{attached_name}'. Provide scripts=[...] on the merge action."
                                ),
                            }, ensure_ascii=False)
                        merged_scripts.append(attached)
                        seen_script_names.add(attached_name)

            # Check if merged target already exists (and isn't one of the sources)
            existing = await db.get(SkillRow, merged_id)
            if existing and merged_id not in source_ids:
                return json.dumps({"error": f"Target skill '{merged_id}' already exists and is not one of the source skills."}, ensure_ascii=False)

            # Delete source skills + their embeddings
            deleted_names = []
            for row in source_rows:
                deleted_names.append(row.name)
                await db.delete(row)
                await db.execute(sa_delete(Document).where(Document.source == f"skill:{row.id}"))

            # Create the merged skill
            full_content = _build_content(title, content, triggers, category)
            content_hash = hashlib.sha256(full_content.encode()).hexdigest()
            now = datetime.now(timezone.utc)
            _triggers_list = [t.strip() for t in triggers.split(",") if t.strip()] if triggers else []
            merged_row = SkillRow(
                id=merged_id,
                name=title.strip(),
                description=content[:200].strip() if content else None,
                category=category.strip() if category else None,
                triggers=_triggers_list,
                scripts=merged_scripts,
                content=full_content,
                content_hash=content_hash,
                source_type="tool",
                created_at=now,
                updated_at=now,
            )
            db.add(merged_row)
            await db.commit()

        embedded = await _embed_skill_safe(merged_id)
        _invalidate_cache(bot_id)
        return json.dumps({
            "ok": True,
            "id": merged_id,
            "embedded": embedded,
            "deleted": source_ids,
            "message": (
                f"Merged {len(source_ids)} skills into '{merged_id}'. "
                f"Deleted: {', '.join(deleted_names)}."
            ),
        }, ensure_ascii=False)

    # --- ADD SCRIPT ---
    if action == "add_script":
        if not name or not script_name or not script_body or not script_description:
            return json.dumps({
                "error": "name, script_name, script_description, and script_body are required for add_script action.",
            }, ensure_ascii=False)
        skill_id, err = _safe_skill_id(bot_id, name)
        if err:
            return err
        new_scripts, scripts_err = _validate_scripts_payload([{
            "name": script_name,
            "description": script_description,
            "script": script_body,
            "timeout_s": script_timeout_s,
        }], require_description=True)
        if scripts_err:
            return json.dumps({"error": scripts_err}, ensure_ascii=False)
        new_script = new_scripts[0]
        async with async_session() as db:
            row = await db.get(SkillRow, skill_id)
            if not row:
                return json.dumps({"error": f"Skill '{skill_id}' not found."}, ensure_ascii=False)
            if row.source_type not in ("tool", "manual"):
                return json.dumps({"error": "Cannot edit scripts on a file-managed or integration skill."}, ensure_ascii=False)
            if _get_script_by_name(row.scripts, new_script["name"]):
                return json.dumps({"error": f"Script '{new_script['name']}' already exists on '{skill_id}'."}, ensure_ascii=False)
            combined_scripts, combined_err = _validate_scripts_payload(
                [*(row.scripts or []), new_script],
                require_description=True,
            )
            if combined_err:
                return json.dumps({"error": combined_err}, ensure_ascii=False)
            row.scripts = combined_scripts
            row.updated_at = datetime.now(timezone.utc)
            await db.commit()
        _invalidate_cache(bot_id)
        return json.dumps({"ok": True, "id": skill_id, "message": f"Script '{new_script['name']}' added to '{skill_id}'."}, ensure_ascii=False)

    # --- UPDATE SCRIPT ---
    if action == "update_script":
        if not name or not script_name:
            return json.dumps({"error": "name and script_name are required for update_script action."}, ensure_ascii=False)
        skill_id, err = _safe_skill_id(bot_id, name)
        if err:
            return err
        normalized_name = _normalize_script_name(script_name)
        async with async_session() as db:
            row = await db.get(SkillRow, skill_id)
            if not row:
                return json.dumps({"error": f"Skill '{skill_id}' not found."}, ensure_ascii=False)
            if row.source_type not in ("tool", "manual"):
                return json.dumps({"error": "Cannot edit scripts on a file-managed or integration skill."}, ensure_ascii=False)
            current = _get_script_by_name(row.scripts, normalized_name)
            if not current:
                return json.dumps({"error": f"Script '{normalized_name}' not found on '{skill_id}'."}, ensure_ascii=False)
            next_name = current["name"]
            next_description = current.get("description", "")
            next_body = current.get("script", "")
            next_timeout = current.get("timeout_s")
            if script_description:
                next_description = script_description
            if script_body:
                next_body = script_body
            if script_timeout_s is not None:
                next_timeout = script_timeout_s
            new_scripts, scripts_err = _validate_scripts_payload([{
                "name": next_name,
                "description": next_description,
                "script": next_body,
                "timeout_s": next_timeout,
            }], require_description=True)
            if scripts_err:
                return json.dumps({"error": scripts_err}, ensure_ascii=False)
            updated_script = new_scripts[0]
            replaced = []
            for attached in row.scripts or []:
                replaced.append(updated_script if attached.get("name") == normalized_name else attached)
            row.scripts = replaced
            row.updated_at = datetime.now(timezone.utc)
            await db.commit()
        _invalidate_cache(bot_id)
        return json.dumps({"ok": True, "id": skill_id, "message": f"Script '{normalized_name}' updated on '{skill_id}'."}, ensure_ascii=False)

    # --- DELETE SCRIPT ---
    if action == "delete_script":
        if not name or not script_name:
            return json.dumps({"error": "name and script_name are required for delete_script action."}, ensure_ascii=False)
        skill_id, err = _safe_skill_id(bot_id, name)
        if err:
            return err
        normalized_name = _normalize_script_name(script_name)
        async with async_session() as db:
            row = await db.get(SkillRow, skill_id)
            if not row:
                return json.dumps({"error": f"Skill '{skill_id}' not found."}, ensure_ascii=False)
            if row.source_type not in ("tool", "manual"):
                return json.dumps({"error": "Cannot edit scripts on a file-managed or integration skill."}, ensure_ascii=False)
            current_scripts = row.scripts or []
            if not _get_script_by_name(current_scripts, normalized_name):
                return json.dumps({"error": f"Script '{normalized_name}' not found on '{skill_id}'."}, ensure_ascii=False)
            row.scripts = [attached for attached in current_scripts if attached.get("name") != normalized_name]
            row.updated_at = datetime.now(timezone.utc)
            await db.commit()
        _invalidate_cache(bot_id)
        return json.dumps({"ok": True, "id": skill_id, "message": f"Script '{normalized_name}' deleted from '{skill_id}'."}, ensure_ascii=False)

    return json.dumps({
        "error": (
            f"Unknown action: {action}. Use create, update, upsert, list, get, delete, "
            "patch, merge, restore, get_script, add_script, update_script, or delete_script."
        ),
    }, ensure_ascii=False)


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
