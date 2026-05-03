"""Skill enrollment loading for the tool-surface composer.

Owns bot-authored skill discovery, core/integration skill auto-enroll
caches, and the per-turn enrollment loader that merges enrolled skill ids
into the active `BotConfig`. The canonical enrollment service lives at
`app/services/skill_enrollment.py`; this module is the agent-loop wrapper
that previously lived inline in `context_assembly`.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from app.agent.bots import BotConfig
from app.agent.rag import fetch_skill_chunks_by_id

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bot-authored skill auto-discovery cache (avoids DB hit on every message)
# ---------------------------------------------------------------------------
_bot_skill_cache: dict[str, tuple[float, list[str]]] = {}  # bot_id → (timestamp, [skill_ids])
_BOT_SKILL_CACHE_TTL = 30.0  # seconds


async def _get_bot_authored_skill_ids(bot_id: str) -> list[str]:
    """Return skill IDs for bot-authored skills, with a short TTL cache."""
    import time
    now = time.monotonic()
    cached = _bot_skill_cache.get(bot_id)
    if cached and (now - cached[0]) < _BOT_SKILL_CACHE_TTL:
        return cached[1]

    from sqlalchemy import select as _sa_select
    from app.db.engine import async_session as _bas_session
    from app.db.models import Skill as _SkillRow

    prefix = f"bots/{bot_id}/"
    async with _bas_session() as _bas_db:
        rows = (await _bas_db.execute(
            _sa_select(_SkillRow.id).where(
                _SkillRow.id.like(f"{prefix}%"),
                _SkillRow.source_type == "tool",
                _SkillRow.archived_at.is_(None),
            )
        )).scalars().all()

    result = list(rows)
    _bot_skill_cache[bot_id] = (now, result)
    return result


def invalidate_bot_skill_cache(bot_id: str | None = None) -> None:
    """Clear the bot-authored skill discovery cache.

    Called after create/update/delete to ensure next context assembly sees changes.
    """
    if bot_id:
        _bot_skill_cache.pop(bot_id, None)
    else:
        _bot_skill_cache.clear()


# ---------------------------------------------------------------------------
# Core + integration skill auto-enrollment cache
# ---------------------------------------------------------------------------
_core_skill_cache: tuple[float, list[str]] | None = None
_integration_skill_cache: dict[str, tuple[float, list[str]]] = {}
_SKILL_CACHE_TTL = 60.0  # seconds


async def _get_core_skill_ids() -> list[str]:
    """Return IDs of all core skills (source_type='file', not integration-prefixed)."""
    import time
    global _core_skill_cache
    now = time.monotonic()
    if _core_skill_cache and (now - _core_skill_cache[0]) < _SKILL_CACHE_TTL:
        return _core_skill_cache[1]

    from sqlalchemy import select as _sa_select
    from app.db.engine import async_session as _cs_session
    from app.db.models import Skill as _SkillRow

    async with _cs_session() as _cs_db:
        rows = (await _cs_db.execute(
            _sa_select(_SkillRow.id).where(
                _SkillRow.source_type == "file",
                ~_SkillRow.id.like("integrations/%"),
                ~_SkillRow.id.like("bots/%"),
            )
        )).scalars().all()

    result = list(rows)
    _core_skill_cache = (now, result)
    return result


async def _get_integration_skill_ids(integration_type: str) -> list[str]:
    """Return IDs of skills for a specific integration."""
    import time
    now = time.monotonic()
    cached = _integration_skill_cache.get(integration_type)
    if cached and (now - cached[0]) < _SKILL_CACHE_TTL:
        return cached[1]

    from sqlalchemy import select as _sa_select
    from app.db.engine import async_session as _is_session
    from app.db.models import Skill as _SkillRow

    prefix = f"integrations/{integration_type}/"
    async with _is_session() as _is_db:
        rows = (await _is_db.execute(
            _sa_select(_SkillRow.id).where(
                _SkillRow.id.like(f"{prefix}%"),
                _SkillRow.source_type == "integration",
            )
        )).scalars().all()

    result = list(rows)
    _integration_skill_cache[integration_type] = (now, result)
    return result


def invalidate_skill_auto_enroll_cache() -> None:
    """Clear all skill enrollment caches after file sync.

    Phase 3 working set: clears the legacy core/integration helper caches AND
    the per-bot enrollment cache so a fresh skill catalog rebuild is picked up
    on the next turn.
    """
    global _core_skill_cache
    _core_skill_cache = None
    _integration_skill_cache.clear()
    try:
        from app.services.skill_enrollment import invalidate_enrolled_cache
        invalidate_enrolled_cache()
    except Exception:
        logger.debug("Failed to invalidate enrollment cache", exc_info=True)


async def _load_skill_enrollments(
    *,
    bot: BotConfig,
    state: Any,
) -> AsyncGenerator[dict[str, Any], None]:
    """Phase 3 skill-enrollment loader. Discovers bot-authored skills,
    persists any new ones as source='authored', loads the bot's full enrolled
    working set, and merges the skill ids into `bot`. Sets three keys on
    `out_state`:

      * `bot`          — the replaced BotConfig (always set)
      * `enrolled_ids` — list[str] of skill ids (empty when bot.id is falsy)
      * `source_map`   — dict[str, str] of skill_id -> enrollment source

    Indirects bot-authored discovery through `app.agent.context_assembly` so
    tests patching `app.agent.context_assembly._get_bot_authored_skill_ids`
    continue to intercept the call after the move into `tool_surface/`.
    """
    out_state = state
    out_state["bot"] = bot
    out_state["enrolled_ids"] = []
    out_state["source_map"] = {}

    if not bot.id:
        return

    from app.agent import context_assembly as _ca
    from app.services.skill_enrollment import (
        enroll_many as _enroll_many,
        get_enrolled_skill_ids as _get_enrolled_skill_ids,
        get_enrolled_source_map as _get_enrolled_source_map,
    )

    # Discover bot-authored skills, persist any new ones as 'authored'
    try:
        _bot_skill_ids = await _ca._get_bot_authored_skill_ids(bot.id)
        if _bot_skill_ids:
            _new = await _enroll_many(bot.id, _bot_skill_ids, source="authored")
            if _new:
                yield {"type": "bot_authored_skills_enrolled", "count": _new}
    except Exception:
        logger.warning("Failed to auto-discover bot-authored skills for %s", bot.id, exc_info=True)

    # Load the bot's full enrolled working set in one query
    try:
        _enrolled_ids = await _get_enrolled_skill_ids(bot.id)
        _source_map = await _get_enrolled_source_map(bot.id)
        out_state["enrolled_ids"] = _enrolled_ids
        out_state["source_map"] = _source_map
        if _enrolled_ids:
            _prev = len(bot.skills)
            bot = _ca._merge_skills(bot, _enrolled_ids)
            out_state["bot"] = bot
            if len(bot.skills) > _prev:
                yield {"type": "enrolled_skills", "count": len(bot.skills) - _prev}
    except Exception:
        logger.warning("Failed to load enrolled skills for %s", bot.id, exc_info=True)


async def _apply_ephemeral_skills(
    *,
    messages: list[dict],
    bot: BotConfig,
    state: Any,
) -> None:
    """Append webhook/execution-config skills that weren't @-tagged or
    already in bot.skills. Writes `untagged_ephemeral` to ``out_state`` for
    Stage 9 to consume."""
    from app.agent.context import current_ephemeral_skills
    tagged_skill_names = state.tagged_skill_names
    _ephemeral_skill_ids = list(current_ephemeral_skills.get() or [])
    _bot_skill_ids = {s.id for s in bot.skills}
    _untagged_ephemeral = [
        s for s in _ephemeral_skill_ids
        if s not in tagged_skill_names and s not in _bot_skill_ids
    ]
    state.untagged_ephemeral = _untagged_ephemeral
    if _untagged_ephemeral:
        _eph_chunks: list[str] = []
        for _eph_id in _untagged_ephemeral:
            _eph_chunks.extend(await fetch_skill_chunks_by_id(_eph_id))
        if _eph_chunks:
            messages.append({
                "role": "system",
                "content": "Webhook skill context:\n\n"
                           + "\n\n---\n\n".join(_eph_chunks),
            })
