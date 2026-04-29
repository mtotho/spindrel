"""Context injection pipeline — assembles RAG context before the agent tool loop."""

import asyncio
import json
import logging
import math
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dataclasses import replace as _dc_replace

from app.agent.bots import BotConfig
from app.agent.channel_overrides import EffectiveTools, apply_auto_injections, resolve_effective_tools
from app.agent.context import (
    current_run_origin,
    current_skills_in_context,
    set_ephemeral_delegates,
    set_ephemeral_skills,
)
from app.agent.context_profiles import ContextProfile, get_context_profile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.context_budget import ContextBudget

from app.agent.message_utils import (
    _AUDIO_TRANSCRIPT_INSTRUCTION,
    _all_tool_schemas_by_name,
    _build_audio_user_message,
    _build_user_message_content,
    _merge_tool_schemas,
)
from app.agent.rag import fetch_skill_chunks_by_id
from app.agent.rag_formatting import (
    BOT_KNOWLEDGE_BASE_RAG_PREFIX,
    CHANNEL_INDEX_SEGMENTS_RAG_PREFIX,
    CHANNEL_KNOWLEDGE_BASE_RAG_PREFIX,
    CHUNK_SEPARATOR,
    CONVERSATION_SECTIONS_RAG_PREFIX,
    LEGACY_INDEXED_DIRECTORIES_RAG_PREFIX,
    WORKSPACE_RAG_PREFIX,
)
from app.agent.recording import _record_trace_event
from app.agent.tags import resolve_tags
from app.agent.tokenization import estimate_content_tokens
from app.agent.prompt_sizing import message_prompt_tokens
from app.agent.tools import retrieve_tools
from app.config import settings
from app.tools.client_tools import get_client_tool_schemas
from app.tools.mcp import get_mcp_server_for_tool
from app.tools.registry import get_local_tool_schemas

logger = logging.getLogger(__name__)

# Enrollment sources eligible for auto-inject. Starter/migration skills are
# generic utility docs that shouldn't compete for the injection slot.
_INJECT_ELIGIBLE_SOURCES = frozenset({"authored", "fetched", "manual"})


def _safe_sim(value: float) -> float | None:
    """Sanitize similarity score for JSONB serialization (NaN is invalid JSON)."""
    if math.isnan(value):
        return None
    return round(value, 4)


def _build_context_profile_note(
    *,
    context_profile: ContextProfile,
    inject_decisions: dict[str, str],
) -> str | None:
    """Return a small runtime note for restricted profiles.

    Chat already carries the full generic memory/context instructions in the
    shared memory prompt. Restricted profiles get an extra per-request note so
    the model knows what is missing on this run without duplicating the whole
    prompt family.
    """
    if context_profile.name == "chat":
        return None

    lines = [f"Current context profile: {context_profile.name}."]

    if context_profile.live_history_turns == 0:
        lines.append("Live replay is disabled for this run.")
    elif context_profile.live_history_turns is not None:
        lines.append(
            f"Live replay is limited to the last {context_profile.live_history_turns} user-started turn(s)."
        )

    if not context_profile.allow_memory_recent_logs:
        lines.append("Recent daily logs and memory reference listings are not preloaded in this run.")

    workspace_keys = (
        "channel_workspace",
        "channel_index_segments",
        "workspace_rag",
        "bot_knowledge_base",
    )
    workspace_decisions = [inject_decisions.get(key) for key in workspace_keys]
    workspace_admitted = any(decision == "admitted" for decision in workspace_decisions)
    workspace_budget_skipped = any(decision == "skipped_by_budget" for decision in workspace_decisions)

    if not (
        context_profile.allow_channel_workspace
        or context_profile.allow_channel_index_segments
        or context_profile.allow_bot_knowledge_base
        or context_profile.allow_workspace_rag
    ):
        lines.append("Workspace files, knowledge excerpts, and workspace search context are not preloaded in this profile.")
    elif workspace_admitted:
        lines.append("Some workspace and knowledge context is already present in this run.")
    elif workspace_budget_skipped:
        lines.append("Workspace and knowledge context was eligible but skipped on budget for this run.")
    else:
        lines.append("Workspace and knowledge context was not preloaded for this run.")

    lines.append("If exact detail matters, fetch or search it explicitly instead of assuming it is already in context.")
    return "\n".join(lines)


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


def _render_channel_workspace_prompt(
    *,
    workspace_path: str,
    channel_id: str,
    data_listing: str,
    style: str = "markdown",
) -> str:
    """Render the channel workspace helper prompt from the configured template.

    Uses CHANNEL_WORKSPACE_PROMPT if set, otherwise DEFAULT_CHANNEL_WORKSPACE_PROMPT.
    Template placeholders: {workspace_path}, {channel_id}, {data_listing}.
    Prompt-dialect section markers ({% section %}) are resolved first, then
    Python .format_map fills the value placeholders. Falls back to
    DEFAULT_CHANNEL_WORKSPACE_PROMPT if the configured template breaks.
    """
    from app.config import DEFAULT_CHANNEL_WORKSPACE_PROMPT
    from app.services.prompt_dialect import render as _dialect_render

    template = settings.CHANNEL_WORKSPACE_PROMPT.strip() or DEFAULT_CHANNEL_WORKSPACE_PROMPT
    replacements = {
        "workspace_path": workspace_path,
        "channel_id": channel_id,
        "data_listing": data_listing,
    }
    try:
        return _dialect_render(template, style).format_map(replacements)
    except (KeyError, ValueError) as exc:
        logger.warning(
            "Failed to render CHANNEL_WORKSPACE_PROMPT (%s), using fallback", exc,
        )
        return _dialect_render(DEFAULT_CHANNEL_WORKSPACE_PROMPT, style).format_map(replacements)


async def _build_tagged_skill_hint_lines(skill_ids: list[str]) -> list[str]:
    """Build one hint line per tagged skill — ``- <id> — <name>: <description>``.

    Looks up SkillRow by id (no chunk fetch, no ephemeral embedding). Unknown
    ids are skipped silently. Descriptions truncate to 160 chars.
    """
    if not skill_ids:
        return []
    from sqlalchemy import select
    from app.db.engine import async_session
    from app.db.models import Skill as SkillRow

    async with async_session() as db:
        rows = (await db.execute(
            select(SkillRow.id, SkillRow.name, SkillRow.description)
            .where(SkillRow.id.in_(skill_ids))
            .where(SkillRow.archived_at.is_(None))
        )).all()
    by_id = {r.id: r for r in rows}
    lines: list[str] = []
    for sid in skill_ids:
        row = by_id.get(sid)
        if row is None:
            continue
        desc = (row.description or "").strip()
        if len(desc) > 160:
            desc = desc[:157] + "..."
        head = f"- `{sid}` — {row.name}" if row.name else f"- `{sid}`"
        lines.append(f"{head}: {desc}" if desc else head)
    return lines


def _compact_tool_usage(name: str, fn: dict[str, Any]) -> str:
    """Compact usage hint with types + enums so the bot can skip get_tool_info.

    Shape: ``tool_name(required: type, [optional: type=default]) — description``.
    Small enums inline as ``mode: a|b|c``; longer enums fall back to the raw
    type. Kept to one line per tool so a ~20-tool index stays under ~5 KB.
    """
    params = fn.get("parameters", {}) or {}
    props = params.get("properties", {}) or {}
    required = set(params.get("required", []) or [])
    parts: list[str] = []
    for p, spec in props.items():
        if not isinstance(spec, dict):
            parts.append(p if p in required else f"[{p}]")
            continue
        t = spec.get("type")
        enum = spec.get("enum")
        if isinstance(enum, list) and 1 <= len(enum) <= 5:
            type_hint = "|".join(str(v) for v in enum)
        elif isinstance(t, list):
            type_hint = "|".join(str(x) for x in t)
        elif isinstance(t, str):
            type_hint = t
        else:
            type_hint = ""
        label = f"{p}: {type_hint}" if type_hint else p
        parts.append(label if p in required else f"[{label}]")
    sig = f"{name}({', '.join(parts)})" if parts else f"{name}()"
    desc = fn.get("description", "")
    # First sentence only, capped at 80 chars
    dot = desc.find(". ")
    if dot > 0:
        desc = desc[:dot]
    if len(desc) > 80:
        desc = desc[:77] + "..."
    return f"{sig} — {desc}" if desc else sig


def _merge_skills(
    bot: BotConfig,
    new_skill_ids: list[str],
    mode: str = "on_demand",
) -> BotConfig:
    """Merge new skills into bot config, deduplicating.

    Updates the current_resolved_skill_ids context var as a side effect.
    Returns a new BotConfig with merged skills.
    """
    from app.agent.bots import SkillConfig
    from app.agent.context import current_resolved_skill_ids

    existing = {s.id for s in bot.skills}
    new_skills = [
        SkillConfig(id=sid, mode=mode)
        for sid in new_skill_ids
        if sid not in existing
    ]
    if not new_skills:
        return bot
    bot = _dc_replace(bot, skills=list(bot.skills) + new_skills)
    current_resolved_skill_ids.set({s.id for s in bot.skills})
    return bot


@dataclass
class AssemblyResult:
    """Side-channel outputs from context assembly needed by the caller."""
    pre_selected_tools: list[dict[str, Any]] | None = None
    authorized_tool_names: set[str] | None = None
    user_msg_index: int = 0
    tagged_tool_names: list[str] = field(default_factory=list)
    tagged_bot_names: list[str] = field(default_factory=list)
    channel_model_override: str | None = None
    channel_provider_id_override: str | None = None
    channel_max_iterations: int | None = None
    channel_fallback_models: list[dict] = field(default_factory=list)
    channel_model_tier_overrides: dict | None = None
    budget_utilization: float | None = None
    effective_local_tools: list[str] | None = None
    auto_inject_skills: list[dict[str, Any]] = field(default_factory=list)
    active_skills: list[dict[str, Any]] = field(default_factory=list)
    skills_in_context: list[dict[str, Any]] = field(default_factory=list)
    # Per-category injection chars — populated by assemble_context for callers
    # that want the breakdown without scraping trace events (e.g. dev-panel
    # next-turn forecast). Mirrors the dict written into the
    # `context_injection_summary` trace event.
    inject_chars: dict[str, int] = field(default_factory=dict)
    inject_decisions: dict[str, str] = field(default_factory=dict)
    context_profile: str | None = None
    context_origin: str | None = None
    context_policy: dict[str, Any] = field(default_factory=dict)
    tool_discovery_info: dict[str, Any] = field(default_factory=dict)


@dataclass
class AssemblyLedger:
    """Budget + injection accounting shared by context assembly stages."""
    budget: "ContextBudget | None" = None
    inject_chars: dict[str, int] = field(default_factory=dict)
    inject_decisions: dict[str, str] = field(default_factory=dict)

    def can_afford(self, content: Any) -> bool:
        if self.budget is None:
            return True
        return self.budget.can_afford(estimate_content_tokens(content))

    def consume(self, category: str, content: Any) -> None:
        if self.budget is not None:
            self.budget.consume(category, estimate_content_tokens(content))

    def consume_tokens(self, category: str, tokens: int) -> None:
        if self.budget is not None and tokens:
            self.budget.consume(category, tokens)

    def mark(self, key: str, decision: str) -> None:
        self.inject_decisions[key] = decision

    def record_chars(self, key: str, chars: int) -> None:
        self.inject_chars[key] = chars


@dataclass
class AssemblyStageState:
    """Typed cross-stage outputs for the context assembly pipeline."""
    bot: BotConfig | None = None
    enrolled_ids: list[str] = field(default_factory=list)
    source_map: dict[str, str] = field(default_factory=dict)
    tagged: list[Any] = field(default_factory=list)
    tagged_skill_names: list[str] = field(default_factory=list)
    tagged_tool_names: list[str] = field(default_factory=list)
    tagged_bot_names: list[str] = field(default_factory=list)
    untagged_ephemeral: list[str] = field(default_factory=list)
    member_bot_ids: list[str] = field(default_factory=list)
    member_configs: dict[str, dict] = field(default_factory=dict)
    enrolled_rows: list[Any] = field(default_factory=list)
    suggestion_rows: list[Any] = field(default_factory=list)
    ranked_relevant: list[str] = field(default_factory=list)
    auto_injected: list[str] = field(default_factory=list)
    auto_injected_similarities: dict[str, float] = field(default_factory=dict)
    history_fetched_skills: set[str] = field(default_factory=set)
    history_skill_records: dict[str, dict[str, Any]] = field(default_factory=dict)
    pre_selected_tools: list[dict[str, Any]] | None = None
    authorized_names: set[str] | None = None
    tool_discovery_info: dict[str, Any] = field(default_factory=lambda: {"tool_retrieval_enabled": False})

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


def _mark_injection_decision(
    inject_decisions: dict[str, str],
    key: str,
    decision: str,
) -> None:
    inject_decisions[key] = decision


# ===== Cluster 7a setup-stage extractions =====
#
# Five helpers extracted from the top of `assemble_context` (Stages 1-4 + 10).
# They form the "discovery + setup" phase that runs before RAG injection:
# channel-overrides load, context pruning, effective-tool/budget accounting,
# skill enrollment loading, and API-access tool injection. Each helper stays
# at module level in this file so test patches on
# `app.agent.context_assembly.*` continue to intercept.


async def _load_channel_overrides(
    *,
    channel_id: Any,
) -> Any:
    """Load the Channel row + its skill enrollment ids. Returns None if
    channel_id is None, no channel is found, or the load fails. The returned
    row carries a `_channel_skill_enrollment_ids` attribute holding the
    per-channel skill enrollment skill_ids.
    """
    if channel_id is None:
        return None
    try:
        from sqlalchemy import select as _sa_select
        from sqlalchemy.orm import selectinload as _selectinload
        from app.db.engine import async_session
        from app.db.models import Channel, ChannelSkillEnrollment
        async with async_session() as _ch_db:
            _ch_result = await _ch_db.execute(
                _sa_select(Channel)
                .where(Channel.id == channel_id)
                .options(_selectinload(Channel.integrations))
            )
            _ch_row = _ch_result.scalar_one_or_none()
            if _ch_row is not None:
                _skill_rows = (await _ch_db.execute(
                    _sa_select(ChannelSkillEnrollment.skill_id).where(
                        ChannelSkillEnrollment.channel_id == channel_id
                    )
                )).scalars().all()
                setattr(_ch_row, "_channel_skill_enrollment_ids", list(_skill_rows))
            return _ch_row
    except Exception:
        logger.warning(
            "Failed to load channel %s for context assembly, continuing without overrides",
            channel_id,
            exc_info=True,
        )
        return None


async def _run_context_pruning(
    *,
    messages: list[dict],
    bot: BotConfig,
    ch_row: Any,
    ledger: AssemblyLedger,
    correlation_id: Any,
    session_id: Any,
    client_id: str | None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Trim stale tool results from message history. Mutates `messages` and
    `inject_chars` in place; yields a single `context_pruning` event and
    fires a trace task when at least one result was pruned. Returns early
    without mutating anything when pruning is disabled by bot/channel/global
    settings cascade.
    """
    _pruning_enabled = settings.CONTEXT_PRUNING_ENABLED
    _pruning_min_len = settings.CONTEXT_PRUNING_MIN_LENGTH
    # Bot-level override
    if bot.context_pruning is not None:
        _pruning_enabled = bot.context_pruning
    # Channel-level override (highest priority)
    if ch_row is not None:
        if getattr(ch_row, "context_pruning", None) is not None:
            _pruning_enabled = ch_row.context_pruning

    if not _pruning_enabled:
        return

    from app.agent.context_pruning import prune_tool_results
    _prune_stats = prune_tool_results(messages, min_content_length=_pruning_min_len)
    if _prune_stats["pruned_count"] > 0 or _prune_stats.get("tool_call_args_pruned", 0) > 0:
        ledger.record_chars("context_pruning_saved", -_prune_stats["chars_saved"])
        yield {
            "type": "context_pruning",
            "scope": "turn_boundary",
            "pruned_count": _prune_stats["pruned_count"],
            "chars_saved": _prune_stats["chars_saved"],
            "turns_pruned": _prune_stats["turns_pruned"],
            "tool_call_args_pruned": _prune_stats.get("tool_call_args_pruned", 0),
            "tool_call_arg_chars_saved": _prune_stats.get("tool_call_arg_chars_saved", 0),
        }
        if correlation_id is not None:
            asyncio.create_task(_record_trace_event(
                correlation_id=correlation_id,
                session_id=session_id,
                bot_id=bot.id,
                client_id=client_id,
                event_type="context_pruning",
                count=_prune_stats["pruned_count"],
                data={
                    "scope": "turn_boundary",
                    "chars_saved": _prune_stats["chars_saved"],
                    "turns_pruned": _prune_stats["turns_pruned"],
                    "tool_call_args_pruned": _prune_stats.get("tool_call_args_pruned", 0),
                    "tool_call_arg_chars_saved": _prune_stats.get("tool_call_arg_chars_saved", 0),
                    "min_length": _pruning_min_len,
                },
            ))


def _apply_effective_tools_and_budget(
    *,
    messages: list[dict],
    bot: BotConfig,
    ch_row: Any,
    ledger: AssemblyLedger,
    result: "AssemblyResult",
) -> BotConfig:
    """Consume base + history tokens against the budget, resolve the channel-
    layered effective tool set via `resolve_effective_tools` +
    `apply_auto_injections`, copy channel-side model/iteration/fallback
    overrides into `result`, and return the replaced BotConfig. Sync — no
    awaits in the underlying pipeline stage.
    """
    if ledger.budget is not None:
        _base_tokens = 0
        _history_tokens = 0
        for m in messages:
            _tokens = message_prompt_tokens(m)
            if m.get("role") == "system":
                _base_tokens += _tokens
            else:
                _history_tokens += _tokens
        ledger.consume_tokens("base_context", _base_tokens)
        ledger.consume_tokens("conversation_history", _history_tokens)

    if ch_row is not None:
        _eff = resolve_effective_tools(bot, ch_row)
        _eff = apply_auto_injections(_eff, bot)
        bot = _dc_replace(
            bot,
            local_tools=_eff.local_tools,
            mcp_servers=_eff.mcp_servers,
            client_tools=_eff.client_tools,
            pinned_tools=_eff.pinned_tools,
            skills=_eff.skills,
        )
        if ch_row.model_override:
            result.channel_model_override = ch_row.model_override
            result.channel_provider_id_override = ch_row.model_provider_id_override
        if ch_row.max_iterations is not None:
            result.channel_max_iterations = ch_row.max_iterations
        if ch_row.fallback_models:
            result.channel_fallback_models = ch_row.fallback_models
        if ch_row.model_tier_overrides:
            result.channel_model_tier_overrides = ch_row.model_tier_overrides
    else:
        # No channel — still apply auto-injections to bot defaults
        _eff = EffectiveTools(
            local_tools=list(bot.local_tools),
            mcp_servers=list(bot.mcp_servers),
            client_tools=list(bot.client_tools),
            pinned_tools=list(bot.pinned_tools),
            skills=list(bot.skills),
        )
        _eff = apply_auto_injections(_eff, bot)
        bot = _dc_replace(
            bot,
            local_tools=_eff.local_tools,
            pinned_tools=_eff.pinned_tools,
        )
    return bot


async def _load_skill_enrollments(
    *,
    bot: BotConfig,
    state: AssemblyStageState,
) -> AsyncGenerator[dict[str, Any], None]:
    """Phase 3 skill-enrollment loader. Discovers bot-authored skills,
    persists any new ones as source='authored', loads the bot's full enrolled
    working set, and merges the skill ids into `bot`. Sets three keys on
    `out_state`:

      * `bot`          — the replaced BotConfig (always set)
      * `enrolled_ids` — list[str] of skill ids (empty when bot.id is falsy)
      * `source_map`   — dict[str, str] of skill_id -> enrollment source

    Uses the module-level `_get_bot_authored_skill_ids` so tests that patch
    `app.agent.context_assembly._get_bot_authored_skill_ids` continue to
    intercept the call.
    """
    out_state = state
    out_state["bot"] = bot
    out_state["enrolled_ids"] = []
    out_state["source_map"] = {}

    if not bot.id:
        return

    from app.services.skill_enrollment import (
        enroll_many as _enroll_many,
        get_enrolled_skill_ids as _get_enrolled_skill_ids,
        get_enrolled_source_map as _get_enrolled_source_map,
    )

    # Discover bot-authored skills, persist any new ones as 'authored'
    try:
        _bot_skill_ids = await _get_bot_authored_skill_ids(bot.id)
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
            bot = _merge_skills(bot, _enrolled_ids)
            out_state["bot"] = bot
            if len(bot.skills) > _prev:
                yield {"type": "enrolled_skills", "count": len(bot.skills) - _prev}
    except Exception:
        logger.warning("Failed to load enrolled skills for %s", bot.id, exc_info=True)


def _inject_api_access_tools(
    *,
    messages: list[dict],
    bot: BotConfig,
) -> tuple[BotConfig, dict[str, Any] | None]:
    """If the bot has scoped API permissions, inject the two API-access tools
    (`list_api_endpoints`, `call_api`) into both `local_tools` and
    `pinned_tools`, append a system message describing the available scopes,
    and return the replaced bot plus a progress event. Otherwise return the
    bot unchanged and `None` for the event.
    """
    if not bot.api_permissions:
        return bot, None
    _api_tools = ["list_api_endpoints", "call_api"]
    _new_local = list(bot.local_tools or [])
    _new_pinned = list(dict.fromkeys(bot.pinned_tools or []))
    for _t in _api_tools:
        if _t not in _new_local:
            _new_local.append(_t)
        if _t not in _new_pinned:
            _new_pinned.append(_t)
    bot = _dc_replace(bot, local_tools=_new_local, pinned_tools=_new_pinned)
    messages.append({
        "role": "system",
        "content": (
            f"You have API access to the agent server (scopes: {', '.join(bot.api_permissions)}). "
            "Use list_api_endpoints() to see available endpoints and call_api(method, path, body) to execute them."
        ),
    })
    return bot, {"type": "api_access_tools", "scopes": bot.api_permissions}


# ===== Cluster 7b discovery-stage extractions =====
#
# Four helpers extracted from the "discovery" phase of `assemble_context`
# (Stages 7, 8, 11, 12). They share the `_tagged_*` / `_member_*` locals
# that get read by Stages 9 (skills), 12 (delegate index), and 18 (tool
# retrieval), so each helper writes its outputs to a caller-supplied
# `out_state` dict. Stays in-file for the same test-patch reason as 7a.


async def _resolve_tagged_mentions(
    *,
    messages: list[dict],
    bot: BotConfig,
    user_message: Any,
    client_id: Any,
    session_id: Any,
    correlation_id: Any,
    result: Any,
    state: AssemblyStageState,
) -> AsyncGenerator[dict[str, Any], None]:
    """Resolve @mentions in the user message into skill/tool/bot tag objects.
    Writes `tagged`, `tagged_skill_names`, `tagged_tool_names`,
    `tagged_bot_names` to ``out_state``. Mutates ``result`` and the
    `ephemeral_delegates` / `ephemeral_skills` context vars (side effects
    preserved from the original inline code)."""
    _tagged = await resolve_tags(
        message=user_message,
        bot_skills=bot.skill_ids,
        bot_local_tools=bot.local_tools,
        bot_client_tools=bot.client_tools,
        bot_id=bot.id,
        client_id=client_id,
        session_id=session_id,
    )
    _tagged_skill_names = [t.name for t in _tagged if t.tag_type == "skill"]
    _tagged_tool_names = [t.name for t in _tagged if t.tag_type == "tool"]
    _tagged_bot_names = [t.name for t in _tagged if t.tag_type == "bot"]

    out_state = state
    out_state["tagged"] = _tagged
    out_state["tagged_skill_names"] = _tagged_skill_names
    out_state["tagged_tool_names"] = _tagged_tool_names
    out_state["tagged_bot_names"] = _tagged_bot_names

    result.tagged_tool_names = _tagged_tool_names
    result.tagged_bot_names = _tagged_bot_names
    if _tagged_bot_names:
        set_ephemeral_delegates(_tagged_bot_names)
    if _tagged_skill_names:
        from app.agent.context import current_ephemeral_skills
        _existing_skills = list(current_ephemeral_skills.get() or [])
        _merged = list(dict.fromkeys(_existing_skills + _tagged_skill_names))
        set_ephemeral_skills(_merged)

    if _tagged:
        if _tagged_skill_names:
            _hint_lines = await _build_tagged_skill_hint_lines(_tagged_skill_names)
            if _hint_lines:
                messages.append({
                    "role": "system",
                    "content": (
                        "Tagged skill context (explicitly requested): the user "
                        "tagged these skills. Call "
                        'get_skill(skill_id="...") to load any you need — '
                        "otherwise ignore.\n\n" + "\n".join(_hint_lines)
                    ),
                })

        yield {
            "type": "tagged_context",
            "tags": [t.raw for t in _tagged],
            "skills": _tagged_skill_names,
            "tools": _tagged_tool_names,
            "bots": _tagged_bot_names,
        }
        if correlation_id is not None:
            asyncio.create_task(_record_trace_event(
                correlation_id=correlation_id,
                session_id=session_id,
                bot_id=bot.id,
                client_id=client_id,
                event_type="tagged_context",
                count=len(_tagged),
                data={
                    "tags": [t.raw for t in _tagged],
                    "skills": _tagged_skill_names,
                    "tools": _tagged_tool_names,
                    "bots": _tagged_bot_names,
                },
            ))


async def _apply_ephemeral_skills(
    *,
    messages: list[dict],
    bot: BotConfig,
    state: AssemblyStageState,
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


async def _inject_multi_bot_awareness(
    *,
    messages: list[dict],
    bot: BotConfig,
    channel_id: Any,
    ch_row: Any,
    system_preamble: Any,
    state: AssemblyStageState,
) -> AsyncGenerator[dict[str, Any], None]:
    """Load channel bot members + emit a system message listing participants
    (primary/member labels, self marker, config suffixes). Writes
    `member_bot_ids` / `member_configs` to ``out_state`` for Stage 12."""
    _member_bot_ids: list[str] = []
    _member_configs: dict[str, dict] = {}
    if channel_id:
        try:
            from sqlalchemy import select as _sel
            from app.db.engine import async_session as _async_session
            from app.db.models import ChannelBotMember as _CBM
            async with _async_session() as _mbdb:
                _mb_rows = (await _mbdb.execute(
                    _sel(_CBM).where(_CBM.channel_id == channel_id)
                )).all()
                for (_row,) in _mb_rows:
                    _member_bot_ids.append(_row.bot_id)
                    _member_configs[_row.bot_id] = _row.config or {}
        except Exception:
            logger.debug("Failed to load channel bot members for %s", channel_id, exc_info=True)

    state.member_bot_ids = _member_bot_ids
    state.member_configs = _member_configs

    if _member_bot_ids:
        from app.agent.bots import get_bot as _get_bot_mb
        _participant_lines: list[str] = []

        _primary_bot_id = getattr(ch_row, "bot_id", None) if ch_row else None
        _primary_bot_id = _primary_bot_id or bot.id

        _all_bot_ids = [_primary_bot_id] + [mid for mid in _member_bot_ids if mid != _primary_bot_id]
        if bot.id != _primary_bot_id and bot.id not in _all_bot_ids:
            _all_bot_ids.append(bot.id)

        for _bid in _all_bot_ids:
            _is_primary = _bid == _primary_bot_id
            _is_self = _bid == bot.id
            _role_label = "primary" if _is_primary else "member"
            _you_marker = " ← you" if _is_self else ""
            try:
                _mb = _get_bot_mb(_bid)
                _cfg = _member_configs.get(_bid, {})
                _cfg_parts: list[str] = []
                if _cfg.get("auto_respond"):
                    _cfg_parts.append("auto-respond")
                if _cfg.get("response_style"):
                    _cfg_parts.append(f"style={_cfg['response_style']}")
                _cfg_suffix = f" [{', '.join(_cfg_parts)}]" if _cfg_parts else ""
                _participant_lines.append(f"  - @{_bid} ({_role_label}): {_mb.name}{_cfg_suffix}{_you_marker}")
            except Exception:
                _participant_lines.append(f"  - @{_bid} ({_role_label}){_you_marker}")

        _awareness_msg = (
            f"You are {bot.name} (bot_id: {bot.id}).\n\n"
            "This channel has multiple bot participants:\n"
            + "\n".join(_participant_lines)
        )
        if not system_preamble:
            _awareness_msg += (
                "\nYou can @-mention bots by bot_id or display name (e.g., @dev_bot or @Dev Bot) to bring them into the conversation."
                "\nDo not @-mention yourself."
            )
        else:
            _awareness_msg += (
                "\nYou were brought into this conversation to help. Focus on responding — "
                "do not invoke or @-mention other bots."
            )
        messages.append({"role": "system", "content": _awareness_msg})

        yield {"type": "multi_bot_awareness", "member_count": len(_member_bot_ids)}


async def _inject_spatial_awareness(
    *,
    messages: list[dict],
    bot: BotConfig,
    channel_id: Any,
    ledger: AssemblyLedger,
) -> AsyncGenerator[dict[str, Any], None]:
    if not channel_id:
        return
    try:
        from app.db.engine import async_session
        from app.services.workspace_spatial import build_canvas_neighborhood_block
        async with async_session() as db:
            block = await build_canvas_neighborhood_block(
                db,
                channel_id=channel_id,
                bot_id=bot.id,
            )
    except Exception:
        logger.debug("Failed to build spatial awareness block for %s/%s", bot.id, channel_id, exc_info=True)
        return
    if not block:
        return
    if ledger.can_afford(block):
        messages.append({"role": "system", "content": block})
        ledger.consume("spatial_canvas", block)
        ledger.record_chars("spatial_canvas", len(block))
        ledger.mark("spatial_canvas", "admitted")
        yield {"type": "spatial_canvas", "chars": len(block)}
    else:
        ledger.mark("spatial_canvas", "skipped_by_budget")


def _inject_delegate_index(
    *,
    messages: list[dict],
    bot: BotConfig,
    tagged_bot_names: list[str],
    member_bot_ids: list[str],
) -> dict[str, Any] | None:
    """Append the delegate index system message (bot.delegate_bots + tagged
    bots + member bots, deduped). Returns the `delegate_index` event dict or
    None if no delegates to list."""
    _all_delegate_ids = list(dict.fromkeys(bot.delegate_bots + tagged_bot_names + member_bot_ids))
    _delegate_lines: list[str] = []
    if _all_delegate_ids:
        from app.agent.bots import get_bot as _get_bot
        for _did in _all_delegate_ids:
            try:
                _db = _get_bot(_did)
                _desc = (_db.system_prompt or "").strip().splitlines()[0][:120] if _db.system_prompt else ""
                _delegate_lines.append(f"  [bot] {_did} — {_db.name}" + (f": {_desc}" if _desc else ""))
            except Exception:
                _delegate_lines.append(f"  [bot] {_did}")

    if _delegate_lines:
        _delegate_content = (
            "Available delegates for delegate_to_agent:\n"
            + "\n".join(_delegate_lines)
        )
        messages.append({
            "role": "system",
            "content": _delegate_content,
        })
        return {"type": "delegate_index", "count": len(_delegate_lines)}
    return None


# ===== Cluster 7c skills-stage extraction =====
#
# Stage 9 (Phase-3 working set + semantic discovery + ranking + auto-inject)
# was 346 LOC inline — the largest single stage in `assemble_context`. Three
# internal closures (`_fmt_skill_line`, `_skill_category`,
# `_render_grouped_skill_lines`) travel with the helper as nested functions
# since they close over `_resident_skill_ids`. Stays in-file for the same
# test-patch reason as 7a/7b.


async def _inject_skill_working_set(
    *,
    messages: list[dict],
    bot: BotConfig,
    user_message: Any,
    correlation_id: Any,
    session_id: Any,
    client_id: Any,
    skip_skill_inject: bool,
    state: AssemblyStageState,
    ledger: AssemblyLedger,
    result: Any,
    context_profile: ContextProfile,
) -> AsyncGenerator[dict[str, Any], None]:
    """Phase-3 skill working-set + semantic discovery + auto-inject for the
    turn. Writes `enrolled_rows`, `suggestion_rows`, `enrolled_ids`,
    `ranked_relevant`, `auto_injected`, `auto_injected_similarities`,
    `history_fetched_skills`, `history_skill_records` to ``out_state`` for
    the downstream active-skills snapshot trace.

    Three layers, each gated independently:
      1. Working set — relevance-ranked list of enrolled skills. When ranking
         is enabled and there's a user_message, skills are sorted by semantic
         similarity and the top matches are marked as relevant.
      2. Auto-inject — highest-confidence enrolled skill has its content
         pre-loaded into context (eliminates get_skill round-trip).
      3. Discovery — semantic retrieval over UNENROLLED catalog skills.

    Each section runs in its own try/except so a failure in one doesn't kill
    the others or hang the event loop on teardown."""
    _enrolled_rows: list = []
    _suggestion_rows: list = []
    _enrolled_ids: list[str] = []
    _ranked_relevant: list[str] = []
    _auto_injected: list[str] = []
    _auto_injected_similarities: dict[str, float] = {}
    _history_fetched_skills: set[str] = set()
    _history_skill_records: dict[str, dict[str, Any]] = {}
    _skipped_in_history: list[str] = []
    _skipped_budget: list[str] = []
    _ranking: list[dict] = []
    tagged_skill_names = state.tagged_skill_names
    untagged_ephemeral = state.untagged_ephemeral
    source_map = state.source_map
    budget_can_afford = ledger.can_afford
    budget_consume = ledger.consume
    inject_decisions = ledger.inject_decisions
    out_state = state

    out_state["enrolled_rows"] = _enrolled_rows
    out_state["suggestion_rows"] = _suggestion_rows
    out_state["enrolled_ids"] = _enrolled_ids
    out_state["ranked_relevant"] = _ranked_relevant
    out_state["auto_injected"] = _auto_injected
    out_state["auto_injected_similarities"] = _auto_injected_similarities
    out_state["history_fetched_skills"] = _history_fetched_skills
    out_state["history_skill_records"] = _history_skill_records

    if not context_profile.allow_skill_index and not tagged_skill_names and not untagged_ephemeral:
        _enrolled_ids.extend([s.id for s in bot.skills])
        _mark_injection_decision(inject_decisions, "skill_index", "skipped_by_profile")
        return

    if not bot.id:
        return

    from app.agent.rag import (
        retrieve_skill_index as _retrieve_skill_index,
        rank_enrolled_skills as _rank_enrolled_skills,
        fetch_skill_chunks_by_id as _fetch_skill_chunks,
    )
    from sqlalchemy import select as _sa_select
    from app.db.engine import async_session as _async_session
    from app.db.models import Skill as _SkillRow

    _assistant_msgs_ago = 0
    for _hmsg in reversed(messages):
        if _hmsg.get("role") not in ("assistant", "bot"):
            continue
        for _htc in reversed(_hmsg.get("tool_calls") or []):
            _hfn = _htc.get("function") or {}
            if _hfn.get("name") != "get_skill":
                continue
            try:
                _hargs = json.loads(_hfn.get("arguments", "{}"))
            except (json.JSONDecodeError, TypeError):
                continue
            _skill_id = _hargs.get("skill_id")
            if not _skill_id or _skill_id in _history_skill_records:
                continue
            _tcid = str(_htc.get("id") or "")
            _history_skill_records[_skill_id] = {
                "skill_id": _skill_id,
                "source": "auto_injected" if _tcid.startswith("auto_inject_") else "loaded",
                "messages_ago": _assistant_msgs_ago,
            }
            _history_fetched_skills.add(_skill_id)
        _assistant_msgs_ago += 1

    _resident_skill_ids = set(_history_skill_records.keys())

    def _fmt_skill_line(r, *, relevant: bool = False, resident: bool = False) -> str:
        prefix = "↑" if relevant else "-"
        parts = [prefix]
        if resident:
            parts.append(" [loaded]")
        parts.append(f" {r.id}: {r.name}")
        if r.description:
            parts.append(f" — {r.description}")
        if r.triggers:
            parts.append(f" [{', '.join(r.triggers)}]")
        return "".join(parts)

    def _skill_category(r) -> str:
        cat = getattr(r, "category", None)
        if cat:
            return cat
        if "/" in r.id:
            return r.id.split("/", 1)[0]
        return "misc"

    def _render_grouped_skill_lines(rows_in_order: list, relevant_ids: set, resident_ids: set[str]) -> str:
        categories: dict[str, list[str]] = {}
        cat_order: list[str] = []
        for _r in rows_in_order:
            _c = _skill_category(_r)
            if _c not in categories:
                categories[_c] = []
                cat_order.append(_c)
            categories[_c].append(
                _fmt_skill_line(
                    _r,
                    relevant=_r.id in relevant_ids,
                    resident=_r.id in resident_ids,
                )
            )
        if len(rows_in_order) < 5 or len(cat_order) < 2:
            return "\n".join(
                _fmt_skill_line(
                    _r,
                    relevant=_r.id in relevant_ids,
                    resident=_r.id in resident_ids,
                )
                for _r in rows_in_order
            )
        if "core" in cat_order:
            cat_order.remove("core")
            cat_order.insert(0, "core")
        chunks: list[str] = []
        for _c in cat_order:
            chunks.append(f"[{_c}]")
            chunks.extend(categories[_c])
        return "\n".join(chunks)

    if bot.skills:
        _enrolled_ids = [s.id for s in bot.skills]
        out_state["enrolled_ids"] = _enrolled_ids
        try:
            async with _async_session() as _db:
                _enrolled_rows = (await _db.execute(
                    _sa_select(
                        _SkillRow.id, _SkillRow.name, _SkillRow.description,
                        _SkillRow.triggers, _SkillRow.category,
                    )
                    .where(_SkillRow.id.in_(_enrolled_ids))
                )).all()
        except Exception:
            logger.warning("Skill working-set load failed", exc_info=True)
            _enrolled_rows = []
        out_state["enrolled_rows"] = _enrolled_rows

        if _enrolled_rows:
            if settings.SKILL_ENROLLED_RANKING_ENABLED and user_message:
                _rank_parts: list[str] = []
                for _msg in reversed(messages[-10:]):
                    if _msg.get("role") in ("user", "assistant") and _msg.get("content"):
                        _rank_parts.append(_msg["content"][:500])
                        if len(_rank_parts) >= 3:
                            break
                _rank_query = "\n".join(reversed(_rank_parts)) if _rank_parts else user_message
                try:
                    _ranking = await _rank_enrolled_skills(
                        _rank_query, [r.id for r in _enrolled_rows],
                    )
                except Exception:
                    logger.warning("Enrolled skill ranking failed", exc_info=True)

            if _ranking:
                _rank_map = {r["skill_id"]: r for r in _ranking}
                _ranked_relevant = [r["skill_id"] for r in _ranking if r["relevant"]]
                out_state["ranked_relevant"] = _ranked_relevant
                _row_map = {r.id: r for r in _enrolled_rows}
                _sorted_ids = [r["skill_id"] for r in _ranking if r["skill_id"] in _row_map]
                for r in _enrolled_rows:
                    if r.id not in _rank_map:
                        _sorted_ids.append(r.id)

                _has_relevant = bool(_ranked_relevant)
                _ordered_rows = [_row_map[sid] for sid in _sorted_ids if sid in _row_map]
                _working_lines = _render_grouped_skill_lines(
                    _ordered_rows, set(_ranked_relevant), _resident_skill_ids,
                )
                _header = (
                    "BEFORE answering, scan your enrolled skills below. If any plausibly applies, "
                    "call get_skill(skill_id=\"<id>\") FIRST — these lines are an index, NOT content. "
                    "Answering from the description alone is the primary source of bad replies.\n"
                    "Do not call get_skill again for skills marked [loaded] unless you intentionally "
                    "need a fresh copy with get_skill(skill_id=\"<id>\", refresh=true).\n"
                    "Skills marked ↑ are semantically relevant to this message — load them before responding.\n"
                    if _has_relevant else
                    "BEFORE answering, scan your enrolled skills below. If any plausibly applies, "
                    "call get_skill(skill_id=\"<id>\") FIRST — these lines are an index, NOT content.\n"
                    "Do not call get_skill again for skills marked [loaded] unless you intentionally "
                    "need a fresh copy with get_skill(skill_id=\"<id>\", refresh=true).\n"
                )
            else:
                _working_lines = _render_grouped_skill_lines(
                    list(_enrolled_rows), set(), _resident_skill_ids,
                )
                _header = (
                    "BEFORE answering, scan your enrolled skills below. If any plausibly applies, "
                    "call get_skill(skill_id=\"<id>\") FIRST — these lines are an index, NOT content.\n"
                    "Do not call get_skill again for skills marked [loaded] unless you intentionally "
                    "need a fresh copy with get_skill(skill_id=\"<id>\", refresh=true).\n"
                )

            messages.append({
                "role": "system",
                "content": _header + _working_lines,
            })
            budget_consume("skill_index", _header + _working_lines)

            if _ranking and settings.SKILL_ENROLLED_AUTO_INJECT_MAX > 0 and not skip_skill_inject:
                _already_injected = (
                    set(tagged_skill_names) | set(untagged_ephemeral) | _history_fetched_skills
                )
                _injected_count = 0
                _inject_threshold = settings.SKILL_ENROLLED_AUTO_INJECT_THRESHOLD
                for _ri in _ranking:
                    if _injected_count >= settings.SKILL_ENROLLED_AUTO_INJECT_MAX:
                        break
                    if _ri["similarity"] < _inject_threshold:
                        break
                    if source_map.get(_ri["skill_id"], "starter") not in _INJECT_ELIGIBLE_SOURCES:
                        continue
                    if _ri["skill_id"] in _already_injected:
                        _skipped_in_history.append(_ri["skill_id"])
                        continue
                    try:
                        _ai_chunks = await _fetch_skill_chunks(_ri["skill_id"])
                        if _ai_chunks:
                            _ai_content = "\n\n---\n\n".join(_ai_chunks)
                            _ai_row = _row_map.get(_ri["skill_id"])
                            _ai_name = _ai_row.name if _ai_row else _ri["skill_id"]
                            _ai_formatted = f"# {_ai_name}\n\n{_ai_content}"
                            if not budget_can_afford(_ai_formatted):
                                _skipped_budget.append(_ri["skill_id"])
                                break
                            budget_consume("auto_inject_skill", _ai_formatted)
                            result.auto_inject_skills.append({
                                "skill_id": _ri["skill_id"],
                                "content": _ai_formatted,
                            })
                            _auto_injected.append(_ri["skill_id"])
                            _auto_injected_similarities[_ri["skill_id"]] = _safe_sim(_ri["similarity"])
                            _injected_count += 1
                            from app.tools.local.skills import _increment_auto_inject_count
                            asyncio.create_task(
                                _increment_auto_inject_count(_ri["skill_id"], bot.id)
                            )
                    except Exception:
                        logger.warning(
                            "Failed to auto-inject skill %s", _ri["skill_id"], exc_info=True,
                        )

                for _ai in _auto_injected:
                    _ai_row = _row_map.get(_ai)
                    _ai_sim = next((r["similarity"] for r in _ranking if r["skill_id"] == _ai), 0.0)
                    yield {
                        "type": "auto_inject",
                        "skill_id": _ai,
                        "skill_name": _ai_row.name if _ai_row else _ai,
                        "similarity": _safe_sim(_ai_sim),
                        "source": source_map.get(_ai, "unknown"),
                    }

    if user_message:
        try:
            async with _async_session() as _db:
                _catalog_q = _sa_select(_SkillRow.id).where(
                    ~_SkillRow.id.like("bots/%") | _SkillRow.id.like(f"bots/{bot.id}/%")
                )
                _catalog_ids = list((await _db.execute(_catalog_q)).scalars().all())

            _enrolled_set = set(_enrolled_ids)
            _candidate_ids = [sid for sid in _catalog_ids if sid not in _enrolled_set]

            if _candidate_ids:
                _suggestions = await _retrieve_skill_index(user_message, _candidate_ids)
                if _suggestions:
                    _suggestion_ids = [s["skill_id"] for s in _suggestions]
                    async with _async_session() as _db:
                        _suggestion_rows = (await _db.execute(
                            _sa_select(_SkillRow.id, _SkillRow.name, _SkillRow.description, _SkillRow.triggers)
                            .where(_SkillRow.id.in_(_suggestion_ids))
                        )).all()
        except Exception:
            logger.warning("Skill discovery layer failed", exc_info=True)
            _suggestion_rows = []
        out_state["suggestion_rows"] = _suggestion_rows

        if _suggestion_rows:
            _disc_lines = "\n".join(
                _fmt_skill_line(r) for r in _suggestion_rows
            )
            _disc_header = (
                "Skills you can fetch via get_skill(skill_id=\"<id>\") "
                "(your working set is empty — first successful fetch enrolls them):"
                if not _enrolled_rows else
                "Other skills you can fetch via get_skill(skill_id=\"<id>\") "
                "(not yet in your working set; first successful fetch enrolls them):"
            )
            messages.append({
                "role": "system",
                "content": _disc_header + "\n" + _disc_lines,
            })
            budget_consume("skill_index", _disc_header + "\n" + _disc_lines)

    if _enrolled_rows or _suggestion_rows:
        _skill_trace_data = {
            "enrolled_ids": [r.id for r in _enrolled_rows],
            "suggested_ids": [r.id for r in _suggestion_rows],
            "total_enrolled": len(_enrolled_ids),
            "ranked_relevant": _ranked_relevant,
            "auto_injected": _auto_injected,
            "ranking_scores": [
                {"skill_id": r["skill_id"], "similarity": _safe_sim(r["similarity"])}
                for r in _ranking
            ] if _ranking else [],
            "skills_in_history": sorted(_history_fetched_skills) if _history_fetched_skills else [],
            "skipped_in_history": _skipped_in_history if _skipped_in_history else [],
            "skipped_budget": _skipped_budget if _skipped_budget else [],
            "relevance_threshold": settings.SKILL_ENROLLED_RELEVANCE_THRESHOLD,
            "auto_inject_threshold": settings.SKILL_ENROLLED_AUTO_INJECT_THRESHOLD,
        }
        yield {
            "type": "skill_index",
            "count": len(_enrolled_rows),
            "suggestions": len(_suggestion_rows),
            "total": len(_enrolled_ids),
            **_skill_trace_data,
        }
        if correlation_id is not None:
            asyncio.create_task(_record_trace_event(
                correlation_id=correlation_id,
                session_id=session_id,
                bot_id=bot.id,
                client_id=client_id,
                event_type="skill_index",
                count=len(_enrolled_rows),
                data=_skill_trace_data,
            ))


# ===== Cluster 7d tool-retrieval extraction =====
#
# Stage 18 (tool retrieval + policy gate + unretrieved-tool index + discovery
# trace, 182 LOC) was the second-largest stage in `assemble_context`. The
# `bot.tool_retrieval` branch stays in the caller so the helper is only
# invoked when retrieval is actually running.


async def _run_tool_retrieval(
    *,
    messages: list[dict],
    bot: BotConfig,
    user_message: Any,
    ch_row: Any,
    state: AssemblyStageState,
    correlation_id: Any,
    session_id: Any,
    client_id: Any,
    context_profile: Any,
    tool_surface_policy: str | None,
    ledger: AssemblyLedger,
) -> AsyncGenerator[dict[str, Any], None]:
    """Tool-RAG retrieval + policy gate + pinned/retrieved merge + compact
    unretrieved-tool index injection. Writes `pre_selected_tools`,
    `authorized_names`, `tool_discovery_info` to ``out_state``. Only called
    when `bot.tool_retrieval` is on — caller keeps the gate."""
    tagged_tool_names = state.tagged_tool_names
    tagged_skill_names = state.tagged_skill_names
    inject_decisions = ledger.inject_decisions
    budget_can_afford = ledger.can_afford
    budget_consume = ledger.consume
    out_state = state
    _enrolled_tool_names: list[str] = []
    if bot.id:
        try:
            from app.services.tool_enrollment import get_enrolled_tool_names as _get_enrolled_tools
            _enrolled_tool_names = await _get_enrolled_tools(bot.id)
        except Exception:
            logger.warning("Failed to load enrolled tools for %s", bot.id, exc_info=True)

    by_name = await _all_tool_schemas_by_name(
        bot, enrolled_tool_names=_enrolled_tool_names,
    ) if (
        bot.local_tools or bot.mcp_servers or bot.client_tools
        or bot.pinned_tools or _enrolled_tool_names
    ) else {}
    if "get_tool_info" not in by_name:
        for _gti in get_local_tool_schemas(["get_tool_info"]):
            by_name[_gti["function"]["name"]] = _gti
    if bot.tool_discovery and "search_tools" not in by_name:
        for _st in get_local_tool_schemas(["search_tools"]):
            by_name[_st["function"]["name"]] = _st
    if bot.tool_discovery:
        for _name in ("list_tool_signatures", "run_script"):
            if _name not in by_name:
                for _sch in get_local_tool_schemas([_name]):
                    by_name[_sch["function"]["name"]] = _sch
    for _sk_name in ("get_skill", "get_skill_list"):
        if _sk_name not in by_name:
            for _sk_schema in get_local_tool_schemas([_sk_name]):
                by_name[_sk_schema["function"]["name"]] = _sk_schema

    _surface_policy = tool_surface_policy if tool_surface_policy in {"focused_escape", "strict", "full"} else "full"
    _authorized_names: set[str] = set(by_name.keys())
    out_state["authorized_names"] = _authorized_names

    th = (
        bot.tool_similarity_threshold
        if bot.tool_similarity_threshold is not None
        else settings.TOOL_RETRIEVAL_THRESHOLD
    )
    retrieved, tool_sim, tool_candidates = await retrieve_tools(
        user_message,
        bot.local_tools,
        bot.mcp_servers,
        threshold=th,
        discover_all=bot.tool_discovery,
    )
    _ch_disabled_tools = set(getattr(ch_row, "local_tools_disabled", None) or []) if ch_row else set()
    if _ch_disabled_tools:
        retrieved = [t for t in retrieved if t.get("function", {}).get("name") not in _ch_disabled_tools]
    if settings.TOOL_POLICY_ENABLED and retrieved:
        from app.db.engine import async_session as _policy_session_factory
        from app.services.tool_policies import evaluate_tool_policy
        async with _policy_session_factory() as _pol_db:
            _policy_allowed = []
            for _rt in retrieved:
                _rn = _rt.get("function", {}).get("name")
                if _rn and _rn not in _authorized_names:
                    _decision = await evaluate_tool_policy(_pol_db, bot.id, _rn, {})
                    if _decision.action == "deny":
                        continue
                _policy_allowed.append(_rt)
            retrieved = _policy_allowed
    for _rt in retrieved:
        _rn = _rt.get("function", {}).get("name")
        if _rn:
            _authorized_names.add(_rn)
            if _rn not in by_name:
                by_name[_rn] = _rt

    if correlation_id is not None:
        asyncio.create_task(_record_trace_event(
            correlation_id=correlation_id,
            session_id=session_id,
            bot_id=bot.id,
            client_id=client_id,
            event_type="tool_retrieval",
            count=len(retrieved),
            data={"best_similarity": _safe_sim(tool_sim), "threshold": th,
                  "selected": [t["function"]["name"] for t in retrieved],
                  "top_candidates": tool_candidates},
        ))

    pre_selected_tools: list[dict[str, Any]] | None = None
    if by_name:
        _broad_pinned = list(bot.pinned_tools or [])
        if _surface_policy == "full":
            _effective_pinned = _broad_pinned + tagged_tool_names + ["get_tool_info"]
            if bot.tool_discovery:
                _effective_pinned.append("search_tools")
                _effective_pinned.append("list_tool_signatures")
                _effective_pinned.append("run_script")
            if _enrolled_tool_names:
                _effective_pinned += _enrolled_tool_names
            if bot.skills and (context_profile.allow_skill_index or tagged_skill_names):
                _effective_pinned += ["get_skill", "get_skill_list"]
        elif _surface_policy == "focused_escape":
            _effective_pinned = tagged_tool_names + ["get_tool_info"]
            if bot.tool_discovery:
                _effective_pinned.append("search_tools")
                _effective_pinned.append("list_tool_signatures")
                _effective_pinned.append("run_script")
            if tagged_skill_names:
                _effective_pinned += ["get_skill", "get_skill_list"]
        else:
            _effective_pinned = list(tagged_tool_names)
            if tagged_skill_names:
                _effective_pinned += ["get_skill", "get_skill_list"]
        pinned_list = [by_name[n] for n in _effective_pinned if n in by_name]
        _server_pins = {n for n in _effective_pinned if n not in by_name}
        if _server_pins:
            for _tool_name, _schema in by_name.items():
                if get_mcp_server_for_tool(_tool_name) in _server_pins:
                    pinned_list.append(_schema)
        client_only = get_client_tool_schemas(bot.client_tools)
        merged = _merge_tool_schemas(pinned_list, retrieved, client_only)
        if not merged:
            pre_selected_tools = list(by_name.values()) if _surface_policy == "full" else []
        else:
            pre_selected_tools = merged

        _retrieved_names = {t["function"]["name"] for t in pre_selected_tools}
        if _surface_policy != "full":
            _authorized_names = set(_retrieved_names)
            out_state["authorized_names"] = _authorized_names
        _unretrieved = [
            (n, s["function"])
            for n, s in by_name.items()
            if n not in _retrieved_names and n not in ("get_tool_info", "search_tools")
        ]
        if _unretrieved:
            _index_lines = "\n".join(
                f"  • {_compact_tool_usage(n, fn)}" for n, fn in _unretrieved
            )
            _header = (
                "You have MORE tools available than what's currently loaded. "
                "BEFORE producing a best-effort answer — or saying you don't have a tool — "
                "call get_tool_info(tool_name=\"<name>\") for any entry below that could "
                "plausibly apply. These lines are an index; the full schema is only accessible "
                "via get_tool_info."
            )
            if bot.tool_discovery:
                _header += (
                    " If the right tool isn't in this list, call "
                    "search_tools(query=\"...\") to semantically search the full pool "
                    "BEFORE giving up."
                )
            _header += (
                " Acting without fetching the schema when a relevant tool exists "
                "is the primary source of wrong/missing actions.\n"
            )
            _tool_idx_content = _header + _index_lines
            if not context_profile.allow_tool_index:
                _mark_injection_decision(inject_decisions, "tool_index", "skipped_by_profile")
            elif budget_can_afford(_tool_idx_content):
                messages.append({"role": "system", "content": _tool_idx_content})
                budget_consume("tool_index", _tool_idx_content)
                _mark_injection_decision(inject_decisions, "tool_index", "admitted")
                yield {"type": "tool_index", "unretrieved_count": len(_unretrieved)}
            else:
                _mark_injection_decision(inject_decisions, "tool_index", "skipped_by_budget")
                logger.info("Budget: skipping tool index hints (%d tools)", len(_unretrieved))
        elif context_profile.allow_tool_index:
            _mark_injection_decision(inject_decisions, "tool_index", "skipped_empty")

        out_state["tool_discovery_info"] = {
            "tool_retrieval_enabled": True,
            "tool_discovery_enabled": bool(bot.tool_discovery),
            "threshold": th,
            "pool_total": len(by_name),
            "pinned": list(bot.pinned_tools or []),
            "included": sorted(by_name.keys()),
            "enrolled_working_set": list(_enrolled_tool_names),
            "retrieved": [t["function"]["name"] for t in retrieved],
            "retrieved_count": len(retrieved),
            "tool_surface": _surface_policy,
            "excluded_broad_pin_count": len({
                n for n in _broad_pinned
                if n in by_name and n not in _retrieved_names
            }) if _surface_policy != "full" else 0,
            "top_candidates": tool_candidates[:5] if tool_candidates else [],
            "best_similarity": _safe_sim(tool_sim),
            "unretrieved_count": len(_unretrieved) if _unretrieved else 0,
        }

    out_state["pre_selected_tools"] = pre_selected_tools


# ===== Cluster 7e-a tool-exposure finalization =====
#
# Stages 19 (dynamic tool injection), 20 (widget-handler tools), and 21
# (capability-gated tool exposure) together finalize the tool surface
# exposed to the model. They all read/mutate the same two locals
# (`pre_selected_tools`, `authorized_names`), so they extract as a single
# helper. No yields — plain async.


async def _finalize_exposed_tools(
    *,
    bot: BotConfig,
    channel_id: Any,
    ch_row: Any,
    tool_surface_policy: str | None,
    state: AssemblyStageState,
) -> None:
    pre_selected_tools = state.pre_selected_tools
    authorized_names = state.authorized_names
    # --- merge dynamically injected tools (e.g. post_heartbeat_to_channel) ---
    from app.agent.context import current_injected_tools
    _injected = current_injected_tools.get()
    if _injected:
        _injected_names = [t["function"]["name"] for t in _injected]
        logger.info("Injecting tools: %s", _injected_names)
        if pre_selected_tools is not None:
            _existing = {t["function"]["name"] for t in pre_selected_tools}
            for t in _injected:
                if t["function"]["name"] not in _existing:
                    pre_selected_tools.append(t)

    # Include dynamically injected tool names in the authorized set
    if _injected and authorized_names is not None:
        authorized_names.update(t["function"]["name"] for t in _injected)

    # --- widget-handler tools (bot↔widget bridge) ---
    # For every pinned widget whose manifest declares bot-callable handlers,
    # surface them as `widget__<slug>__<handler>` tools. Visibility is the
    # caller's channel dashboard + any dashboard the calling bot authored.
    # See `app/services/widget_handler_tools.py` for visibility + dispatch.
    if (channel_id or bot.id) and tool_surface_policy not in {"focused_escape", "strict"}:
        try:
            from app.db.engine import async_session as _wh_session_factory
            from app.services.widget_handler_tools import list_widget_handler_tools
            async with _wh_session_factory() as _wh_db:
                _wh_schemas, _ = await list_widget_handler_tools(
                    _wh_db, bot.id, str(channel_id) if channel_id else None,
                )
            if _wh_schemas:
                if pre_selected_tools is None:
                    pre_selected_tools = list(_wh_schemas)
                else:
                    _existing = {t["function"]["name"] for t in pre_selected_tools}
                    for _sch in _wh_schemas:
                        if _sch["function"]["name"] not in _existing:
                            pre_selected_tools.append(_sch)
                if authorized_names is None:
                    authorized_names = set()
                authorized_names.update(
                    t["function"]["name"] for t in _wh_schemas
                )
                logger.debug(
                    "widget_handler_tools: injected %d handler(s) for bot=%s channel=%s",
                    len(_wh_schemas), bot.id, channel_id,
                )
        except Exception:
            logger.warning(
                "widget_handler_tools: enumeration failed; widget tools will not be surfaced this turn",
                exc_info=True,
            )

    # --- capability-gated tool exposure ---
    # Drop tools whose required_capabilities / required_integrations the
    # current channel's bindings can't satisfy. Keeps respond_privately,
    # open_modal, and slack_* surface tools out of the LLM's tool list
    # on channels that can't honor them — rather than letting the agent
    # call the tool and hit a runtime "unsupported" error. Structural
    # fix for the Phase 3/4 Slack-depth bug documented in
    # project-notes/Architecture Decisions.md (Channel binding model).
    if ch_row is not None:
        try:
            from app.agent.capability_gate import build_view
            from app.integrations import renderer_registry as _rreg
            from app.services.dispatch_resolution import resolve_targets as _resolve_targets
            from app.tools.registry import get_tool_capability_requirements

            _targets = await _resolve_targets(ch_row)
            _bound_ids = [iid for iid, _t in _targets]
            _caps_map = {
                iid: getattr(_rreg.get(iid), "capabilities", frozenset())
                for iid in _bound_ids
                if _rreg.get(iid) is not None
            }
            _view = build_view(_bound_ids, _caps_map)

            def _tool_is_exposable(_name: str) -> bool:
                _req_caps, _req_ints = get_tool_capability_requirements(_name)
                return _view.tool_is_exposable(_req_caps, _req_ints)

            if authorized_names is not None:
                _dropped = {n for n in authorized_names if not _tool_is_exposable(n)}
                if _dropped:
                    authorized_names -= _dropped
                    logger.debug(
                        "capability_gate: dropped %d tools on channel=%s (bound=%s): %s",
                        len(_dropped), channel_id,
                        sorted(_view.bound_integrations), sorted(_dropped),
                    )
            if pre_selected_tools is not None:
                pre_selected_tools = [
                    _t for _t in pre_selected_tools
                    if _tool_is_exposable(_t.get("function", {}).get("name", ""))
                ]
        except Exception:
            logger.warning(
                "capability_gate: filter failed for channel %s — continuing without gate",
                channel_id, exc_info=True,
            )

    state.pre_selected_tools = pre_selected_tools
    state.authorized_names = authorized_names


# ===== Cluster 7e-b late cache-safe injections =====
#
# Stages 22 (datetime + conversation-gap framing), 23 (pinned widget state),
# 24 (tool refusal guard), plus the trailing context-profile note. All four
# share the same "cache-safety band" — they inject AFTER the tool surface
# is finalized but BEFORE channel prompt / preamble / user message, so they
# can't bust the prompt-cache prefix. All four mutate messages + inject_chars
# + inject_decisions in place; plain async, no yields, no out_state.


async def _inject_late_cache_safe_context(
    *,
    messages: list[dict],
    bot: BotConfig,
    channel_id: Any,
    ch_row: Any,
    session_id: uuid.UUID | None,
    authorized_names: set[str] | None,
    context_profile: ContextProfile,
    ledger: AssemblyLedger,
) -> None:
    inject_chars = ledger.inject_chars
    inject_decisions = ledger.inject_decisions
    budget_can_afford = ledger.can_afford
    budget_consume = ledger.consume
    # --- datetime + conversation-gap framing (injected late to avoid busting prompt cache prefix) ---
    if context_profile.allow_temporal_context:
        try:
            from zoneinfo import ZoneInfo
            from app.services.temporal_context import (
                ScanMessage,
                TemporalBlockInputs,
                build_current_time_block,
            )
            _tz = ZoneInfo(settings.TIMEZONE)
            _now_local = datetime.now(_tz)
            _now_utc = datetime.now(timezone.utc)

            _last_human_dt: datetime | None = None
            _last_non_human_dt: datetime | None = None
            _scan_messages: list[ScanMessage] = []
            if session_id is not None:
                try:
                    from sqlalchemy import select as _sa_select_t
                    from app.db.engine import async_session as _async_session_t
                    from app.db.models import Message as _MessageT
                    _cutoff = _now_utc - timedelta(seconds=5)
                    async with _async_session_t() as _tdb:
                        _recent_rows = (await _tdb.execute(
                            _sa_select_t(
                                _MessageT.role,
                                _MessageT.content,
                                _MessageT.metadata_,
                                _MessageT.created_at,
                            )
                            .where(_MessageT.session_id == session_id)
                            .where(_MessageT.role.in_(("user", "assistant")))
                            .where(_MessageT.created_at < _cutoff)
                            .order_by(_MessageT.created_at.desc())
                            .limit(15)
                        )).all()

                        for _r in _recent_rows:
                            _meta = _r.metadata_ or {}
                            _is_bot_sender = _meta.get("sender_type") == "bot"
                            _is_hb = bool(_meta.get("is_heartbeat"))
                            _is_human = _r.role == "user" and not _is_bot_sender and not _is_hb
                            if not _is_human and _last_non_human_dt is None:
                                _last_non_human_dt = _r.created_at
                            if _is_human and _last_human_dt is None:
                                _last_human_dt = _r.created_at
                            _content = _r.content if isinstance(_r.content, str) else ""
                            if _content:
                                _sender_id = _meta.get("sender_id") or _meta.get("bot_id")
                                _is_self = _r.role == "assistant" and (
                                    _sender_id is None or _sender_id == bot.id
                                )
                                _scan_messages.append(ScanMessage(
                                    role=_r.role,
                                    content=_content,
                                    created_at=_r.created_at,
                                    is_human=_is_human,
                                    is_self=_is_self,
                                ))
                except Exception:
                    logger.debug("temporal_context: DB lookup failed", exc_info=True)

            _time_block = build_current_time_block(TemporalBlockInputs(
                now_local=_now_local,
                now_utc=_now_utc,
                last_human_dt=_last_human_dt,
                last_non_human_dt=_last_non_human_dt,
                recent_messages=_scan_messages,
            ))
            if budget_can_afford(_time_block):
                messages.append({"role": "system", "content": _time_block})
                budget_consume("temporal_context", _time_block)
                inject_chars["temporal_context"] = len(_time_block)
                _mark_injection_decision(inject_decisions, "temporal_context", "admitted")
            else:
                _mark_injection_decision(inject_decisions, "temporal_context", "skipped_by_budget")
        except Exception:
            pass
    else:
        _mark_injection_decision(inject_decisions, "temporal_context", "skipped_by_profile")

    # --- pinned widget state (stale-but-OK, same cache-safety band as temporal) ---
    try:
        if ch_row is not None and context_profile.allow_pinned_widgets:
            from app.db.engine import async_session as _pw_session
            from app.services.widget_context import (
                build_pinned_widget_context_snapshot,
                fetch_channel_pin_dicts,
                is_pinned_widget_context_enabled,
            )
            if not is_pinned_widget_context_enabled(getattr(ch_row, "config", None) or {}):
                _mark_injection_decision(inject_decisions, "pinned_widgets", "skipped_by_channel_config")
            else:
                async with _pw_session() as _pw_db:
                    _pins = await fetch_channel_pin_dicts(_pw_db, ch_row.id)
                if _pins:
                    async with _pw_session() as _pw_db:
                        _snapshot = await build_pinned_widget_context_snapshot(
                            _pw_db,
                            _pins,
                            bot_id=bot.id,
                            channel_id=str(ch_row.id),
                        )
                    _widget_block = _snapshot.get("block_text")
                    if isinstance(_widget_block, str) and _widget_block and budget_can_afford(_widget_block):
                        messages.append({"role": "system", "content": _widget_block})
                        budget_consume("pinned_widgets", _widget_block)
                        inject_chars["pinned_widgets"] = len(_widget_block)
                        _mark_injection_decision(inject_decisions, "pinned_widgets", "admitted")
                    elif isinstance(_widget_block, str) and _widget_block:
                        _mark_injection_decision(inject_decisions, "pinned_widgets", "skipped_by_budget")
                    else:
                        _mark_injection_decision(inject_decisions, "pinned_widgets", "skipped_empty")
                else:
                    _mark_injection_decision(inject_decisions, "pinned_widgets", "skipped_empty")
    except Exception:
        logger.debug("pinned_widgets: injection failed", exc_info=True)
    if not context_profile.allow_pinned_widgets:
        _mark_injection_decision(inject_decisions, "pinned_widgets", "skipped_by_profile")

    # --- tool refusal guard (counters history poisoning from prior "I can't" turns) ---
    # Scans recent assistant turns for refusal phrases. If any are found, injects a
    # corrective system message; if the refusal named a tool that IS now authorized,
    # the message names it specifically. Same cache-safety band as temporal/widgets.
    try:
        if authorized_names and context_profile.allow_tool_refusal_guard:
            from app.services.tool_refusal_guard import (
                build_tool_authority_block,
                scan_assistant_refusals,
            )
            _assistant_contents = [
                m.get("content") for m in messages
                if isinstance(m, dict) and m.get("role") == "assistant"
            ]
            # Newest first — matches the 5-turn recent-window intent
            _assistant_contents.reverse()
            _refusal = scan_assistant_refusals(_assistant_contents, set(authorized_names))
            _guard_block = build_tool_authority_block(_refusal)
            if _guard_block and budget_can_afford(_guard_block):
                messages.append({"role": "system", "content": _guard_block})
                budget_consume("tool_refusal_guard", _guard_block)
                inject_chars["tool_refusal_guard"] = len(_guard_block)
                _mark_injection_decision(inject_decisions, "tool_refusal_guard", "admitted")
                if _refusal.stale_refused:
                    logger.info(
                        "tool_refusal_guard: correcting stale refusals for %s on channel %s",
                        _refusal.stale_refused, channel_id,
                    )
            elif _guard_block:
                _mark_injection_decision(inject_decisions, "tool_refusal_guard", "skipped_by_budget")
            else:
                _mark_injection_decision(inject_decisions, "tool_refusal_guard", "skipped_empty")
    except Exception:
        logger.debug("tool_refusal_guard: injection failed", exc_info=True)
    if not context_profile.allow_tool_refusal_guard:
        _mark_injection_decision(inject_decisions, "tool_refusal_guard", "skipped_by_profile")

    _context_profile_note = _build_context_profile_note(
        context_profile=context_profile,
        inject_decisions=inject_decisions,
    )
    if _context_profile_note:
        if budget_can_afford(_context_profile_note):
            messages.append({"role": "system", "content": _context_profile_note})
            budget_consume("context_profile_note", _context_profile_note)
            inject_chars["context_profile_note"] = len(_context_profile_note)
            _mark_injection_decision(inject_decisions, "context_profile_note", "admitted")
        else:
            _mark_injection_decision(inject_decisions, "context_profile_note", "skipped_by_budget")


# ===== Cluster 7e-c message assembly =====
#
# Stages 25-29: channel prompt, system preamble, current-turn marker, bot
# system_prompt reinforcement, and the user message (text or audio). All five
# mutate `messages` + `inject_chars` in place and the final stage mutates
# `result.user_msg_index`. Plain async, no yields, no out_state.


async def _append_prompt_and_user_message(
    *,
    messages: list[dict],
    bot: BotConfig,
    channel_id: Any,
    ch_row: Any,
    user_message: str | None,
    attachments: Any,
    audio_data: str | None,
    audio_format: str | None,
    native_audio: bool,
    system_preamble: str | None,
    task_mode: bool,
    ledger: AssemblyLedger,
    result: Any,
) -> None:
    inject_chars = ledger.inject_chars
    budget_consume = ledger.consume
    # --- project prompt (shared across every channel attached to the Project) ---
    if channel_id is not None and ch_row is not None and getattr(ch_row, "project_id", None):
        try:
            from app.db.engine import async_session
            from app.services.projects import resolve_project_prompt

            async with async_session() as db:
                _project_prompt = await resolve_project_prompt(db, ch_row)
            if _project_prompt:
                messages.append({"role": "system", "content": _project_prompt})
                inject_chars["project_prompt"] = len(_project_prompt)
                budget_consume("project_prompt", _project_prompt)
        except Exception:
            logger.warning("Failed to resolve project prompt for channel %s", channel_id, exc_info=True)

    # --- channel prompt (injected just before user message) ---
    if channel_id is not None and ch_row is not None:
        _ch_ws_path = getattr(ch_row, "channel_prompt_workspace_file_path", None)
        _ch_ws_id = getattr(ch_row, "channel_prompt_workspace_id", None)
        _ch_inline = getattr(ch_row, "channel_prompt", None)
        if _ch_ws_path and _ch_ws_id:
            from app.services.prompt_resolution import resolve_workspace_file_prompt
            _ch_prompt = resolve_workspace_file_prompt(str(_ch_ws_id), _ch_ws_path, _ch_inline or "")
        else:
            _ch_prompt = _ch_inline
        if _ch_prompt:
            messages.append({"role": "system", "content": _ch_prompt})
            inject_chars["channel_prompt"] = len(_ch_prompt)
            budget_consume("channel_prompt", _ch_prompt)

    # --- system preamble (e.g. heartbeat metadata — injected before user message, after all RAG context) ---
    if system_preamble:
        messages.append({"role": "system", "content": system_preamble})
        inject_chars["system_preamble"] = len(system_preamble)
        budget_consume("system_preamble", system_preamble)

    # --- current-turn marker (helps models distinguish injected context from the live message) ---
    if task_mode:
        # Heartbeat or other system-initiated task — frame as executable task, not conversation
        _turn_marker = {
            "role": "system",
            "content": "Everything above is background context. Your TASK PROMPT follows — execute it now.",
        }
        messages.append(_turn_marker)
    else:
        _turn_marker = {
            "role": "system",
            "content": "Everything above is context and conversation history. The user's CURRENT message follows — respond to it directly.",
        }
        messages.append(_turn_marker)
    budget_consume("base_context", _turn_marker)

    # --- bot system_prompt reinforcement (recency bias) ---
    # Repeats bot.system_prompt near the end of the message array so weaker
    # models don't lose it under ~12KB of framework text. Disabled by default
    # (strong models don't need it). Gated on REINFORCE_SYSTEM_PROMPT setting.
    if settings.REINFORCE_SYSTEM_PROMPT and not task_mode:
        _bot_sys_prompt = bot.system_prompt or ""
        if getattr(bot, "system_prompt_workspace_file", False):
            try:
                from app.services.prompt_resolution import resolve_workspace_file_prompt
                _ws_prompt = resolve_workspace_file_prompt(
                    bot.shared_workspace_id,
                    f"bots/{bot.id}/system_prompt.md",
                    "",
                )
                if _ws_prompt:
                    _bot_sys_prompt = _ws_prompt
            except Exception:
                pass
        if _bot_sys_prompt.strip():
            _reinforce = f"## Your Role (these are your active instructions — follow them)\n\n{_bot_sys_prompt.rstrip()}"
            messages.append({"role": "system", "content": _reinforce})
            inject_chars["bot_system_prompt_reinforce"] = len(_reinforce)
            budget_consume("bot_system_prompt_reinforce", _reinforce)

    # --- user message (audio or text) ---
    if native_audio:
        _audio_instruction = {
            "role": "system",
            "content": _AUDIO_TRANSCRIPT_INSTRUCTION,
        }
        messages.append(_audio_instruction)
        budget_consume("base_context", _AUDIO_TRANSCRIPT_INSTRUCTION)
        user_msg = _build_audio_user_message(audio_data, audio_format)
        messages.append(user_msg)
        budget_consume("current_user_message", user_msg.get("content", ""))
        result.user_msg_index = len(messages) - 1
    elif user_message:
        from app.security.prompt_sanitize import sanitize_unicode
        user_content = _build_user_message_content(sanitize_unicode(user_message), attachments)
        messages.append({"role": "user", "content": user_content})
        budget_consume("current_user_message", user_content)
        result.user_msg_index = len(messages) - 1
    # When user_message is empty (e.g. member bot replies), no user message is
    # appended — the system_preamble and conversation history are sufficient.


# ===== Cluster 7e-d finalization traces =====
#
# Stages 30-33: store budget utilization, injection summary trace, active-skills
# snapshot, discovery summary trace. All happen after messages are finalized.
# Writes to `result`, fires `asyncio.create_task(_record_trace_event(...))`
# twice, and pushes the active-skills list into the `current_skills_in_context`
# ctxvar. No yields, no out_state.


async def _emit_finalization_traces(
    *,
    bot: BotConfig,
    correlation_id: Any,
    session_id: Any,
    client_id: Any,
    context_profile: ContextProfile,
    ledger: AssemblyLedger,
    state: AssemblyStageState,
    result: Any,
) -> None:
    budget = ledger.budget
    inject_chars = ledger.inject_chars
    inject_decisions = ledger.inject_decisions
    enrolled_rows = state.enrolled_rows
    enrolled_ids = state.enrolled_ids
    ranked_relevant = state.ranked_relevant
    auto_injected = state.auto_injected
    auto_injected_similarities = state.auto_injected_similarities
    suggestion_rows = state.suggestion_rows
    history_fetched_skills = state.history_fetched_skills
    history_skill_records = state.history_skill_records
    tool_discovery_info = state.tool_discovery_info
    # --- store budget utilization for downstream (compaction trigger) ---
    if budget is not None:
        result.budget_utilization = budget.utilization

    # Mirror the per-category breakdown onto the result so dry-run / preview
    # callers can read it without scraping trace events.
    if inject_chars:
        result.inject_chars = dict(inject_chars)
    if inject_decisions:
        result.inject_decisions = dict(inject_decisions)

    # --- injection summary trace ---
    if correlation_id is not None and (inject_chars or inject_decisions):
        _summary_data: dict[str, Any] = {
            "breakdown": inject_chars,
            "total_chars": sum(inject_chars.values()),
            "context_profile": context_profile.name,
            "context_origin": result.context_origin,
            "context_policy": result.context_policy,
            "decisions": inject_decisions,
        }
        if budget is not None:
            _summary_data["context_budget"] = budget.to_dict()
        asyncio.create_task(_record_trace_event(
            correlation_id=correlation_id,
            session_id=session_id,
            bot_id=bot.id,
            client_id=client_id,
            event_type="context_injection_summary",
            data=_summary_data,
        ))

    # --- active skills snapshot for UI ---
    # Surfaces which skills are still in the LLM's context this turn (fetched via
    # prior get_skill() calls and still sitting in conversation history). The loop
    # consumes result.active_skills and emits an `active_skills` stream event so
    # turn_worker can tag the assistant message metadata.
    if history_fetched_skills:
        _skill_name_map: dict[str, str] = {r.id: r.name for r in enrolled_rows}
        _missing_skill_ids = [sid for sid in history_fetched_skills if sid not in _skill_name_map]
        if _missing_skill_ids:
            try:
                from app.db.engine import async_session as _async_session_names
                from app.db.models import Skill as _SkillRowForNames
                from sqlalchemy import select as _sa_select_names
                async with _async_session_names() as _db:
                    _name_rows = (await _db.execute(
                        _sa_select_names(_SkillRowForNames.id, _SkillRowForNames.name)
                        .where(_SkillRowForNames.id.in_(_missing_skill_ids))
                    )).all()
                    for _nr in _name_rows:
                        _skill_name_map[_nr.id] = _nr.name
            except Exception:
                logger.warning("active_skills name lookup failed", exc_info=True)
        for _sid, _rec in sorted(
            history_skill_records.items(),
            key=lambda item: (
                int(item[1].get("messages_ago", 0)),
                str(_skill_name_map.get(item[0], item[0])).lower(),
            ),
        ):
            _entry = {
                "skill_id": _sid,
                "skill_name": _skill_name_map.get(_sid, _sid),
                "source": _rec.get("source", "loaded"),
                "messages_ago": int(_rec.get("messages_ago", 0)),
            }
            result.skills_in_context.append(_entry)
            if _entry["source"] == "loaded":
                result.active_skills.append({
                    "skill_id": _sid,
                    "skill_name": _entry["skill_name"],
                })
        current_skills_in_context.set(list(result.skills_in_context))

    # --- discovery summary trace (skills + tools, consolidated for at-a-glance) ---
    # Emitted unconditionally so the UI can render a single "what did discovery do
    # this turn" card. Complements the richer skill_index / tool_retrieval events
    # that carry full detail.
    if correlation_id is not None:
        _discovery_data: dict[str, Any] = {
            "skills": {
                "enrolled_count": len(enrolled_ids),
                "enrolled_in_context": len(enrolled_rows),
                "relevant_count": len(ranked_relevant),
                "auto_injected": [
                    {"skill_id": sid, "similarity": auto_injected_similarities.get(sid, 0.0)}
                    for sid in auto_injected
                ],
                "discoverable_unenrolled_count": len(suggestion_rows),
                "auto_inject_threshold": settings.SKILL_ENROLLED_AUTO_INJECT_THRESHOLD,
                "auto_inject_max": settings.SKILL_ENROLLED_AUTO_INJECT_MAX,
                "ranking_enabled": settings.SKILL_ENROLLED_RANKING_ENABLED,
                "history_fetched": sorted(history_fetched_skills) if history_fetched_skills else [],
            },
            "tools": tool_discovery_info,
        }
        asyncio.create_task(_record_trace_event(
            correlation_id=correlation_id,
            session_id=session_id,
            bot_id=bot.id,
            client_id=client_id,
            event_type="discovery_summary",
            data=_discovery_data,
        ))


async def _inject_plan_artifact(
    messages: list[dict],
    session_id: uuid.UUID | None,
    ledger: AssemblyLedger,
    context_profile: ContextProfile,
) -> None:
    """Inject a compact block derived from the active canonical plan artifact."""
    inject_chars = ledger.inject_chars
    budget_consume = ledger.consume
    budget_can_afford = ledger.can_afford
    inject_decisions = ledger.inject_decisions
    if not context_profile.allow_plan_artifact:
        return
    if session_id is None:
        _mark_injection_decision(inject_decisions, "plan_artifact", "skipped_missing")
        return

    try:
        from app.db.engine import async_session
        from app.db.models import Session as SessionRow
        from app.services.session_plan_mode import build_plan_artifact_context

        async with async_session() as db:
            session_row = await db.get(SessionRow, session_id)
        if session_row is None:
            _mark_injection_decision(inject_decisions, "plan_artifact", "skipped_missing")
            return

        content = build_plan_artifact_context(session_row)
        if not content:
            _mark_injection_decision(inject_decisions, "plan_artifact", "skipped_empty")
            return
        if not budget_can_afford(content):
            _mark_injection_decision(inject_decisions, "plan_artifact", "skipped_by_budget")
            return

        messages.append({"role": "system", "content": content})
        budget_consume("plan_artifact", content)
        inject_chars["plan_artifact"] = len(content)
        _mark_injection_decision(inject_decisions, "plan_artifact", "admitted")
    except Exception:
        logger.warning("Failed to inject plan artifact for session %s", session_id, exc_info=True)
        _mark_injection_decision(inject_decisions, "plan_artifact", "skipped_error")


async def _inject_memory_scheme(
    messages: list[dict],
    bot: BotConfig,
    ledger: AssemblyLedger,
    injected_paths: set[str],
    context_profile: ContextProfile,
) -> AsyncGenerator[dict[str, Any], None]:
    """Inject memory scheme files (MEMORY.md, daily logs, reference index).

    Populates `injected_paths` with relative paths of injected files (for fs RAG dedup).
    """
    import os
    from datetime import date, timedelta

    from app.services.memory_scheme import get_memory_root, get_memory_index_prefix, get_memory_rel_path
    from app.services.workspace import workspace_service
    inject_chars = ledger.inject_chars
    budget_consume = ledger.consume
    budget_can_afford = ledger.can_afford
    inject_decisions = ledger.inject_decisions
    try:
        ws_root = workspace_service.get_workspace_root(bot.id, bot)
        mem_root = get_memory_root(bot, ws_root=ws_root)
        mem_rel = get_memory_index_prefix(bot)
        mem_file_rel = get_memory_rel_path(bot)

        # 1. MEMORY.md — always inject
        md_path = os.path.join(mem_root, "MEMORY.md")
        if os.path.isfile(md_path):
            content = Path(md_path).read_text()
            if content.strip():
                inject_chars["memory_bootstrap"] = len(content)
                full = f"Your persistent memory ({mem_file_rel}/MEMORY.md — curated stable facts):\n\n{content}"
                messages.append({"role": "system", "content": full})
                budget_consume("memory_bootstrap", full)
                injected_paths.add(f"{mem_rel}/MEMORY.md")
                _mark_injection_decision(inject_decisions, "memory_bootstrap", "admitted")
                yield {"type": "memory_scheme_bootstrap", "chars": len(content)}

                line_count = content.count("\n") + 1
                if settings.MEMORY_MD_NUDGE_THRESHOLD > 0 and line_count > settings.MEMORY_MD_NUDGE_THRESHOLD:
                    _nudge_text = (
                        f"[Memory housekeeping] Your MEMORY.md is {line_count} lines "
                        f"(threshold: {settings.MEMORY_MD_NUDGE_THRESHOLD}). "
                        "Consider pruning stale entries, merging duplicates, or moving detailed "
                        "notes to reference/ files to keep MEMORY.md concise and fast to scan."
                    )
                    if context_profile.allow_memory_recent_logs and budget_can_afford(_nudge_text):
                        messages.append({"role": "system", "content": _nudge_text})
                        budget_consume("memory_housekeeping", _nudge_text)
                        _mark_injection_decision(inject_decisions, "memory_housekeeping", "admitted")
                    elif not context_profile.allow_memory_recent_logs:
                        _mark_injection_decision(inject_decisions, "memory_housekeeping", "skipped_by_profile")
                    else:
                        _mark_injection_decision(inject_decisions, "memory_housekeeping", "skipped_by_budget")
            else:
                _mark_injection_decision(inject_decisions, "memory_bootstrap", "skipped_empty")
        else:
            _mark_injection_decision(inject_decisions, "memory_bootstrap", "skipped_missing")

        # 2. Today's daily log
        today = date.today().isoformat()
        today_path = os.path.join(mem_root, "logs", f"{today}.md")
        if not context_profile.allow_memory_recent_logs:
            _mark_injection_decision(inject_decisions, "memory_today_log", "skipped_by_profile")
        elif os.path.isfile(today_path):
            content = Path(today_path).read_text()
            if content.strip():
                full = f"Today's daily log ({mem_file_rel}/logs/{today}.md):\n\n{content}"
                if budget_can_afford(full):
                    inject_chars["memory_today_log"] = len(content)
                    messages.append({"role": "system", "content": full})
                    budget_consume("memory_today_log", full)
                    injected_paths.add(f"{mem_rel}/logs/{today}.md")
                    _mark_injection_decision(inject_decisions, "memory_today_log", "admitted")
                    yield {"type": "memory_scheme_today_log", "chars": len(content)}
                else:
                    _mark_injection_decision(inject_decisions, "memory_today_log", "skipped_by_budget")
            else:
                _mark_injection_decision(inject_decisions, "memory_today_log", "skipped_empty")
        else:
            _mark_injection_decision(inject_decisions, "memory_today_log", "skipped_missing")

        # 3. Yesterday's daily log
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        yesterday_path = os.path.join(mem_root, "logs", f"{yesterday}.md")
        if not context_profile.allow_memory_recent_logs:
            _mark_injection_decision(inject_decisions, "memory_yesterday_log", "skipped_by_profile")
        elif os.path.isfile(yesterday_path):
            content = Path(yesterday_path).read_text()
            if content.strip():
                full = f"Yesterday's daily log ({mem_file_rel}/logs/{yesterday}.md):\n\n{content}"
                if budget_can_afford(full):
                    inject_chars["memory_yesterday_log"] = len(content)
                    messages.append({"role": "system", "content": full})
                    budget_consume("memory_yesterday_log", full)
                    injected_paths.add(f"{mem_rel}/logs/{yesterday}.md")
                    _mark_injection_decision(inject_decisions, "memory_yesterday_log", "admitted")
                    yield {"type": "memory_scheme_yesterday_log", "chars": len(content)}
                else:
                    _mark_injection_decision(inject_decisions, "memory_yesterday_log", "skipped_by_budget")
            else:
                _mark_injection_decision(inject_decisions, "memory_yesterday_log", "skipped_empty")
        else:
            _mark_injection_decision(inject_decisions, "memory_yesterday_log", "skipped_missing")

        # 4. List reference/ files
        ref_dir = os.path.join(mem_root, "reference")
        if not context_profile.allow_memory_recent_logs:
            _mark_injection_decision(inject_decisions, "memory_reference_index", "skipped_by_profile")
        elif os.path.isdir(ref_dir):
            ref_files = sorted(
                f for f in os.listdir(ref_dir)
                if f.endswith(".md") and os.path.isfile(os.path.join(ref_dir, f))
            )
            if ref_files:
                ref_entries = []
                for rf in ref_files:
                    try:
                        mtime = os.path.getmtime(os.path.join(ref_dir, rf))
                        rf_date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
                        ref_entries.append(f"  - {rf} (modified {rf_date})")
                    except Exception:
                        ref_entries.append(f"  - {rf}")
                content = (
                    f"Reference documents in {mem_file_rel}/reference/ (use get_memory_file to read):\n"
                    + "\n".join(ref_entries)
                )
                if budget_can_afford(content):
                    messages.append({"role": "system", "content": content})
                    budget_consume("memory_reference_index", content)
                    _mark_injection_decision(inject_decisions, "memory_reference_index", "admitted")
                    yield {"type": "memory_scheme_reference_index", "count": len(ref_files)}
                else:
                    _mark_injection_decision(inject_decisions, "memory_reference_index", "skipped_by_budget")
            else:
                _mark_injection_decision(inject_decisions, "memory_reference_index", "skipped_empty")
        else:
            _mark_injection_decision(inject_decisions, "memory_reference_index", "skipped_missing")

        # 5. List loose .md files in memory/ root (not MEMORY.md, not dirs)
        _skip = {"MEMORY.md"}
        if not context_profile.allow_memory_recent_logs:
            _mark_injection_decision(inject_decisions, "memory_loose_files", "skipped_by_profile")
        else:
            loose_files = sorted(
                f for f in os.listdir(mem_root)
                if f.endswith(".md") and f not in _skip
                and os.path.isfile(os.path.join(mem_root, f))
            )
            if loose_files:
                loose_entries = []
                for lf in loose_files:
                    try:
                        mtime = os.path.getmtime(os.path.join(mem_root, lf))
                        lf_date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
                        loose_entries.append(f"  - {lf} (modified {lf_date})")
                    except Exception:
                        loose_entries.append(f"  - {lf}")
                content = (
                    f"Other files in {mem_file_rel}/ (use file(read) to access):\n"
                    + "\n".join(loose_entries)
                    + f"\n\nTip: consider moving these to {mem_file_rel}/reference/ "
                    "so they appear in the reference index."
                )
                if budget_can_afford(content):
                    messages.append({"role": "system", "content": content})
                    budget_consume("memory_loose_files", content)
                    _mark_injection_decision(inject_decisions, "memory_loose_files", "admitted")
                    yield {"type": "memory_scheme_loose_files", "count": len(loose_files)}
                else:
                    _mark_injection_decision(inject_decisions, "memory_loose_files", "skipped_by_budget")
            else:
                _mark_injection_decision(inject_decisions, "memory_loose_files", "skipped_empty")

        # 6. Memory-write nudge — remind bot to save if it hasn't written
        #    to memory/ recently. Scan messages for file tool calls that
        #    wrote to memory/. Count user turns since last such write.
        _NUDGE_TURN_THRESHOLD = 5
        user_turns_since_memory_write = 0
        found_memory_write = False
        for msg in reversed(messages):
            role = msg.get("role", "")
            if role == "user":
                user_turns_since_memory_write += 1
                if user_turns_since_memory_write > _NUDGE_TURN_THRESHOLD:
                    break
            elif role == "tool":
                # Check if this was a file tool call that wrote to memory/
                content_str = msg.get("content", "")
                if isinstance(content_str, str) and "memory/" in content_str and '"ok"' in content_str:
                    found_memory_write = True
                    break
            elif role == "assistant":
                # Check tool_calls in assistant messages for memory/ paths
                for tc in msg.get("tool_calls", []):
                    args = tc.get("function", {}).get("arguments", "")
                    if isinstance(args, str) and "memory/" in args:
                        name = tc.get("function", {}).get("name", "")
                        if name == "file":
                            found_memory_write = True
                            break
                if found_memory_write:
                    break

        if user_turns_since_memory_write >= _NUDGE_TURN_THRESHOLD and not found_memory_write:
            content = (
                f"[Memory reminder] {user_turns_since_memory_write} user messages since your "
                "last memory write. If the user stated any preferences, corrections, facts, "
                "or decisions, write them to memory NOW — they will be lost on compaction."
            )
            if context_profile.allow_memory_recent_logs and budget_can_afford(content):
                messages.append({"role": "system", "content": content})
                budget_consume("memory_nudge", content)
                _mark_injection_decision(inject_decisions, "memory_nudge", "admitted")
                yield {"type": "memory_scheme_nudge", "turns_since_write": user_turns_since_memory_write}
            elif not context_profile.allow_memory_recent_logs:
                _mark_injection_decision(inject_decisions, "memory_nudge", "skipped_by_profile")
            else:
                _mark_injection_decision(inject_decisions, "memory_nudge", "skipped_by_budget")
        elif context_profile.allow_memory_recent_logs:
            _mark_injection_decision(inject_decisions, "memory_nudge", "skipped_empty")

    except Exception:
        logger.warning("Failed to inject memory scheme files for bot %s", bot.id, exc_info=True)


_CW_TOOLS = [
    "file", "search_channel_archive", "search_channel_workspace",
    "search_channel_knowledge", "search_bot_knowledge", "list_channels",
]
_CW_BUDGET = 50_000


async def _inject_channel_workspace(
    messages: list[dict],
    bot: BotConfig,
    ch_row: Any,
    user_message: str,
    ledger: AssemblyLedger,
    context_profile: ContextProfile,
    model_override: str | None = None,
    provider_id_override: str | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Inject channel workspace files, data listing, schema, index segments, and plan stall detection."""
    import os
    import time

    from app.services.channel_workspace import get_channel_workspace_root, ensure_channel_workspace

    ch_id = str(ch_row.id)
    inject_chars = ledger.inject_chars
    budget_consume = ledger.consume
    budget_can_afford = ledger.can_afford
    inject_decisions = ledger.inject_decisions

    try:
        from app.db.engine import async_session
        from app.services.projects import project_workspace_path, resolve_channel_project_directory
        from app.services.shared_workspace import shared_workspace_service

        async with async_session() as db:
            project_dir = await resolve_channel_project_directory(db, ch_row, bot)

        if project_dir is not None:
            cw_root = project_dir.host_path
            cw_abs = project_workspace_path(project_dir)
            index_root = shared_workspace_service.get_host_root(project_dir.workspace_id)
            channel_index_prefix = project_dir.path
            helper_prefix = (
                f"Project workspace — {project_dir.name or project_dir.path}\n"
                "This channel is attached to the Project root below; treat it as the default working surface for code, files, search, and exec.\n"
            )
        else:
            ensure_channel_workspace(ch_id, bot, display_name=ch_row.name)
            cw_root = get_channel_workspace_root(ch_id, bot)
            cw_abs = f"/workspace/channels/{ch_id}"
            index_root = str(Path(cw_root).parent.parent)
            channel_index_prefix = f"channels/{ch_id}"
            helper_prefix = ""

        # Collect .md files
        cw_files: list[tuple[str, str]] = []
        total_chars = 0
        if os.path.isdir(cw_root):
            for entry in sorted(os.scandir(cw_root), key=lambda e: e.name):
                if entry.is_file() and entry.name.endswith(".md"):
                    try:
                        content = Path(entry.path).read_text()
                        if content.strip():
                            if total_chars + len(content) > _CW_BUDGET:
                                content = content[:_CW_BUDGET - total_chars] + "\n\n[...truncated]"
                            cw_files.append((entry.name, content))
                            total_chars += len(content)
                            if total_chars >= _CW_BUDGET:
                                break
                    except Exception:
                        pass
        else:
            logger.warning("Channel workspace dir does not exist: %s", cw_root)

        # List data/ files
        data_dir = os.path.join(cw_root, "data")
        data_listing = ""
        if os.path.isdir(data_dir):
            data_entries = sorted(e.name for e in os.scandir(data_dir) if e.is_file())
            if data_entries:
                data_listing = (
                    "\nData files (data/ — not auto-injected, reference via workspace .md files):\n"
                    + "\n".join(f"  - {n}" for n in data_entries) + "\n"
                )

        # Resolve workspace schema
        schema_content = ""
        ch_schema_override = getattr(ch_row, "workspace_schema_content", None)
        if ch_schema_override:
            schema_content = ch_schema_override
        elif getattr(ch_row, "workspace_schema_template_id", None):
            try:
                from app.db.engine import async_session
                from app.services.prompt_resolution import resolve_prompt_template
                async with async_session() as db:
                    schema_content = await resolve_prompt_template(
                        str(ch_row.workspace_schema_template_id), fallback="", db=db,
                    )
            except Exception:
                logger.warning("Failed to resolve workspace schema template for channel %s", ch_row.id, exc_info=True)

        # Build and inject helper prompt
        from app.services.providers import resolve_prompt_style
        helper = _render_channel_workspace_prompt(
            workspace_path=cw_abs,
            channel_id=ch_id,
            data_listing=data_listing,
            style=resolve_prompt_style(
                bot,
                ch_row,
                model_override=model_override,
                provider_id_override=provider_id_override,
            ),
        )
        if helper_prefix:
            helper = helper_prefix + helper
        if schema_content:
            helper = schema_content + "\n\n" + helper

        body = ""
        if cw_files:
            sections = [f"## {cw_abs}/{fname}\n\n{fcontent}" for fname, fcontent in cw_files]
            body = "\n\n---\n\n".join(sections)

        full = helper + body
        if context_profile.allow_channel_workspace:
            if budget_can_afford(full):
                inject_chars["channel_workspace"] = total_chars
                messages.append({"role": "system", "content": full})
                budget_consume("channel_workspace", full)
                _mark_injection_decision(inject_decisions, "channel_workspace", "admitted")
                yield {"type": "channel_workspace_context", "count": len(cw_files), "chars": total_chars}
            else:
                _mark_injection_decision(inject_decisions, "channel_workspace", "skipped_by_budget")
        else:
            _mark_injection_decision(inject_decisions, "channel_workspace", "skipped_by_profile")

        # Background re-index
        from app.services.bot_indexing import reindex_channel
        cw_segments = getattr(ch_row, "index_segments", None) or []
        asyncio.create_task(reindex_channel(
            ch_id,
            bot,
            channel_segments=cw_segments if cw_segments else None,
            force=False,
        ))

        # Channel index segment RAG retrieval.
        # Always include the implicit channels/{id}/knowledge-base/ segment so the
        # convention-based KB folder is retrievable without any configuration.
        try:
            from app.agent.fs_indexer import retrieve_filesystem_context
            from app.services.bot_indexing import resolve_for
            plan = resolve_for(bot, scope="workspace")
            if plan is None:
                raise RuntimeError("channel RAG requires workspace-enabled bot")

            implicit_kb_prefix = f"{channel_index_prefix}/.spindrel/knowledge-base" if project_dir is not None else f"channels/{ch_id}/knowledge-base"
            seg_dicts: list[dict] = [{
                "path_prefix": implicit_kb_prefix,
                "embedding_model": plan.embedding_model,
            }]
            for seg in cw_segments:
                explicit_prefix = f"{channel_index_prefix}/{seg['path_prefix'].strip('/')}"
                if explicit_prefix.rstrip("/") == implicit_kb_prefix:
                    continue  # user's explicit segment wins, don't double-register
                seg_dicts.append({
                    "path_prefix": explicit_prefix,
                    "embedding_model": seg.get("embedding_model") or plan.embedding_model,
                })

            seg_top_k = max((seg.get("top_k", 8) for seg in cw_segments), default=8)
            seg_threshold = min((seg.get("similarity_threshold", 0.35) for seg in cw_segments), default=0.35)
            chunks, sim = await retrieve_filesystem_context(
                user_message, f"channel:{ch_row.id}",
                roots=[str(Path(index_root).resolve())],
                embedding_model=plan.embedding_model,
                segments=seg_dicts,
                top_k=seg_top_k,
                threshold=seg_threshold,
            )
            if chunks:
                seg_body = "\n\n".join(chunks)
                seg_header = (
                    f"{CHANNEL_INDEX_SEGMENTS_RAG_PREFIX if cw_segments else CHANNEL_KNOWLEDGE_BASE_RAG_PREFIX}:\n\n"
                )
                if "search_channel_knowledge" in bot.local_tools:
                    seg_header += "(Call search_channel_knowledge for targeted lookups beyond these auto-retrieved excerpts.)\n\n"
                elif "search_workspace" in bot.local_tools:
                    seg_header += "(Use search_workspace for targeted searches beyond these auto-retrieved excerpts.)\n\n"
                seg_content = seg_header + seg_body
                if not context_profile.allow_channel_index_segments:
                    _mark_injection_decision(inject_decisions, "channel_index_segments", "skipped_by_profile")
                elif budget_can_afford(seg_content):
                    messages.append({"role": "system", "content": seg_content})
                    budget_consume("channel_index_segments", seg_content)
                    inject_chars["channel_index_segments"] = len(seg_body)
                    _mark_injection_decision(inject_decisions, "channel_index_segments", "admitted")
                    yield {"type": "channel_index_segments", "count": len(chunks), "similarity": sim}
                else:
                    _mark_injection_decision(inject_decisions, "channel_index_segments", "skipped_by_budget")
            else:
                _mark_injection_decision(inject_decisions, "channel_index_segments", "skipped_empty")
        except Exception:
            logger.warning("Failed to retrieve channel knowledge-base / index segments for channel %s", ch_row.id, exc_info=True)

    except Exception:
        logger.warning("Failed to inject channel workspace files for channel %s", ch_row.id, exc_info=True)


async def _inject_conversation_sections(
    messages: list[dict],
    bot: BotConfig,
    ch_row: Any,
    channel_id: uuid.UUID,
    session_id: uuid.UUID | None,
    user_message: str,
    ledger: AssemblyLedger,
    context_profile: ContextProfile,
) -> AsyncGenerator[dict[str, Any], None]:
    """Inject conversation section context (structured mode) or section index (file mode)."""
    from app.db.engine import async_session
    from app.db.models import ConversationSection
    from app.services.compaction import _get_history_mode
    from sqlalchemy import func, select
    from sqlalchemy.orm import defer
    inject_chars = ledger.inject_chars
    budget_consume = ledger.consume
    budget_can_afford = ledger.can_afford
    inject_decisions = ledger.inject_decisions

    if not context_profile.allow_conversation_sections:
        _mark_injection_decision(inject_decisions, "conversation_sections", "skipped_by_profile")
        _mark_injection_decision(inject_decisions, "section_index", "skipped_by_profile")
        return

    hist_mode = _get_history_mode(bot, ch_row)

    if hist_mode == "structured" and user_message:
        from app.agent.embeddings import embed_text
        from app.agent.vector_ops import halfvec_cosine_distance
        query_vec = await embed_text(user_message)
        async with async_session() as db:
            rows = (await db.execute(
                select(ConversationSection)
                .where(
                    ConversationSection.session_id == session_id,
                    ConversationSection.embedding.is_not(None),
                )
                .order_by(halfvec_cosine_distance(ConversationSection.embedding, query_vec))
                .limit(3)
            )).scalars().all()
        if rows:
            texts = [r.transcript if r.transcript else f"## {r.title}\n{r.summary}" for r in rows]
            chars = sum(len(t) for t in texts)
            content = CONVERSATION_SECTIONS_RAG_PREFIX + CHUNK_SEPARATOR.join(texts)
            if budget_can_afford(content):
                inject_chars["conversation_sections"] = chars
                messages.append({"role": "system", "content": content})
                budget_consume("conversation_sections", content)
                _mark_injection_decision(inject_decisions, "conversation_sections", "admitted")
                yield {"type": "section_context", "count": len(rows), "chars": chars}
            else:
                _mark_injection_decision(inject_decisions, "conversation_sections", "skipped_by_budget")
        else:
            _mark_injection_decision(inject_decisions, "conversation_sections", "skipped_empty")

    elif hist_mode == "file":
        if session_id is None:
            _mark_injection_decision(inject_decisions, "section_index", "skipped_missing")
            return
        si_count = getattr(ch_row, "section_index_count", None)
        si_count = si_count if si_count is not None else settings.SECTION_INDEX_COUNT
        if si_count > 0:
            si_verbosity = getattr(ch_row, "section_index_verbosity", None) or settings.SECTION_INDEX_VERBOSITY
            async with async_session() as db:
                rows = (await db.execute(
                    select(ConversationSection)
                    .where(ConversationSection.session_id == session_id)
                    .order_by(ConversationSection.sequence.desc())
                    .limit(si_count)
                    .options(defer(ConversationSection.transcript), defer(ConversationSection.embedding))
                )).scalars().all()
                total = (await db.execute(
                    select(func.count())
                    .select_from(ConversationSection)
                    .where(ConversationSection.session_id == session_id)
                )).scalar() or 0
                all_tags: list[str] | None = None
                if rows and total > len(rows):
                    tag_rows = (await db.execute(
                        select(ConversationSection.tags)
                        .where(ConversationSection.session_id == session_id)
                    )).scalars().all()
                    all_tags = [tag for tags in tag_rows if tags for tag in tags]
            if rows:
                from app.services.compaction import format_section_index
                text = format_section_index(rows, verbosity=si_verbosity, total_sections=total, all_tags=all_tags)
                if budget_can_afford(text):
                    inject_chars["section_index"] = len(text)
                    messages.append({"role": "system", "content": text})
                    budget_consume("section_index", text)
                    _mark_injection_decision(inject_decisions, "section_index", "admitted")
                    yield {"type": "section_index_context", "count": len(rows), "chars": len(text)}
                else:
                    _mark_injection_decision(inject_decisions, "section_index", "skipped_by_budget")
            else:
                _mark_injection_decision(inject_decisions, "section_index", "skipped_empty")
        else:
            _mark_injection_decision(inject_decisions, "section_index", "skipped_empty")


async def _inject_workspace_rag(
    messages: list[dict],
    bot: BotConfig,
    ch_row: Any | None,
    channel_id: uuid.UUID | None,
    user_message: str,
    correlation_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    client_id: str | None,
    ledger: AssemblyLedger,
    memory_scheme_injected_paths: set[str],
    excluded_path_prefixes: set[str],
    context_profile: ContextProfile,
) -> AsyncGenerator[dict[str, Any], None]:
    """Inject workspace filesystem RAG context (current and legacy paths)."""
    from app.agent.fs_indexer import retrieve_filesystem_context
    budget_consume = ledger.consume
    budget_can_afford = ledger.can_afford
    budget = ledger.budget
    inject_decisions = ledger.inject_decisions

    if not context_profile.allow_workspace_rag:
        _mark_injection_decision(inject_decisions, "workspace_rag", "skipped_by_profile")
        return

    do_rag = False
    if bot.workspace.enabled and bot.workspace.indexing.enabled:
        channel_rag = True
        if ch_row is not None and not getattr(ch_row, "workspace_rag", True):
            channel_rag = False
        do_rag = channel_rag

    if do_rag:
        from app.services.bot_indexing import resolve_for
        plan = resolve_for(bot, scope="workspace")
        assert plan is not None  # guarded above by bot.workspace.enabled
        fs_chunks, fs_sim = await retrieve_filesystem_context(
            user_message, bot.id, roots=list(plan.roots),
            threshold=plan.similarity_threshold, top_k=plan.top_k,
            embedding_model=plan.embedding_model,
            segments=plan.segments,
            channel_id=str(channel_id) if channel_id else None,
            exclude_paths=sorted(memory_scheme_injected_paths) if memory_scheme_injected_paths else None,
            exclude_path_prefixes=sorted(excluded_path_prefixes) if excluded_path_prefixes else None,
        )
        if fs_chunks:
            body = (
                f"{WORKSPACE_RAG_PREFIX} (partial segments — "
                "use the file tool with operation=\"read\" to read full file contents):\n\n"
                + CHUNK_SEPARATOR.join(fs_chunks)
            )
            if budget_can_afford(body):
                yield {"type": "fs_context", "count": len(fs_chunks)}
                if correlation_id is not None:
                    asyncio.create_task(_record_trace_event(
                        correlation_id=correlation_id, session_id=session_id,
                        bot_id=bot.id, client_id=client_id,
                        event_type="fs_context", count=len(fs_chunks),
                        data={"preview": fs_chunks[0][:200], "best_similarity": _safe_sim(fs_sim)},
                    ))
                messages.append({"role": "system", "content": body})
                budget_consume("fs_context", body)
                _mark_injection_decision(inject_decisions, "workspace_rag", "admitted")
            else:
                _mark_injection_decision(inject_decisions, "workspace_rag", "skipped_by_budget")
                logger.info("Budget: skipping workspace fs RAG (%d chunks, budget remaining: %d)",
                           len(fs_chunks), budget.remaining if budget else 0)
        else:
            _mark_injection_decision(inject_decisions, "workspace_rag", "skipped_empty")

    elif bot.filesystem_indexes:
        fs_threshold = min(
            (cfg.similarity_threshold for cfg in bot.filesystem_indexes if cfg.similarity_threshold is not None),
            default=None,
        )
        fs_chunks, fs_sim = await retrieve_filesystem_context(
            user_message,
            bot.id,
            threshold=fs_threshold,
            exclude_path_prefixes=sorted(excluded_path_prefixes) if excluded_path_prefixes else None,
        )
        if fs_chunks:
            body = (
                f"{LEGACY_INDEXED_DIRECTORIES_RAG_PREFIX} (partial segments — "
                "use the file tool with operation=\"read\" to read full file contents):\n\n"
                + CHUNK_SEPARATOR.join(fs_chunks)
            )
            if not budget_can_afford(body):
                _mark_injection_decision(inject_decisions, "workspace_rag", "skipped_by_budget")
                return
            yield {"type": "fs_context", "count": len(fs_chunks)}
            if correlation_id is not None:
                asyncio.create_task(_record_trace_event(
                    correlation_id=correlation_id, session_id=session_id,
                    bot_id=bot.id, client_id=client_id,
                    event_type="fs_context", count=len(fs_chunks),
                    data={"preview": fs_chunks[0][:200], "best_similarity": _safe_sim(fs_sim)},
                ))
            messages.append({"role": "system", "content": body})
            budget_consume("fs_context", body)
            _mark_injection_decision(inject_decisions, "workspace_rag", "admitted")
        else:
            _mark_injection_decision(inject_decisions, "workspace_rag", "skipped_empty")


async def _inject_bot_knowledge_base(
    messages: list[dict],
    bot: BotConfig,
    user_message: str,
    ledger: AssemblyLedger,
    context_profile: ContextProfile,
) -> AsyncGenerator[dict[str, Any], None]:
    """Inject semantic excerpts from the bot's own knowledge-base/ folder."""
    inject_chars = ledger.inject_chars
    budget_consume = ledger.consume
    budget_can_afford = ledger.can_afford
    inject_decisions = ledger.inject_decisions
    if not context_profile.allow_bot_knowledge_base:
        _mark_injection_decision(inject_decisions, "bot_knowledge_base", "skipped_by_profile")
        return
    if not bot.workspace.enabled or not bot.workspace.indexing.enabled:
        _mark_injection_decision(inject_decisions, "bot_knowledge_base", "skipped_missing")
        return
    if not getattr(bot.workspace, "bot_knowledge_auto_retrieval", True):
        _mark_injection_decision(inject_decisions, "bot_knowledge_base", "skipped_disabled")
        return

    try:
        from app.agent.fs_indexer import retrieve_filesystem_context
        from app.services.bot_indexing import resolve_for
        from app.services.workspace import workspace_service

        plan = resolve_for(bot, scope="workspace")
        assert plan is not None  # guarded above by bot.workspace.enabled
        kb_prefix = workspace_service.get_bot_knowledge_base_index_prefix(bot)
        kb_segments: list[dict[str, Any]] = [{
            "path_prefix": kb_prefix,
            "embedding_model": plan.embedding_model,
        }]
        chunks, sim = await retrieve_filesystem_context(
            user_message,
            bot.id,
            roots=list(plan.roots),
            threshold=plan.similarity_threshold,
            top_k=plan.top_k,
            embedding_model=plan.embedding_model,
            segments=kb_segments,
        )
        if not chunks:
            _mark_injection_decision(inject_decisions, "bot_knowledge_base", "skipped_empty")
            return

        kb_body = "\n\n".join(chunks)
        kb_header = f"{BOT_KNOWLEDGE_BASE_RAG_PREFIX}:\n\n"
        if "search_bot_knowledge" in bot.local_tools:
            kb_header += "(Call search_bot_knowledge for targeted lookups beyond these auto-retrieved excerpts.)\n\n"
        elif "search_workspace" in bot.local_tools:
            kb_header += "(Use search_workspace for targeted searches beyond these auto-retrieved excerpts.)\n\n"
        kb_content = kb_header + kb_body
        if budget_can_afford(kb_content):
            messages.append({"role": "system", "content": kb_content})
            budget_consume("bot_knowledge_base", kb_content)
            inject_chars["bot_knowledge_base"] = len(kb_body)
            _mark_injection_decision(inject_decisions, "bot_knowledge_base", "admitted")
            yield {"type": "bot_knowledge_base", "count": len(chunks), "similarity": sim}
        else:
            _mark_injection_decision(inject_decisions, "bot_knowledge_base", "skipped_by_budget")
    except Exception:
        logger.warning("Failed to retrieve bot knowledge-base for bot %s", bot.id, exc_info=True)
        _mark_injection_decision(inject_decisions, "bot_knowledge_base", "skipped_error")


async def assemble_context(
    messages: list[dict],
    bot: BotConfig,
    user_message: str,
    session_id: uuid.UUID | None,
    client_id: str | None,
    correlation_id: uuid.UUID | None,
    channel_id: uuid.UUID | None,
    audio_data: str | None,
    audio_format: str | None,
    attachments: list[dict] | None,
    native_audio: bool,
    result: AssemblyResult,
    system_preamble: str | None = None,
    budget: "ContextBudget | None" = None,
    task_mode: bool = False,
    skip_skill_inject: bool = False,
    context_profile_name: str | None = None,
    model_override: str | None = None,
    provider_id_override: str | None = None,
    tool_surface_policy: str | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Inject all RAG context into messages and yield status events.

    Mutates `messages` in-place. Populates `result` with side-channel outputs.
    """
    # Fire before_context_assembly lifecycle hook
    from app.agent.hooks import fire_hook, HookContext
    await fire_hook("before_context_assembly", HookContext(
        bot_id=bot.id, session_id=session_id, channel_id=channel_id,
        client_id=client_id, correlation_id=correlation_id,
        extra={"user_message": user_message},
    ))

    context_profile = get_context_profile(context_profile_name or "chat")
    result.context_profile = context_profile.name
    result.context_origin = current_run_origin.get(None)
    result.context_policy = context_profile.to_policy_dict()
    current_skills_in_context.set([])
    ledger = AssemblyLedger(budget=budget)
    stage_state = AssemblyStageState(bot=bot)

    # --- channel-level tool/skill overrides ---
    _ch_row = await _load_channel_overrides(channel_id=channel_id)

    # --- context pruning (trim stale tool results) ---
    async for _evt in _run_context_pruning(
        messages=messages,
        bot=bot,
        ch_row=_ch_row,
        ledger=ledger,
        correlation_id=correlation_id,
        session_id=session_id,
        client_id=client_id,
    ):
        yield _evt

    # --- account for pre-existing messages after pruning ---
    bot = _apply_effective_tools_and_budget(
        messages=messages,
        bot=bot,
        ch_row=_ch_row,
        ledger=ledger,
        result=result,
    )
    stage_state.bot = bot

    # --- skill enrollment loading (Phase 3 working set model) ---
    # `bot_skill_enrollment` is the source of truth for "what skills does
    # this bot know about"; bot-authored skills are discovered each turn
    # and persisted as enrollment rows rather than merged inline.
    async for _evt in _load_skill_enrollments(bot=bot, state=stage_state):
        yield _evt
    bot = stage_state.bot or bot

    # --- memory scheme: file injection ---
    # NOTE: memory-scheme TOOL injection (search_memory, file, etc.) is handled
    # by apply_auto_injections() above. This section only does file/context injection.
    _memory_scheme_injected_paths: set[str] = set()
    if bot.memory_scheme == "workspace-files":
        async for evt in _inject_memory_scheme(
            messages, bot, ledger, _memory_scheme_injected_paths, context_profile,
        ):
            yield evt

    # --- channel workspace: file injection + tool injection ---
    if _ch_row is not None:
        # Inject channel workspace tools into bot config
        cw_filtered = list(bot.local_tools)
        for cwt in _CW_TOOLS:
            if cwt not in cw_filtered:
                cw_filtered.append(cwt)
        bot = _dc_replace(
            bot,
            local_tools=cw_filtered,
            pinned_tools=list(dict.fromkeys((bot.pinned_tools or []) + _CW_TOOLS)),
        )
        async for evt in _inject_channel_workspace(
            messages, bot, _ch_row, user_message, ledger, context_profile,
            model_override=model_override,
            provider_id_override=provider_id_override,
        ):
            yield evt

    await _inject_plan_artifact(
        messages,
        session_id,
        ledger,
        context_profile,
    )

    # --- @mention tag resolution ---
    async for _evt in _resolve_tagged_mentions(
        messages=messages,
        bot=bot,
        user_message=user_message,
        client_id=client_id,
        session_id=session_id,
        correlation_id=correlation_id,
        result=result,
        state=stage_state,
    ):
        yield _evt

    # --- execution_config ephemeral skills (not already @-tagged or in bot.skills) ---
    await _apply_ephemeral_skills(
        messages=messages,
        bot=bot,
        state=stage_state,
    )

    # --- skills (Phase 3 working set + semantic discovery layer + ranking) ---
    #
    # Three layers, each gated independently:
    #   1. Working set — relevance-ranked list of enrolled skills.
    #   2. Auto-inject — highest-confidence enrolled skill pre-loaded.
    #   3. Discovery — semantic retrieval over UNENROLLED catalog skills.
    async for _evt in _inject_skill_working_set(
        messages=messages,
        bot=bot,
        user_message=user_message,
        correlation_id=correlation_id,
        session_id=session_id,
        client_id=client_id,
        skip_skill_inject=skip_skill_inject,
        state=stage_state,
        ledger=ledger,
        result=result,
        context_profile=context_profile,
    ):
        yield _evt

    # --- API access tools (for bots with scoped API keys) ---
    bot, _api_event = _inject_api_access_tools(messages=messages, bot=bot)
    if _api_event:
        yield _api_event

    # --- multi-bot channel awareness + member bot injection ---
    async for _evt in _inject_multi_bot_awareness(
        messages=messages,
        bot=bot,
        channel_id=channel_id,
        ch_row=_ch_row,
        system_preamble=system_preamble,
        state=stage_state,
    ):
        yield _evt

    # --- spatial canvas awareness (opt-in per channel/bot policy) ---
    async for _evt in _inject_spatial_awareness(
        messages=messages,
        bot=bot,
        channel_id=channel_id,
        ledger=ledger,
    ):
        yield _evt

    # --- delegate bot index ---
    _delegate_event = _inject_delegate_index(
        messages=messages,
        bot=bot,
        tagged_bot_names=stage_state.tagged_bot_names,
        member_bot_ids=stage_state.member_bot_ids,
    )
    if _delegate_event:
        yield _delegate_event

    # --- DB memory injection REMOVED (deprecated — use memory_scheme='workspace-files') ---
    # --- DB RAG knowledge injection REMOVED (deprecated — use file-backed skills instead) ---

    # --- conversation section retrieval (structured mode) + section index (file mode) ---
    if channel_id is not None and _ch_row is not None:
        async for evt in _inject_conversation_sections(
            messages, bot, _ch_row, channel_id, session_id, user_message, ledger, context_profile,
        ):
            yield evt

    _workspace_rag_excluded_prefixes: set[str] = set()

    if channel_id is not None:
        _workspace_rag_excluded_prefixes.add(f"channels/{channel_id}/knowledge-base")

    if bot.workspace.enabled and bot.workspace.indexing.enabled:
        _workspace_rag_excluded_prefixes.add(
            "bots/" + bot.id + "/knowledge-base" if bot.shared_workspace_id else "knowledge-base"
        )

    # --- bot knowledge-base retrieval ---
    async for evt in _inject_bot_knowledge_base(
        messages,
        bot,
        user_message,
        ledger,
        context_profile,
    ):
        yield evt

    # --- workspace filesystem context ---
    async for evt in _inject_workspace_rag(
        messages, bot, _ch_row, channel_id, user_message,
        correlation_id, session_id, client_id,
        ledger,
        _memory_scheme_injected_paths, _workspace_rag_excluded_prefixes,
        context_profile,
    ):
        yield evt

    # --- tool retrieval (tool RAG) ---
    pre_selected_tools: list[dict[str, Any]] | None = None
    _authorized_names: set[str] | None = None
    if bot.tool_retrieval:
        async for _evt in _run_tool_retrieval(
            messages=messages,
            bot=bot,
            user_message=user_message,
            ch_row=_ch_row,
            correlation_id=correlation_id,
            session_id=session_id,
            client_id=client_id,
            context_profile=context_profile,
            tool_surface_policy=tool_surface_policy,
            state=stage_state,
            ledger=ledger,
        ):
            yield _evt
        pre_selected_tools = stage_state.pre_selected_tools
        _authorized_names = stage_state.authorized_names
    # --- tool-exposure finalization (dynamic injection + widget-handler tools + capability gate) ---
    stage_state.pre_selected_tools = pre_selected_tools
    stage_state.authorized_names = _authorized_names
    await _finalize_exposed_tools(
        bot=bot,
        channel_id=channel_id,
        ch_row=_ch_row,
        tool_surface_policy=tool_surface_policy,
        state=stage_state,
    )
    pre_selected_tools = stage_state.pre_selected_tools
    _authorized_names = stage_state.authorized_names

    result.pre_selected_tools = pre_selected_tools
    result.authorized_tool_names = _authorized_names
    result.effective_local_tools = list(bot.local_tools)
    result.tool_discovery_info = dict(stage_state.tool_discovery_info)

    # --- late cache-safe injections (temporal + pinned widgets + refusal guard + profile note) ---
    await _inject_late_cache_safe_context(
        messages=messages,
        bot=bot,
        channel_id=channel_id,
        ch_row=_ch_row,
        session_id=session_id,
        authorized_names=_authorized_names,
        context_profile=context_profile,
        ledger=ledger,
    )

    # --- message assembly (channel prompt + preamble + turn marker + reinforcement + user message) ---
    await _append_prompt_and_user_message(
        messages=messages,
        bot=bot,
        channel_id=channel_id,
        ch_row=_ch_row,
        user_message=user_message,
        attachments=attachments,
        audio_data=audio_data,
        audio_format=audio_format,
        native_audio=native_audio,
        system_preamble=system_preamble,
        task_mode=task_mode,
        ledger=ledger,
        result=result,
    )


    # --- finalization traces (budget utilization + injection/discovery summary + active-skills snapshot) ---
    await _emit_finalization_traces(
        bot=bot,
        correlation_id=correlation_id,
        session_id=session_id,
        client_id=client_id,
        context_profile=context_profile,
        ledger=ledger,
        state=stage_state,
        result=result,
    )


# ---------------------------------------------------------------------------
# Dry-run preview — same assembly path the live turn uses, no LLM call,
# no trace events written.
# ---------------------------------------------------------------------------


@dataclass
class PreviewResult:
    """What `assemble_for_preview` returns to the dev panel."""
    messages: list[dict[str, Any]]
    inject_chars: dict[str, int]
    assembly: AssemblyResult
    budget: "ContextBudget"
    bot_id: str
    model: str
    history_mode: str


async def assemble_for_preview(
    channel_id: uuid.UUID,
    *,
    user_message: str = "",
    session_id: uuid.UUID | None = None,
    db: Any | None = None,
) -> PreviewResult:
    """Run `assemble_context` for a channel without dispatching to the LLM.

    Loads the selected, active, or most recent channel session messages, then drives
    `assemble_context` to completion with `correlation_id=None` so no trace
    events are persisted. Returns the assembled messages, the per-category
    breakdown, the budget snapshot, and the AssemblyResult.

    Used by the dev panel's "next-turn forecast" view — same code path the
    live turn would take, so the displayed numbers are guaranteed to match
    the next turn's actual context (modulo any retrievals that depend on
    `user_message`).
    """
    from app.agent.bots import get_bot
    from app.agent.context_budget import ContextBudget, get_model_context_window
    from app.agent.context_profiles import resolve_context_profile
    from app.db.models import Channel, Session
    from app.services.compaction import _get_history_mode
    from app.services.sessions import _load_messages
    from sqlalchemy import select

    async def _load_preview_state(db):
        channel = await db.get(Channel, channel_id)
        if channel is None:
            raise ValueError(f"Channel not found: {channel_id}")
        bot = get_bot(channel.bot_id)
        history_mode = _get_history_mode(bot, channel)

        if session_id is not None:
            session = await db.get(Session, session_id)
            if session is None:
                raise ValueError(f"Session not found: {session_id}")
            belongs_to_channel = (
                str(session.channel_id) == str(channel.id)
                or str(session.parent_channel_id) == str(channel.id)
            )
            if not belongs_to_channel:
                raise ValueError(f"Session {session_id} does not belong to channel {channel_id}")
        elif channel.active_session_id:
            session = await db.get(Session, channel.active_session_id)
        else:
            # Find the most recent session for this channel; fall back to a
            # synthetic empty list if none exist yet.
            sess_row = await db.execute(
                select(Session)
                .where(Session.channel_id == channel_id)
                .order_by(Session.created_at.desc())
                .limit(1)
            )
            session = sess_row.scalar_one_or_none()
        if session is not None:
            messages = await _load_messages(db, session)
            resolved_session_id = session.id
        else:
            messages = []
            resolved_session_id = None
        return channel, bot, history_mode, session, messages, resolved_session_id

    if db is None:
        from app.db.engine import async_session
        async with async_session() as owned_db:
            channel, bot, history_mode, session, messages, resolved_session_id = (
                await _load_preview_state(owned_db)
            )
    else:
        channel, bot, history_mode, session, messages, resolved_session_id = (
            await _load_preview_state(db)
        )

    # Resolve effective model (channel override > bot default) for the budget.
    effective_model = getattr(channel, "model_override", None) or bot.model
    effective_provider = (
        getattr(channel, "model_provider_id_override", None)
        or bot.model_provider_id
    )
    window = get_model_context_window(effective_model, effective_provider)
    reserve = int(window * settings.CONTEXT_BUDGET_RESERVE_RATIO)
    budget = ContextBudget(total_tokens=window, reserve_tokens=reserve)

    result = AssemblyResult()
    # Drain the generator. correlation_id=None disables trace event writes,
    # so this is genuinely a read-only preview.
    async for _ in assemble_context(
        messages=messages,
        bot=bot,
        user_message=user_message,
        session_id=resolved_session_id,
        client_id=None,
        correlation_id=None,
        channel_id=channel_id,
        audio_data=None,
        audio_format=None,
        attachments=None,
        native_audio=False,
        result=result,
        system_preamble=None,
        budget=budget,
        task_mode=False,
        skip_skill_inject=False,
        context_profile_name=resolve_context_profile(session=session).name if session is not None else "chat",
    ):
        pass

    # Mirror the post-assembly tool-schema accounting that loop.py performs.
    if result.pre_selected_tools:
        tool_schema_chars = sum(len(json.dumps(t)) for t in result.pre_selected_tools)
        from app.agent.context_budget import estimate_tokens as _est
        budget.consume("tool_schemas", _est("x" * tool_schema_chars))

    return PreviewResult(
        messages=messages,
        inject_chars=dict(result.inject_chars),
        assembly=result,
        budget=budget,
        bot_id=bot.id,
        model=effective_model,
        history_mode=history_mode,
    )
