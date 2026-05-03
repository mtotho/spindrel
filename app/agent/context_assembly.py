"""Context injection pipeline — assembles RAG context before the agent tool loop."""

import asyncio
import logging
import math
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from dataclasses import replace as _dc_replace

from app.agent.bots import BotConfig
from app.agent.channel_overrides import (
    EffectiveTools,
    apply_auto_injections,
    auto_injected_pin_names,
    discovery_hatch_tool_names,
    plan_mode_control_tool_names,
    resolve_effective_tools,
)
from app.agent.context import (
    current_run_origin,
    current_skills_in_context,
    set_ephemeral_delegates,
    set_ephemeral_skills,
)
from app.agent.context_profiles import ContextProfile, get_context_profile, resolve_context_profile
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
from app.agent.recording import _record_trace_event
from app.agent.tags import resolve_tags
from app.agent.tokenization import estimate_content_tokens
from app.agent.prompt_sizing import message_prompt_tokens
from app.agent.tool_surface import enrollment as _ts_enrollment
from app.agent.tool_surface.enrollment import (
    _apply_ephemeral_skills,
    _get_bot_authored_skill_ids,
    _get_core_skill_ids,
    _get_integration_skill_ids,
    _load_skill_enrollments,
    invalidate_bot_skill_cache,
    invalidate_skill_auto_enroll_cache,
)


def __getattr__(name: str) -> Any:
    """Forward legacy private attribute reads (caches, TTLs) to the
    `tool_surface.enrollment` module so tests that access them via
    `app.agent.context_assembly._bot_skill_cache` continue to see the
    canonical state after the move."""
    if name in {
        "_bot_skill_cache",
        "_BOT_SKILL_CACHE_TTL",
        "_core_skill_cache",
        "_integration_skill_cache",
        "_SKILL_CACHE_TTL",
    }:
        return getattr(_ts_enrollment, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
from app.agent.tool_surface.finalize import _finalize_exposed_tools
from app.agent.tool_surface.heartbeat import _compose_heartbeat_tool_surface
from app.agent.tool_surface.retrieval import _run_tool_retrieval
from app.agent.tools import retrieve_tools
from app.config import settings
from app.tools.client_tools import get_client_tool_schemas
from app.tools.mcp import get_mcp_server_for_tool
from app.tools.registry import (
    get_local_tool_names_by_metadata,
    get_local_tool_schemas,
    get_local_tool_schemas_by_metadata,
)

logger = logging.getLogger(__name__)

# Enrollment sources eligible for auto-inject. Starter/migration skills are
# generic utility docs that shouldn't compete for the injection slot.
_INJECT_ELIGIBLE_SOURCES = frozenset({"authored", "fetched", "manual"})
_AGENT_SELF_INSPECTION_PROMPT = (
    "Agent self-inspection: when self-inspection tools are exposed, use them before "
    "broad API, config, integration, widget, Project, or readiness work. When they "
    "are not exposed, use the loaded task tools and report/propose a narrow config "
    "change if a required tool or scope is missing. If skills.recommended_now is "
    "present, follow its first_action before procedural work."
)
_MEMORY_FLUSH_TOOL_CAPABILITIES = (
    "memory.read",
    "memory.write",
    "workspace_memory.write",
)
_MEMORY_HYGIENE_TOOL_CAPABILITIES = (
    "memory.read",
    "memory.write",
    "workspace_memory.write",
    "conversation_history.read",
    "subsessions.read",
    "skill.write",
)
_SKILL_REVIEW_TOOL_CAPABILITIES = (
    "memory.read",
    "memory.write",
    "workspace_memory.write",
    "conversation_history.read",
    "subsessions.read",
    "skill.read",
    "skill.write",
)


def _safe_sim(value: float) -> float | None:
    """Sanitize similarity score for JSONB serialization (NaN is invalid JSON)."""
    if math.isnan(value):
        return None
    return round(value, 4)


def _plan_mode_active_from_messages(messages: list[dict[str, Any]]) -> bool:
    return any(
        message.get("role") == "system"
        and "Plan mode is active" in str(message.get("content") or "")
        for message in messages
    )


def _dedupe_tool_names(*groups: Any) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for group in groups:
        if not group:
            continue
        for raw in group:
            name = str(raw).strip() if raw is not None else ""
            if name and name not in seen:
                names.append(name)
                seen.add(name)
    return names


def _operator_pinned_tool_names(bot: BotConfig) -> list[str]:
    """Manual pins only; auto-injected chat baseline tools are availability,
    not schema pins for focused/global tool surfaces."""
    return _dedupe_tool_names(
        n for n in (bot.pinned_tools or []) if n not in auto_injected_pin_names()
    )


def _add_local_tool_schemas(
    by_name: dict[str, dict[str, Any]],
    names: tuple[str, ...],
) -> None:
    missing = [name for name in names if name not in by_name]
    if not missing:
        return
    for schema in get_local_tool_schemas(missing):
        tool_name = schema.get("function", {}).get("name")
        if tool_name:
            by_name[tool_name] = schema


def _tool_schemas_for_metadata_domain(domain: str, exposure: str = "ambient") -> list[dict[str, Any]]:
    return get_local_tool_schemas_by_metadata(domain=domain, exposure=exposure)


def _tool_names_for_metadata_domain(domain: str, exposure: str = "ambient") -> list[str]:
    return [
        schema["function"]["name"]
        for schema in _tool_schemas_for_metadata_domain(domain, exposure)
        if schema.get("function", {}).get("name")
    ]


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
    if context_profile.name in {"chat", "chat_lean", "chat_standard", "chat_rich"}:
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

def _render_channel_workspace_prompt(
    *,
    workspace_path: str,
    channel_id: str,
    data_listing: str,
    style: str = "markdown",
) -> str:
    """Compatibility wrapper for channel-workspace prompt rendering."""
    from app.agent.context_admission import render_channel_workspace_prompt

    return render_channel_workspace_prompt(
        workspace_path=workspace_path,
        channel_id=channel_id,
        data_listing=data_listing,
        style=style,
    )


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
        ledger.inject_decisions["context_pruning_saved_chars"] = str(_prune_stats["chars_saved"])
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


def _inject_api_access_tools(
    *,
    bot: BotConfig,
) -> tuple[BotConfig, dict[str, Any] | None]:
    """If the bot has scoped API permissions, inject the two API-access tools
    into both `local_tools` and `pinned_tools`, and return the replaced bot plus
    a progress event. Otherwise return the bot unchanged and `None` for the
    event.
    """
    if not bot.api_permissions:
        return bot, None
    from app.tools.registry import get_local_tool_names_by_metadata

    _api_tools = get_local_tool_names_by_metadata(auto_inject="api_access")
    _new_local = list(bot.local_tools or [])
    _new_pinned = list(dict.fromkeys(bot.pinned_tools or []))
    for _t in _api_tools:
        if _t not in _new_local:
            _new_local.append(_t)
        if _t not in _new_pinned:
            _new_pinned.append(_t)
    bot = _dc_replace(bot, local_tools=_new_local, pinned_tools=_new_pinned)
    return bot, {"type": "api_access_tools", "scopes": bot.api_permissions}


def _inject_api_access_prompt_if_exposed(
    *,
    messages: list[dict],
    bot: BotConfig,
    authorized_names: set[str] | None,
) -> dict[str, Any] | None:
    """Append API access guidance only when API tools are actually exposed."""
    if not bot.api_permissions or not authorized_names:
        return None
    from app.tools.registry import get_local_tool_names_by_metadata

    api_tools = set(get_local_tool_names_by_metadata(auto_inject="api_access"))
    exposed_api_tools = sorted(api_tools & set(authorized_names))
    if not exposed_api_tools:
        return None
    messages.append({
        "role": "system",
        "content": (
            f"You have API access to the agent server (scopes: {', '.join(bot.api_permissions)}). "
            "Use the exposed API access tools only when the user request requires server API inspection or mutation."
        ),
    })
    return {
        "type": "api_access_prompt",
        "scopes": bot.api_permissions,
        "tools": exposed_api_tools,
    }


def _inject_agent_self_inspection_prompt(messages: list[dict]) -> None:
    """Append the compact prompt contract for baseline readiness tools."""
    messages.append({
        "role": "system",
        "content": _AGENT_SELF_INSPECTION_PROMPT,
    })


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
            from app.services.projects import is_project_like_surface, resolve_channel_work_surface

            async with async_session() as db:
                surface = await resolve_channel_work_surface(db, ch_row, bot, include_prompt=True)
            if is_project_like_surface(surface) and surface.prompt:
                messages.append({"role": "system", "content": surface.prompt})
                inject_chars["project_prompt"] = len(surface.prompt)
                budget_consume("project_prompt", surface.prompt)
        except Exception as exc:
            logger.warning("Failed to resolve project prompt for channel %s", channel_id, exc_info=True)
            text = f"Project work surface could not be resolved for this channel: {exc}"
            messages.append({"role": "system", "content": text})
            inject_chars["project_work_surface_error"] = len(text)
            budget_consume("project_work_surface_error", text)

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
    if budget is not None and result.pre_selected_tools and not budget.breakdown.get("tool_schemas"):
        from app.agent.context_budget import estimate_tokens as _estimate_tokens

        tool_schema_chars = sum(len(json.dumps(tool)) for tool in result.pre_selected_tools)
        budget.consume("tool_schemas", _estimate_tokens("x" * tool_schema_chars))

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
    """Compatibility wrapper for static context-admission policy."""
    from app.agent.context_admission import inject_plan_artifact

    await inject_plan_artifact(messages, session_id, ledger, context_profile)


async def _inject_memory_scheme(
    messages: list[dict],
    bot: BotConfig,
    ledger: AssemblyLedger,
    injected_paths: set[str],
    context_profile: ContextProfile,
) -> AsyncGenerator[dict[str, Any], None]:
    """Compatibility wrapper for memory-scheme context admission."""
    from app.agent.context_admission import inject_memory_scheme

    async for event in inject_memory_scheme(
        messages,
        bot,
        ledger,
        injected_paths,
        context_profile,
    ):
        yield event


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
    """Compatibility wrapper for channel workspace context admission."""
    from app.agent.context_admission import inject_channel_workspace

    async for event in inject_channel_workspace(
        messages,
        bot,
        ch_row,
        user_message,
        ledger,
        context_profile,
        model_override=model_override,
        provider_id_override=provider_id_override,
    ):
        yield event


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
    """Compatibility wrapper for conversation-section context admission."""
    from app.agent.context_admission import inject_conversation_sections

    async for event in inject_conversation_sections(
        messages,
        bot,
        ch_row,
        channel_id,
        session_id,
        user_message,
        ledger,
        context_profile,
    ):
        yield event


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
    """Compatibility wrapper for workspace RAG context admission."""
    from app.agent.context_admission import inject_workspace_rag

    async for event in inject_workspace_rag(
        messages,
        bot,
        ch_row,
        channel_id,
        user_message,
        correlation_id,
        session_id,
        client_id,
        ledger,
        memory_scheme_injected_paths,
        excluded_path_prefixes,
        context_profile,
    ):
        yield event


async def _inject_bot_knowledge_base(
    messages: list[dict],
    bot: BotConfig,
    user_message: str,
    ledger: AssemblyLedger,
    context_profile: ContextProfile,
) -> AsyncGenerator[dict[str, Any], None]:
    """Compatibility wrapper for bot knowledge-base context admission."""
    from app.agent.context_admission import inject_bot_knowledge_base

    async for event in inject_bot_knowledge_base(
        messages,
        bot,
        user_message,
        ledger,
        context_profile,
    ):
        yield event


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
    required_tool_names: list[str] | tuple[str, ...] | None = None,
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

    if isinstance(required_tool_names, str):
        required_tool_names = [required_tool_names]
    elif required_tool_names is not None:
        required_tool_names = [str(n) for n in required_tool_names if n]
    current_skills_in_context.set([])
    ledger = AssemblyLedger(budget=budget)
    stage_state = AssemblyStageState(bot=bot)

    # --- channel-level tool/skill overrides ---
    _ch_row = await _load_channel_overrides(channel_id=channel_id)
    if context_profile_name:
        context_profile = get_context_profile(context_profile_name)
    else:
        _session_row = None
        if session_id is not None:
            try:
                from app.db.engine import async_session
                from app.db.models import Session

                async with async_session() as _profile_db:
                    _session_row = await _profile_db.get(Session, session_id)
            except Exception:
                logger.debug("context profile session lookup failed", exc_info=True)
        context_profile = resolve_context_profile(
            session=_session_row,
            origin=current_run_origin.get(None),
            channel=_ch_row,
        )
    result.context_profile = context_profile.name
    result.context_origin = current_run_origin.get(None)
    result.context_policy = context_profile.to_policy_dict()

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
        from app.agent.context_admission import apply_channel_workspace_tools

        bot = apply_channel_workspace_tools(bot)
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
    bot, _api_event = _inject_api_access_tools(bot=bot)
    if _api_event:
        yield _api_event

    # --- baseline agent self-inspection prompt contract ---
    _inject_agent_self_inspection_prompt(messages)

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
        try:
            from app.db.engine import async_session
            from app.services.projects import resolve_channel_work_surface

            async with async_session() as db:
                surface = await resolve_channel_work_surface(db, _ch_row, bot) if _ch_row is not None else None
            _workspace_rag_excluded_prefixes.add(
                surface.knowledge_index_prefix if surface is not None else f"channels/{channel_id}/knowledge-base"
            )
        except Exception:
            logger.debug("Could not resolve work surface KB prefix for workspace RAG exclusions", exc_info=True)
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
    if bot.tool_retrieval or getattr(context_profile, "name", None) in {
        "memory_flush",
        "memory_hygiene",
        "skill_review",
    }:
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
            required_tool_names=required_tool_names,
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

    _api_prompt_event = _inject_api_access_prompt_if_exposed(
        messages=messages,
        bot=bot,
        authorized_names=_authorized_names,
    )
    if _api_prompt_event:
        yield _api_prompt_event

    result.pre_selected_tools = pre_selected_tools
    result.authorized_tool_names = _authorized_names
    effective_local_tools = list(bot.local_tools)
    if _plan_mode_active_from_messages(messages):
        effective_local_tools = list(dict.fromkeys([*effective_local_tools, *plan_mode_control_tool_names()]))
    result.effective_local_tools = effective_local_tools
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
        context_profile_name=resolve_context_profile(session=session, channel=channel).name,
    ):
        pass

    # Mirror the post-assembly tool-schema accounting that loop.py performs.
    if result.pre_selected_tools and not budget.breakdown.get("tool_schemas"):
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
