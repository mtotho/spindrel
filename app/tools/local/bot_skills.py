"""Local tool: manage_bot_skill — self-authored skill CRUD for bots."""

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timezone

from app.agent.context import current_bot_id
from app.tools.registry import register

logger = logging.getLogger(__name__)

BOT_SKILL_COUNT_WARNING = 50

_SLUG_RE = re.compile(r"[^a-z0-9-]")


def _slugify(name: str) -> str:
    """Normalize a name to a URL-safe slug."""
    slug = name.strip().lower().replace(" ", "-")
    slug = _SLUG_RE.sub("", slug)  # strip anything not alphanumeric or hyphen
    slug = re.sub(r"-+", "-", slug).strip("-")  # collapse multiple hyphens
    return slug


def _bot_skill_id(bot_id: str, name: str) -> str:
    """Build the canonical skill ID for a bot-authored skill.

    Raises ValueError if the name produces an empty slug.
    """
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
        })


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


def _build_content(title: str, content: str, triggers: str = "", category: str = "") -> str:
    """Build skill content with YAML frontmatter."""
    lines = ["---"]
    lines.append(f"name: {title}")
    if triggers:
        lines.append(f"triggers: {triggers}")
    if category:
        lines.append(f"category: {category}")
    lines.append("---")
    lines.append("")
    lines.append(content)
    return "\n".join(lines)


@register({
    "type": "function",
    "function": {
        "name": "manage_bot_skill",
        "description": (
            "Create, update, list, get, delete, or patch your own reusable skills. "
            "Skills you author enter the RAG pipeline and are semantically retrievable "
            "in future sessions. Use this to capture solution patterns, domain knowledge, "
            "troubleshooting guides, and procedures you've learned."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "update", "list", "get", "delete", "patch"],
                    "description": "The action to perform.",
                },
                "name": {
                    "type": "string",
                    "description": (
                        "Skill slug (lowercase, hyphens). Becomes bots/{bot_id}/{name}. "
                        "Required for create, update, get, delete, patch."
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
                "old_text": {
                    "type": "string",
                    "description": "Text to find in content (for patch action).",
                },
                "new_text": {
                    "type": "string",
                    "description": "Replacement text (for patch action).",
                },
            },
            "required": ["action"],
        },
    },
})
async def manage_bot_skill(
    action: str,
    name: str = "",
    title: str = "",
    content: str = "",
    triggers: str = "",
    category: str = "",
    old_text: str = "",
    new_text: str = "",
) -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context — cannot manage skills."})

    from app.db.engine import async_session
    from app.db.models import Skill as SkillRow

    prefix = f"bots/{bot_id}/"

    # --- LIST ---
    if action == "list":
        from sqlalchemy import select
        async with async_session() as db:
            rows = (await db.execute(
                select(SkillRow).where(SkillRow.id.like(f"{prefix}%"))
                .order_by(SkillRow.updated_at.desc())
            )).scalars().all()
        if not rows:
            return json.dumps({"skills": [], "message": "No self-authored skills yet."})
        summary = [
            {
                "id": r.id,
                "name": r.name,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]
        return json.dumps({"skills": summary, "count": len(summary)})

    # --- GET ---
    if action == "get":
        if not name:
            return json.dumps({"error": "name is required for get action."})
        skill_id, err = _safe_skill_id(bot_id, name)
        if err:
            return err
        async with async_session() as db:
            row = await db.get(SkillRow, skill_id)
        if not row:
            return json.dumps({"error": f"Skill '{skill_id}' not found."})
        return json.dumps({
            "id": row.id,
            "name": row.name,
            "content": row.content,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        })

    # --- CREATE ---
    if action == "create":
        if not name or not title or not content:
            return json.dumps({"error": "name, title, and content are required for create."})
        skill_id, err = _safe_skill_id(bot_id, name)
        if err:
            return err
        full_content = _build_content(title, content, triggers, category)
        content_hash = hashlib.sha256(full_content.encode()).hexdigest()

        async with async_session() as db:
            existing = await db.get(SkillRow, skill_id)
            if existing:
                return json.dumps({"error": f"Skill '{skill_id}' already exists. Use update or patch."})

            now = datetime.now(timezone.utc)
            row = SkillRow(
                id=skill_id,
                name=title.strip(),
                content=full_content,
                content_hash=content_hash,
                source_type="tool",
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            await db.commit()

        # Fire-and-forget embedding
        asyncio.create_task(_embed_skill_safe(skill_id))

        # Count warning
        warning = await _check_count_warning(bot_id, prefix)
        msg = f"Skill '{skill_id}' created."
        if warning:
            msg += f" {warning}"
        return json.dumps({"ok": True, "id": skill_id, "message": msg})

    # --- UPDATE ---
    if action == "update":
        if not name:
            return json.dumps({"error": "name is required for update action."})
        skill_id, err = _safe_skill_id(bot_id, name)
        if err:
            return err

        async with async_session() as db:
            row = await db.get(SkillRow, skill_id)
            if not row:
                return json.dumps({"error": f"Skill '{skill_id}' not found."})
            if row.source_type not in ("tool", "manual"):
                return json.dumps({"error": "Cannot edit a file-managed or integration skill."})
            if not row.id.startswith(prefix):
                return json.dumps({"error": "Cannot update another bot's skill."})

            if not title and not content and not triggers and not category:
                return json.dumps({"error": "Provide at least one of: title, content, triggers, category."})

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

            row.updated_at = datetime.now(timezone.utc)
            await db.commit()

        asyncio.create_task(_embed_skill_safe(skill_id))
        return json.dumps({"ok": True, "id": skill_id, "message": f"Skill '{skill_id}' updated."})

    # --- DELETE ---
    if action == "delete":
        if not name:
            return json.dumps({"error": "name is required for delete action."})
        skill_id, err = _safe_skill_id(bot_id, name)
        if err:
            return err

        from sqlalchemy import delete as sa_delete
        from app.db.models import Document

        async with async_session() as db:
            row = await db.get(SkillRow, skill_id)
            if not row:
                return json.dumps({"error": f"Skill '{skill_id}' not found."})
            if row.source_type not in ("tool", "manual"):
                return json.dumps({"error": "Cannot delete a file-managed or integration skill."})
            if not row.id.startswith(prefix):
                return json.dumps({"error": "Cannot delete another bot's skill."})
            await db.delete(row)
            await db.execute(sa_delete(Document).where(Document.source == f"skill:{skill_id}"))
            await db.commit()

        return json.dumps({"ok": True, "id": skill_id, "message": f"Skill '{skill_id}' deleted."})

    # --- PATCH ---
    if action == "patch":
        if not name:
            return json.dumps({"error": "name is required for patch action."})
        if not old_text or not new_text:
            return json.dumps({"error": "old_text and new_text are required for patch action."})
        skill_id, err = _safe_skill_id(bot_id, name)
        if err:
            return err

        async with async_session() as db:
            row = await db.get(SkillRow, skill_id)
            if not row:
                return json.dumps({"error": f"Skill '{skill_id}' not found."})
            if row.source_type not in ("tool", "manual"):
                return json.dumps({"error": "Cannot patch a file-managed or integration skill."})
            if not row.id.startswith(prefix):
                return json.dumps({"error": "Cannot patch another bot's skill."})

            if old_text not in row.content:
                return json.dumps({"error": "old_text not found in skill content."})

            row.content = row.content.replace(old_text, new_text, 1)
            row.content_hash = hashlib.sha256(row.content.encode()).hexdigest()
            row.updated_at = datetime.now(timezone.utc)
            await db.commit()

        asyncio.create_task(_embed_skill_safe(skill_id))
        return json.dumps({"ok": True, "id": skill_id, "message": f"Skill '{skill_id}' patched."})

    return json.dumps({"error": f"Unknown action: {action}. Use create, update, list, get, delete, or patch."})


async def _embed_skill_safe(skill_id: str) -> None:
    """Re-embed a skill, swallowing errors so fire-and-forget doesn't crash."""
    try:
        from app.agent.skills import re_embed_skill
        await re_embed_skill(skill_id)
    except Exception:
        logger.warning("Failed to re-embed skill '%s'", skill_id, exc_info=True)


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
