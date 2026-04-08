"""get_skill tool — lets the agent fetch the full content of a configured skill on demand."""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import update

from app.agent.context import current_bot_id
from app.tools.registry import register
from app.db.engine import async_session
from app.db.models import Skill as SkillRow

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "get_skill",
        "description": (
            "Retrieve the full content of a skill from the knowledge base by its ID. "
            "Use this when you need detailed information from one of your configured skills. "
            "The skill index in your system context shows which skills are available."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "skill_id": {
                    "type": "string",
                    "description": "The skill ID to retrieve (e.g. 'arch_linux', 'cooking')",
                },
            },
            "required": ["skill_id"],
        },
    },
})
async def get_skill(skill_id: str) -> str:
    """Fetch the full content of a skill from DB."""
    bot_id = current_bot_id.get()

    # Validate that this bot has access to this skill
    if bot_id:
        try:
            from app.agent.bots import get_bot
            bot = get_bot(bot_id)
            if bot.skills and skill_id not in bot.skill_ids:
                # Check carapace-resolved skills (set by context_assembly)
                from app.agent.context import current_resolved_skill_ids, current_ephemeral_skills
                _resolved = current_resolved_skill_ids.get()
                if _resolved and skill_id in _resolved:
                    pass  # carapace-injected skill — allow access
                # Check ephemeral @-tagged skills
                elif skill_id in (current_ephemeral_skills.get() or []):
                    pass  # tagged skill — allow access
                elif skill_id.startswith(f"bots/{bot_id}/"):
                    pass  # bot's own self-authored skill — always allow
                else:
                    # Check workspace DB skills and channel skills_extra
                    _allowed = await _check_extra_skill_access(bot, skill_id)
                    if not _allowed:
                        # Cold-path fallback: resolve carapaces fresh (covers delegation
                        # and cases where context var wasn't set)
                        _allowed = _check_carapace_skill_access(bot, skill_id)
                    if not _allowed:
                        logger.debug(
                            "get_skill access denied: skill=%s bot=%s resolved=%s ephemeral=%s",
                            skill_id, bot_id, _resolved, current_ephemeral_skills.get(),
                        )
                        return f"Skill '{skill_id}' is not configured for this bot."
        except Exception:
            pass  # bot not found — proceed without access check

    # Fetch from DB
    async with async_session() as db:
        row = await db.get(SkillRow, skill_id)
        if not row:
            return f"Skill '{skill_id}' not found."

    # Track surfacing (fire-and-forget) — only counts actual LLM-initiated fetches
    asyncio.create_task(_increment_surface_count(skill_id))

    return f"# {row.name}\n\n{row.content}"


@register({
    "type": "function",
    "function": {
        "name": "get_skill_list",
        "description": (
            "List all available skills with their IDs, names, and descriptions. "
            "Use this to discover skills when the skill index in your context "
            "doesn't show what you need."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
})
async def get_skill_list() -> str:
    """Return the full flat index of all on-demand skills configured for this bot."""
    from sqlalchemy import select

    bot_id = current_bot_id.get()
    if not bot_id:
        return "No bot context available."

    # Use resolved skill IDs (includes auto-enrolled core/integration skills)
    from app.agent.context import current_resolved_skill_ids
    resolved = current_resolved_skill_ids.get()

    if resolved:
        skill_ids = list(resolved)
    else:
        # Fallback to bot config if context var not set
        try:
            from app.agent.bots import get_bot
            bot = get_bot(bot_id)
        except Exception:
            return "Bot not found."
        if not bot.skills:
            return "No skills configured."
        skill_ids = [s.id for s in bot.skills if s.mode != "pinned"]

    if not skill_ids:
        return "No on-demand skills configured."

    async with async_session() as db:
        rows = (await db.execute(
            select(SkillRow.id, SkillRow.name, SkillRow.description, SkillRow.triggers)
            .where(SkillRow.id.in_(skill_ids))
        )).all()

    if not rows:
        return "No skills found in database."

    lines = []
    for r in rows:
        parts = [f"- {r.id}: {r.name}"]
        if r.description:
            parts.append(f" — {r.description}")
        if r.triggers:
            parts.append(f" [{', '.join(r.triggers)}]")
        lines.append("".join(parts))

    return f"All available skills ({len(lines)}):\n" + "\n".join(lines)


def _check_carapace_skill_access(bot, skill_id: str) -> bool:
    """Cold-path fallback: resolve bot's carapaces and check if skill_id is included."""
    try:
        carapace_ids = list(bot.carapaces or [])
        if not carapace_ids:
            return False
        from app.agent.carapaces import resolve_carapaces
        resolved = resolve_carapaces(carapace_ids)
        resolved_skill_ids = {s.id for s in resolved.skills}
        if skill_id in resolved_skill_ids:
            return True
    except Exception:
        logger.debug("Carapace fallback check failed for skill %s", skill_id, exc_info=True)

    # Also check activated integration carapaces if channel_id is available
    try:
        from app.agent.context import current_channel_id
        ch_id = current_channel_id.get()
        if ch_id:
            return _check_activated_integration_skill(ch_id, skill_id)
    except Exception:
        logger.debug("Activated integration skill check failed for %s", skill_id, exc_info=True)

    return False


def _check_activated_integration_skill(channel_id, skill_id: str) -> bool:
    """Check if skill_id comes from an activated integration's carapaces (sync, for fallback)."""
    try:
        from app.agent.carapaces import resolve_carapaces
        from integrations import get_activation_manifests
        # We need the channel's integrations — but this is a sync fallback so we can't do DB.
        # The _registry is always available though.  The real fix is the snapshot/restore
        # above; this catches edge cases where context_assembly didn't run.
        manifests = get_activation_manifests()
        all_activation_carapace_ids = set()
        for manifest in manifests.values():
            for cap_id in manifest.get("carapaces", []):
                all_activation_carapace_ids.add(cap_id)
        if all_activation_carapace_ids:
            resolved = resolve_carapaces(list(all_activation_carapace_ids))
            if skill_id in {s.id for s in resolved.skills}:
                return True
    except Exception:
        pass
    return False


async def _check_extra_skill_access(bot, skill_id: str) -> bool:
    """Check if skill_id is allowed via workspace DB skills, channel skills_extra,
    or channel carapaces_extra (resolved to their skills)."""
    # Check workspace DB skills
    try:
        import uuid as _uuid
        from app.db.models import SharedWorkspace
        async with async_session() as db:
            ws_row = await db.get(SharedWorkspace, _uuid.UUID(bot.shared_workspace_id))
        if ws_row and ws_row.skills:
            if any(
                (e["id"] if isinstance(e, dict) else e) == skill_id
                for e in ws_row.skills
            ):
                return True
    except Exception:
        pass

    # Check channel skills_extra and carapaces_extra
    try:
        from app.agent.context import current_channel_id
        _ch_id = current_channel_id.get()
        if _ch_id:
            from app.db.models import Channel
            async with async_session() as db:
                ch = await db.get(Channel, _ch_id)
            if ch:
                # Direct skill_extra check
                if ch.skills_extra and any(
                    (e["id"] if isinstance(e, dict) else e) == skill_id
                    for e in ch.skills_extra
                ):
                    return True
                # Resolve channel's carapaces_extra to check their skills
                _ch_carapaces = getattr(ch, "carapaces_extra", None)
                if _ch_carapaces:
                    from app.agent.carapaces import resolve_carapaces
                    _resolved = resolve_carapaces(_ch_carapaces)
                    if skill_id in {s.id for s in _resolved.skills}:
                        return True
    except Exception:
        pass

    return False


async def _increment_surface_count(skill_id: str) -> None:
    """Increment surface_count and last_surfaced_at for a skill (fire-and-forget)."""
    try:
        async with async_session() as db:
            await db.execute(
                update(SkillRow)
                .where(SkillRow.id == skill_id)
                .values(
                    last_surfaced_at=datetime.now(timezone.utc),
                    surface_count=SkillRow.surface_count + 1,
                )
            )
            await db.commit()
    except Exception:
        logger.debug("Failed to update skill surfacing for %s", skill_id, exc_info=True)
