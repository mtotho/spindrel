"""Compute a detailed context breakdown for a channel's active session.

Used by the admin UI to show what goes into each agent turn.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any
import uuid as _uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.agent.prompt_sizing import message_prompt_chars
from app.db.models import (
    Channel,
    Message,
    Session,
    TraceEvent,
)

logger = logging.getLogger(__name__)

# Short-lived in-memory coalescing cache for context-breakdown results. The
# endpoint re-runs the full assembly pipeline (tokenization + static prompt
# rendering + RAG estimate + compaction accounting), which is expensive
# enough to matter when tab flips or parallel widgets trigger back-to-back
# reads. 15 s is tight enough that message-level churn still surfaces on the
# next tab flip while coalescing the worst-case stampede.
_BREAKDOWN_CACHE_TTL = 15.0
_breakdown_cache: dict[tuple[str, str, str | None, str], tuple[float, "ContextBreakdownResult"]] = {}
_not_compaction_run_clause = or_(
    Message.metadata_["kind"].astext.is_(None),
    Message.metadata_["kind"].astext != "compaction_run",
)


def invalidate_context_breakdown_cache(channel_id: str | None = None) -> None:
    """Drop cached breakdowns. Called by turn_worker on TURN_ENDED so the
    post-turn recompute reflects the latest message. Passing ``None`` clears
    every entry — use sparingly."""
    if channel_id is None:
        _breakdown_cache.clear()
        return
    for key in list(_breakdown_cache):
        if key[0] == channel_id:
            _breakdown_cache.pop(key, None)


@dataclass
class ContextCategory:
    key: str
    label: str
    chars: int
    tokens_approx: int
    percentage: float
    category: str  # "static" | "rag" | "conversation" | "compaction"
    description: str


@dataclass
class CompactionState:
    enabled: bool = False
    has_summary: bool = False
    summary_chars: int = 0
    messages_since_watermark: int = 0
    user_turns_since_watermark: int = 0
    total_messages: int = 0
    compaction_interval: int = 0
    compaction_keep_turns: int = 0
    turns_until_next: int | None = None


@dataclass
class RerankState:
    enabled: bool = False
    model: str = ""
    threshold_chars: int = 0
    max_chunks: int = 0
    total_rag_chars: int = 0
    would_rerank: bool = False


@dataclass
class EffectiveSetting:
    value: Any
    source: str  # "channel" | "bot" | "global"


@dataclass
class ContextBreakdownResult:
    channel_id: str
    session_id: str | None
    bot_id: str
    categories: list[ContextCategory]
    total_chars: int
    total_tokens_approx: int
    compaction: CompactionState
    reranking: RerankState
    effective_settings: dict[str, EffectiveSetting]
    context_profile: str | None = None
    context_origin: str | None = None
    live_history_turns: int | None = None
    mandatory_static_injections: list[str] = field(default_factory=list)
    optional_static_injections: list[str] = field(default_factory=list)
    context_budget: dict | None = None
    disclaimer: str = ""


@dataclass(frozen=True)
class _InjectionSnapshot:
    budget: dict[str, Any]
    context_profile: str | None
    context_origin: str | None
    live_history_turns: int | None
    mandatory_static_injections: list[str]
    optional_static_injections: list[str]


@dataclass(frozen=True)
class _UsageSnapshot:
    gross_prompt_tokens: int | None
    current_prompt_tokens: int | None
    cached_prompt_tokens: int | None
    completion_tokens: int | None


@dataclass(frozen=True)
class _BreakdownScope:
    channel_id: str
    channel_pk: _uuid.UUID
    channel: Channel
    bot: Any
    requested_session_id: str | None
    session_id: str | None
    session_pk: _uuid.UUID | None
    session: Session | None


@dataclass(frozen=True)
class _ConversationStats:
    total_messages: int = 0
    total_msg_chars: int = 0
    msgs_since_watermark: int = 0
    chars_since_watermark: int = 0
    user_msgs_since_watermark: int | None = None
    watermark_msg: Message | None = None


@dataclass(frozen=True)
class _PreviewPolicy:
    context_profile: str | None
    context_origin: str | None
    live_history_turns: int | None
    mandatory_static_injections: list[str]
    optional_static_injections: list[str]


def _chars_to_tokens(chars: int) -> int:
    """Sign-preserving wrapper around the shared chars/3.5 estimator.

    Pruning savings are negative; the unified estimator only handles
    non-negative text, so we mirror the sign here.
    """
    from app.agent.tokenization import estimate_tokens
    if chars > 0:
        return estimate_tokens("x" * chars)
    if chars < 0:
        return -estimate_tokens("x" * abs(chars))
    return 0


def _row_prompt_chars(content: Any, tool_calls: Any) -> int:
    return message_prompt_chars({"content": content, "tool_calls": tool_calls})


def _session_scope_clause(channel_id: str | Any, session_id: str | Any | None):
    if session_id is None:
        return Session.channel_id == channel_id
    return or_(
        Session.channel_id == channel_id,
        Session.parent_channel_id == channel_id,
    )


async def _latest_trace_data(
    db: AsyncSession,
    *,
    scope_clause,
    event_type: str,
    session_id: str | Any | None,
) -> dict[str, Any]:
    query = (
        select(TraceEvent.data)
        .join(Session, TraceEvent.session_id == Session.id)
        .where(scope_clause, TraceEvent.event_type == event_type)
    )
    if session_id is not None:
        query = query.where(TraceEvent.session_id == session_id)
    row = await db.execute(query.order_by(TraceEvent.created_at.desc()).limit(1))
    return row.scalar_one_or_none() or {}


async def _latest_trace_time(
    db: AsyncSession,
    *,
    scope_clause,
    event_type: str,
    session_id: str | Any | None,
) -> Any | None:
    query = (
        select(TraceEvent.created_at)
        .join(Session, TraceEvent.session_id == Session.id)
        .where(scope_clause, TraceEvent.event_type == event_type)
    )
    if session_id is not None:
        query = query.where(TraceEvent.session_id == session_id)
    row = await db.execute(query.order_by(TraceEvent.created_at.desc()).limit(1))
    return row.scalar_one_or_none()


def _injection_snapshot(data: dict[str, Any]) -> _InjectionSnapshot:
    policy = data.get("context_policy") or {}
    return _InjectionSnapshot(
        budget=data.get("context_budget") or {},
        context_profile=data.get("context_profile"),
        context_origin=data.get("context_origin"),
        live_history_turns=policy.get("live_history_turns"),
        mandatory_static_injections=list(policy.get("mandatory_static_injections") or []),
        optional_static_injections=list(policy.get("optional_static_injections") or []),
    )


def _usage_snapshot(data: dict[str, Any]) -> _UsageSnapshot:
    gross = data.get("gross_prompt_tokens")
    if gross is None:
        gross = data.get("prompt_tokens")
    cached = data.get("cached_prompt_tokens")
    if cached is None:
        cached = data.get("cached_tokens")
    current = data.get("current_prompt_tokens")
    if current is None and gross is not None:
        current = gross if cached is None else max(0, gross - cached)
    return _UsageSnapshot(
        gross_prompt_tokens=gross,
        current_prompt_tokens=current,
        cached_prompt_tokens=cached,
        completion_tokens=data.get("completion_tokens"),
    )


def _budget_response(
    snapshot: _InjectionSnapshot,
    *,
    source: str,
    consumed: int | None,
    total_tokens: int | None,
    current_prompt_tokens: int | None,
    cached_prompt_tokens: int | None,
    completion_tokens: int | None,
    utilization: float | None = None,
) -> dict[str, Any]:
    if utilization is None and total_tokens and consumed is not None and total_tokens > 0:
        utilization = round(consumed / total_tokens, 3)
    return {
        "utilization": utilization,
        "consumed_tokens": consumed,
        "total_tokens": total_tokens,
        "gross_prompt_tokens": consumed,
        "current_prompt_tokens": current_prompt_tokens,
        "cached_prompt_tokens": cached_prompt_tokens,
        "completion_tokens": completion_tokens,
        "context_profile": snapshot.context_profile,
        "context_origin": snapshot.context_origin,
        "live_history_turns": snapshot.live_history_turns,
        "mandatory_static_injections": snapshot.mandatory_static_injections,
        "optional_static_injections": snapshot.optional_static_injections,
        "source": source,
    }


async def _model_context_window_for_channel(
    channel_id: str | Any,
    db: AsyncSession,
) -> int | None:
    from app.agent.bots import get_bot
    from app.agent.context_budget import get_model_context_window
    from app.agent.loop import _resolve_effective_provider

    channel_pk = _uuid.UUID(str(channel_id)) if not isinstance(channel_id, _uuid.UUID) else channel_id
    channel = await db.get(Channel, channel_pk)
    if channel is None:
        return None
    bot = get_bot(channel.bot_id)
    model = channel.model_override or bot.model
    provider = _resolve_effective_provider(
        channel.model_override,
        getattr(channel, "model_provider_id_override", None),
        bot.model_provider_id,
    )
    return get_model_context_window(model, provider)


async def _fresh_budget_after_compaction(
    channel_id: str | Any,
    db: AsyncSession,
    *,
    session_id: str | Any | None,
    snapshot: _InjectionSnapshot,
) -> dict[str, Any]:
    fresh_estimate = await compute_context_breakdown(
        str(channel_id),
        db,
        mode="next_turn",
        session_id=str(session_id) if session_id is not None else None,
        include_budget=False,
    )
    total_tokens = snapshot.budget.get("total_tokens")
    if total_tokens is None:
        total_tokens = await _model_context_window_for_channel(channel_id, db)
    consumed = fresh_estimate.total_tokens_approx
    return _budget_response(
        snapshot,
        source="estimate",
        consumed=consumed,
        total_tokens=total_tokens,
        current_prompt_tokens=consumed,
        cached_prompt_tokens=None,
        completion_tokens=None,
    )


async def fetch_latest_context_budget(
    channel_id: str | Any,
    db: AsyncSession,
    *,
    session_id: str | Any | None = None,
) -> dict[str, Any]:
    """Latest context utilization for this channel — API ground truth when available.

    Resolution order:

    1. Most recent ``token_usage`` trace event on any session in the channel
       — this carries the API-reported ``prompt_tokens`` (Anthropic
       ``input_tokens``). When present this is the canonical answer; the
       header and dev-panel "last turn" view both source it.
    2. If a newer ``compaction_done`` trace exists, treat any older API
       usage snapshot as stale and recompute a fresh live estimate from the
       compacted state.
    3. Fall back to the most recent ``context_injection_summary``'s
       ``context_budget`` dict (pre-call estimate) when no turn has been
       sent yet, or when the model's response didn't include usage.
    4. Sentinel with null fields when no turn has been recorded.

    Shared by ``GET /admin/channels/{id}/context-budget`` and
    ``GET /channels/{id}/context-budget`` so the two cannot drift.
    """
    scope_clause = _session_scope_clause(channel_id, session_id)
    injection = _injection_snapshot(
        await _latest_trace_data(
            db,
            scope_clause=scope_clause,
            event_type="context_injection_summary",
            session_id=session_id,
        )
    )
    usage = _usage_snapshot(
        await _latest_trace_data(
            db,
            scope_clause=scope_clause,
            event_type="token_usage",
            session_id=session_id,
        )
    )
    latest_compaction_at = await _latest_trace_time(
        db,
        scope_clause=scope_clause,
        event_type="compaction_done",
        session_id=session_id,
    )
    latest_usage_at = (
        await _latest_trace_time(
            db,
            scope_clause=scope_clause,
            event_type="token_usage",
            session_id=session_id,
        )
        if usage.gross_prompt_tokens is not None and latest_compaction_at is not None
        else None
    )

    if (
        usage.gross_prompt_tokens is not None
        and latest_compaction_at is not None
        and latest_usage_at is not None
        and latest_usage_at <= latest_compaction_at
    ):
        return await _fresh_budget_after_compaction(
            channel_id,
            db,
            session_id=session_id,
            snapshot=injection,
        )

    estimate_consumed = injection.budget.get("consumed_tokens")
    total_tokens = injection.budget.get("total_tokens")
    if usage.gross_prompt_tokens is None and estimate_consumed is None:
        return _budget_response(
            injection,
            source="none",
            consumed=None,
            total_tokens=None,
            current_prompt_tokens=None,
            cached_prompt_tokens=None,
            completion_tokens=None,
        )

    if usage.gross_prompt_tokens is None:
        return _budget_response(
            injection,
            source="estimate",
            consumed=estimate_consumed,
            total_tokens=total_tokens,
            current_prompt_tokens=estimate_consumed,
            cached_prompt_tokens=None,
            completion_tokens=None,
            utilization=injection.budget.get("utilization"),
        )

    return _budget_response(
        injection,
        source="api",
        consumed=usage.gross_prompt_tokens,
        total_tokens=total_tokens,
        current_prompt_tokens=usage.current_prompt_tokens,
        cached_prompt_tokens=usage.cached_prompt_tokens,
        completion_tokens=usage.completion_tokens,
    )


def _resolve_setting(channel_val, bot_val, global_val, channel_attr: str) -> EffectiveSetting:
    """Resolve a setting with channel > bot > global priority."""
    if channel_val is not None:
        return EffectiveSetting(value=channel_val, source="channel")
    if bot_val is not None:
        return EffectiveSetting(value=bot_val, source="bot")
    return EffectiveSetting(value=global_val, source="global")


_LABEL_TO_CATEGORY: dict[str, tuple[str, str, str]] = {
    "Global Base Prompt": (
        "global_base_prompt",
        "static",
        "Server-wide prompt from the runtime context assembly path",
    ),
    "Workspace Base Prompt": (
        "workspace_base_prompt",
        "static",
        "Workspace-authored prompt from the runtime context assembly path",
    ),
    "Bot System Prompt": (
        "system_prompt",
        "static",
        "Bot-specific system prompt from the runtime context assembly path",
    ),
    "Memory Scheme Prompt": (
        "memory_scheme_prompt",
        "static",
        "Workspace-files memory instructions from the runtime context assembly path",
    ),
    "Persona": (
        "persona",
        "static",
        "Bot persona layer from the runtime context assembly path",
    ),
    "Date/Time": (
        "datetime",
        "static",
        "Current timestamp injected by the runtime context assembly path",
    ),
    "Memory Bootstrap": (
        "memory_bootstrap",
        "static",
        "MEMORY.md contents admitted by the runtime context assembly path",
    ),
    "Memory Housekeeping": (
        "memory_housekeeping",
        "static",
        "Memory housekeeping reminder admitted by the runtime context assembly path",
    ),
    "Memory Today Log": (
        "memory_today_log",
        "static",
        "Today's memory log admitted by the runtime context assembly path",
    ),
    "Memory Yesterday Log": (
        "memory_yesterday_log",
        "static",
        "Yesterday's memory log admitted by the runtime context assembly path",
    ),
    "Memory Reference Index": (
        "memory_reference_index",
        "static",
        "Memory reference index admitted by the runtime context assembly path",
    ),
    "Memory Loose Files": (
        "memory_loose_files",
        "static",
        "Loose memory-file index admitted by the runtime context assembly path",
    ),
    "Memory Nudge": (
        "memory_nudge",
        "static",
        "Memory-write reminder admitted by the runtime context assembly path",
    ),
    "Pinned Widget Context": (
        "pinned_widgets",
        "static",
        "Pinned widget snapshot admitted by the runtime context assembly path",
    ),
    "Workspace Files": (
        "channel_workspace",
        "static",
        "Channel workspace files admitted by the runtime context assembly path",
    ),
    "Context Profile": (
        "context_profile_note",
        "static",
        "Context-profile note admitted by the runtime context assembly path",
    ),
    "Skill Index": (
        "skill_index",
        "rag",
        "Skill working set/discovery index admitted by the runtime context assembly path",
    ),
    "Delegation Index": (
        "delegation_index",
        "rag",
        "Delegatable bot index admitted by the runtime context assembly path",
    ),
    "Spatial Canvas": (
        "spatial_canvas",
        "rag",
        "Spatial canvas awareness admitted by the runtime context assembly path",
    ),
    "Section Index": (
        "section_index",
        "rag",
        "Conversation section index admitted by the runtime context assembly path",
    ),
    "Conversation Sections": (
        "conversation_sections",
        "rag",
        "Retrieved conversation sections admitted by the runtime context assembly path",
    ),
    "Bot Knowledge Base": (
        "bot_knowledge_base",
        "rag",
        "Bot knowledge-base excerpts admitted by the runtime context assembly path",
    ),
    "Channel Knowledge Base": (
        "channel_index_segments",
        "rag",
        "Channel knowledge-base excerpts admitted by the runtime context assembly path",
    ),
    "Channel Index Segments": (
        "channel_index_segments",
        "rag",
        "Channel index-segment excerpts admitted by the runtime context assembly path",
    ),
    "Workspace Files (RAG)": (
        "workspace_context",
        "rag",
        "Workspace file excerpts admitted by the runtime context assembly path",
    ),
}

_BREAKDOWN_IGNORED_LABELS = {
    "Recent Conversation History Start",
    "Recent Conversation History End",
    "Compaction Summary",
}


def _slug_label(label: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in label).strip("_") or "system_message"


def _append_or_merge_category(
    categories: list[ContextCategory],
    *,
    key: str,
    label: str,
    chars: int,
    category: str,
    description: str,
) -> None:
    if chars == 0:
        return
    for existing in categories:
        if existing.key == key:
            existing.chars += chars
            return
    categories.append(ContextCategory(
        key=key,
        label=label,
        chars=chars,
        tokens_approx=0,
        percentage=0,
        category=category,
        description=description,
    ))


def _runtime_preview_categories(preview: Any) -> list[ContextCategory]:
    """Convert an assembled runtime preview into breakdown display rows.

    This is intentionally an adapter over ``assemble_for_preview``. It may
    classify and group messages for the dev panel, but it must not recompute
    whether prompt/RAG sections should exist.
    """
    from app.services.context_preview import extract_context_preview_blocks

    blocks, _ = extract_context_preview_blocks(preview, include_history=False)
    categories: list[ContextCategory] = []
    for idx, block in enumerate(blocks, start=1):
        label = block["label"]
        if label in _BREAKDOWN_IGNORED_LABELS:
            continue
        content = block["content"]
        key, category, description = _LABEL_TO_CATEGORY.get(
            label,
            (
                f"runtime_{_slug_label(label)}_{idx}",
                "static",
                "Runtime system message admitted by the context assembly path",
            ),
        )
        _append_or_merge_category(
            categories,
            key=key,
            label=label,
            chars=len(content),
            category=category,
            description=description,
        )

    tool_tokens = int((getattr(preview.budget, "breakdown", {}) or {}).get("tool_schemas") or 0)
    if tool_tokens > 0:
        _append_or_merge_category(
            categories,
            key="tool_schemas",
            label="Tool Schemas",
            chars=max(1, int(tool_tokens * 3.5)),
            category="rag",
            description="Tool schemas exposed by the runtime context assembly path",
        )
    return categories


def _preview_forecast_tokens(preview: Any, fallback_chars: int) -> int:
    consumed = getattr(preview.budget, "consumed_tokens", None)
    if consumed is None:
        consumed = getattr(preview.budget, "used_tokens", None)
    if consumed is not None:
        return int(consumed)
    return _chars_to_tokens(fallback_chars)


async def _load_breakdown_scope(
    channel_id: str,
    db: AsyncSession,
    *,
    session_id: str | Any | None,
) -> _BreakdownScope:
    from app.agent.bots import get_bot

    channel_pk = _uuid.UUID(channel_id) if isinstance(channel_id, str) else channel_id
    channel = await db.get(Channel, channel_pk)
    if not channel:
        raise ValueError(f"Channel not found: {channel_id}")

    session_id_str = str(session_id) if session_id is not None else None
    target_session_id = session_id_str or (
        str(channel.active_session_id) if channel.active_session_id else None
    )
    target_session_pk = _uuid.UUID(target_session_id) if target_session_id else None
    target_session = None
    if target_session_pk is not None:
        target_session = await db.get(Session, target_session_pk)
        if target_session is None:
            raise ValueError(f"Session not found: {target_session_id}")
        belongs_to_channel = (
            str(target_session.channel_id) == str(channel.id)
            or str(target_session.parent_channel_id) == str(channel.id)
        )
        if not belongs_to_channel:
            raise ValueError(f"Session {target_session_id} does not belong to channel {channel_id}")

    return _BreakdownScope(
        channel_id=str(channel_id),
        channel_pk=channel_pk,
        channel=channel,
        bot=get_bot(channel.bot_id),
        requested_session_id=session_id_str,
        session_id=target_session_id,
        session_pk=target_session_pk,
        session=target_session,
    )


async def _assemble_runtime_preview(scope: _BreakdownScope, db: AsyncSession) -> Any:
    from app.agent.context_assembly import assemble_for_preview

    # ``assemble_for_preview`` can perform expensive retrieval/rendering work.
    # End the read transaction opened while loading ``scope`` before that
    # non-DB work, otherwise Postgres can kill the idle transaction and the
    # next DB read in this request fails with "connection is closed".
    await db.commit()
    return await assemble_for_preview(
        scope.channel_pk,
        user_message="",
        session_id=_uuid.UUID(scope.requested_session_id) if scope.requested_session_id else None,
    )


async def _load_conversation_stats(
    db: AsyncSession,
    *,
    session_pk: _uuid.UUID | None,
    session: Session | None,
) -> _ConversationStats:
    if session_pk is None:
        return _ConversationStats()

    total_messages = (await db.execute(
        select(func.count()).select_from(Message)
        .where(Message.session_id == session_pk)
        .where(_not_compaction_run_clause)
    )).scalar_one()
    total_rows = (await db.execute(
        select(Message.content, Message.tool_calls)
        .where(Message.session_id == session_pk)
        .where(_not_compaction_run_clause)
    )).all()
    total_msg_chars = sum(_row_prompt_chars(row[0], row[1]) for row in total_rows)

    watermark_msg = None
    user_msgs_since_watermark: int | None = None
    if session and session.summary_message_id and session.summary:
        watermark_msg = await db.get(Message, session.summary_message_id)
        if watermark_msg:
            watermark_rows = (await db.execute(
                select(Message.content, Message.tool_calls).where(
                    Message.session_id == session_pk,
                    Message.created_at > watermark_msg.created_at,
                    _not_compaction_run_clause,
                )
            )).all()
            msgs_since_watermark = len(watermark_rows)
            chars_since_watermark = sum(_row_prompt_chars(row[0], row[1]) for row in watermark_rows)
            user_msgs_since_watermark = (await db.execute(
                select(func.count()).where(
                    Message.session_id == session_pk,
                    Message.created_at > watermark_msg.created_at,
                    Message.role == "user",
                    _not_compaction_run_clause,
                )
            )).scalar_one()
        else:
            msgs_since_watermark = total_messages
            chars_since_watermark = total_msg_chars
    else:
        msgs_since_watermark = total_messages
        chars_since_watermark = total_msg_chars

    return _ConversationStats(
        total_messages=total_messages,
        total_msg_chars=total_msg_chars,
        msgs_since_watermark=msgs_since_watermark,
        chars_since_watermark=chars_since_watermark,
        user_msgs_since_watermark=user_msgs_since_watermark,
        watermark_msg=watermark_msg,
    )


def _append_conversation_category(
    categories: list[ContextCategory],
    *,
    stats: _ConversationStats,
    session: Session | None,
) -> None:
    if stats.chars_since_watermark <= 0:
        return
    if session and session.summary:
        if stats.user_msgs_since_watermark is not None:
            desc = (
                f"{stats.user_msgs_since_watermark} user turns since last "
                f"compaction ({stats.msgs_since_watermark} messages total)"
            )
        else:
            desc = f"{stats.msgs_since_watermark} messages since last compaction"
    else:
        desc = f"{stats.total_messages} messages (no compaction yet)"
    categories.append(ContextCategory(
        key="conversation",
        label="Conversation History",
        chars=stats.chars_since_watermark,
        tokens_approx=0,
        percentage=0,
        category="conversation",
        description=desc,
    ))


async def _append_pruning_category(
    categories: list[ContextCategory],
    *,
    db: AsyncSession,
    scope: _BreakdownScope,
    stats: _ConversationStats,
) -> None:
    if scope.session_pk is None or stats.chars_since_watermark <= 0:
        return
    pruning_on = _resolve_setting(
        getattr(scope.channel, "context_pruning", None),
        getattr(scope.bot, "context_pruning", None),
        settings.CONTEXT_PRUNING_ENABLED,
        "context_pruning",
    ).value
    if not pruning_on:
        return

    min_len = settings.CONTEXT_PRUNING_MIN_LENGTH
    watermark_clause = (
        Message.created_at > stats.watermark_msg.created_at
        if scope.session and scope.session.summary_message_id and stats.watermark_msg
        else True
    )
    tool_count, tool_chars = (await db.execute(
        select(func.count(), func.coalesce(func.sum(func.length(Message.content)), 0)).where(
            Message.session_id == scope.session_pk,
            watermark_clause,
            _not_compaction_run_clause,
            Message.role == "tool",
            func.length(Message.content) >= min_len,
        )
    )).one()

    from app.agent.context_pruning import (
        build_pruned_tool_result_marker,
        estimate_tool_call_argument_pruning,
    )

    arg_rows = (await db.execute(
        select(Message.tool_calls).where(
            Message.session_id == scope.session_pk,
            watermark_clause,
            _not_compaction_run_clause,
            Message.role == "assistant",
            Message.tool_calls.is_not(None),
        )
    )).scalars().all()
    arg_count = 0
    arg_chars = 0
    arg_marker_chars = 0
    for tool_calls in arg_rows:
        arg_stats = estimate_tool_call_argument_pruning(tool_calls, min_len)
        arg_count += arg_stats["count"]
        arg_chars += arg_stats["chars"]
        arg_marker_chars += arg_stats["marker_chars"]
    if tool_count <= 0 and arg_count <= 0:
        return

    sample_marker = build_pruned_tool_result_marker(
        "generic_tool",
        10_000,
        record_id="00000000-0000-0000-0000-000000000000",
    )
    marker_chars = tool_count * len(sample_marker)
    est_savings = max(0, tool_chars - marker_chars) + max(0, arg_chars - arg_marker_chars)
    categories.append(ContextCategory(
        key="context_pruning",
        label="Context Pruning (savings)",
        chars=-est_savings,
        tokens_approx=0,
        percentage=0,
        category="conversation",
        description=(
            f"~{tool_count} tool results replaced with retrieval pointers"
            + (f"; ~{arg_count} tool-call argument payload(s) compacted" if arg_count else "")
        ),
    ))


async def _build_compaction_state(
    categories: list[ContextCategory],
    *,
    db: AsyncSession,
    scope: _BreakdownScope,
    stats: _ConversationStats,
) -> CompactionState:
    interval = _resolve_compaction_interval(scope.channel, scope.bot)
    keep_turns = _resolve_compaction_keep_turns(scope.channel, scope.bot)
    enabled = _resolve_compaction_enabled(scope.channel, scope.bot)

    summary_chars = 0
    has_summary = False
    if scope.session and scope.session.summary:
        has_summary = True
        summary_chars = len(scope.session.summary)
        categories.append(ContextCategory(
            key="compaction_summary",
            label="Compaction Summary",
            chars=summary_chars,
            tokens_approx=0,
            percentage=0,
            category="compaction",
            description="Summary of compacted conversation history",
        ))

    user_turns_since = await _count_user_turns_since_watermark(db, scope, stats)
    turns_until_next = max(0, interval - user_turns_since) if enabled else None
    return CompactionState(
        enabled=enabled,
        has_summary=has_summary,
        summary_chars=summary_chars,
        messages_since_watermark=stats.msgs_since_watermark,
        user_turns_since_watermark=user_turns_since,
        total_messages=stats.total_messages,
        compaction_interval=interval,
        compaction_keep_turns=keep_turns,
        turns_until_next=turns_until_next,
    )


async def _count_user_turns_since_watermark(
    db: AsyncSession,
    scope: _BreakdownScope,
    stats: _ConversationStats,
) -> int:
    if scope.session_pk is None:
        return 0
    clauses = [
        Message.session_id == scope.session_pk,
        Message.role == "user",
        _not_compaction_run_clause,
    ]
    if scope.session and scope.session.summary_message_id and stats.watermark_msg:
        clauses.append(Message.created_at > stats.watermark_msg.created_at)
    return (await db.execute(
        select(func.count()).select_from(Message).where(*clauses)
    )).scalar_one()


def _build_rerank_state(categories: list[ContextCategory]) -> RerankState:
    total_rag_chars = sum(c.chars for c in categories if c.category == "rag")
    rerank_model = settings.RAG_RERANK_MODEL or settings.COMPACTION_MODEL
    return RerankState(
        enabled=settings.RAG_RERANK_ENABLED,
        model=rerank_model,
        threshold_chars=settings.RAG_RERANK_THRESHOLD_CHARS,
        max_chunks=settings.RAG_RERANK_MAX_CHUNKS,
        total_rag_chars=total_rag_chars,
        would_rerank=settings.RAG_RERANK_ENABLED and total_rag_chars >= settings.RAG_RERANK_THRESHOLD_CHARS,
    )


def _effective_settings(channel: Channel, bot: Any) -> dict[str, EffectiveSetting]:
    return {
        "context_compaction": _resolve_setting(
            channel.context_compaction if channel.context_compaction != True else None,
            bot.context_compaction if not bot.context_compaction else None,
            True,
            "context_compaction",
        ),
        "compaction_interval": _resolve_setting(
            channel.compaction_interval,
            bot.compaction_interval,
            settings.COMPACTION_INTERVAL,
            "compaction_interval",
        ),
        "compaction_keep_turns": _resolve_setting(
            channel.compaction_keep_turns,
            bot.compaction_keep_turns,
            settings.COMPACTION_KEEP_TURNS,
            "compaction_keep_turns",
        ),
        "memory_enabled": EffectiveSetting(value=False, source="deprecated"),
        "max_iterations": _resolve_setting(
            channel.max_iterations,
            None,
            settings.AGENT_MAX_ITERATIONS,
            "max_iterations",
        ),
        "tool_retrieval": EffectiveSetting(value=bot.tool_retrieval, source="bot"),
        "tool_similarity_threshold": EffectiveSetting(
            value=bot.tool_similarity_threshold or settings.TOOL_RETRIEVAL_THRESHOLD,
            source="bot" if bot.tool_similarity_threshold else "global",
        ),
        "rag_reranking": EffectiveSetting(value=settings.RAG_RERANK_ENABLED, source="global"),
        "context_pruning": _resolve_setting(
            getattr(channel, "context_pruning", None),
            getattr(bot, "context_pruning", None),
            settings.CONTEXT_PRUNING_ENABLED,
            "context_pruning",
        ),
    }


def _finalize_category_metrics(categories: list[ContextCategory]) -> int:
    gross_chars = sum(c.chars for c in categories if c.chars > 0)
    for cat in categories:
        cat.tokens_approx = _chars_to_tokens(cat.chars)
        cat.percentage = round((cat.chars / gross_chars * 100) if gross_chars > 0 else 0, 1)
    return sum(c.chars for c in categories)


def _preview_policy(runtime_preview: Any) -> _PreviewPolicy:
    assembly = runtime_preview.assembly
    policy = getattr(assembly, "context_policy", {}) or {}
    return _PreviewPolicy(
        context_profile=getattr(assembly, "context_profile", None),
        context_origin=getattr(assembly, "context_origin", None),
        live_history_turns=policy.get("live_history_turns"),
        mandatory_static_injections=list(policy.get("mandatory_static_injections") or []),
        optional_static_injections=list(policy.get("optional_static_injections") or []),
    )


def _effective_model_and_provider(channel: Channel, bot: Any) -> tuple[str, str | None]:
    from app.agent.loop import _resolve_effective_provider

    model = channel.model_override or bot.model
    provider = _resolve_effective_provider(
        channel.model_override,
        getattr(channel, "model_provider_id_override", None),
        bot.model_provider_id,
    )
    return model, provider


async def _build_context_budget_info(
    *,
    db: AsyncSession,
    scope: _BreakdownScope,
    runtime_preview: Any,
    forecast_total_tokens: int,
    include_budget: bool,
) -> tuple[dict | None, int | None, _PreviewPolicy]:
    policy = _preview_policy(runtime_preview)
    if not (settings.CONTEXT_BUDGET_ENABLED and include_budget):
        return None, None, policy

    try:
        from app.agent.context_budget import get_model_context_window

        model, provider = _effective_model_and_provider(scope.channel, scope.bot)
        window = get_model_context_window(model, provider)
        reserve = int(window * settings.CONTEXT_BUDGET_RESERVE_RATIO)
        available = window - reserve
        latest = await fetch_latest_context_budget(
            scope.channel_id,
            db,
            session_id=scope.session_id,
        )
        policy = _merge_budget_policy(policy, latest)
        api_total_tokens = latest.get("consumed_tokens") if latest.get("source") == "api" else None
        return (
            {
                "context_profile": policy.context_profile,
                "context_origin": policy.context_origin,
                "live_history_turns": policy.live_history_turns,
                "mandatory_static_injections": policy.mandatory_static_injections,
                "optional_static_injections": policy.optional_static_injections,
                "estimate": {
                    "total_tokens": window,
                    "reserve_tokens": reserve,
                    "available_tokens": available,
                    "gross_prompt_tokens": forecast_total_tokens,
                    "current_prompt_tokens": forecast_total_tokens,
                    "cached_prompt_tokens": None,
                    "completion_tokens": None,
                    "utilization": round(forecast_total_tokens / available, 3) if available > 0 else 1.0,
                    "source": "estimate",
                },
                "usage": None if latest.get("source") == "none" else {
                    "total_tokens": latest.get("total_tokens"),
                    "gross_prompt_tokens": latest.get("gross_prompt_tokens"),
                    "current_prompt_tokens": latest.get("current_prompt_tokens"),
                    "cached_prompt_tokens": latest.get("cached_prompt_tokens"),
                    "completion_tokens": latest.get("completion_tokens"),
                    "utilization": latest.get("utilization"),
                    "source": latest.get("source"),
                },
            },
            api_total_tokens,
            policy,
        )
    except Exception:
        logger.debug("budget block compute failed", exc_info=True)
        return None, None, policy


def _merge_budget_policy(policy: _PreviewPolicy, latest: dict[str, Any]) -> _PreviewPolicy:
    return _PreviewPolicy(
        context_profile=latest.get("context_profile") or policy.context_profile,
        context_origin=latest.get("context_origin") or policy.context_origin,
        live_history_turns=(
            latest.get("live_history_turns")
            if latest.get("live_history_turns") is not None
            else policy.live_history_turns
        ),
        mandatory_static_injections=list(
            latest.get("mandatory_static_injections") or policy.mandatory_static_injections
        ),
        optional_static_injections=list(
            latest.get("optional_static_injections") or policy.optional_static_injections
        ),
    )


def context_breakdown_response(
    result: ContextBreakdownResult,
    *,
    mode: str,
    include_effective_settings: bool = False,
) -> dict[str, Any]:
    """Serialize context-breakdown responses for admin and public routers."""
    from dataclasses import asdict

    payload = {
        "channel_id": result.channel_id,
        "session_id": result.session_id,
        "bot_id": result.bot_id,
        "context_profile": result.context_profile,
        "context_origin": result.context_origin,
        "live_history_turns": result.live_history_turns,
        "mandatory_static_injections": result.mandatory_static_injections,
        "optional_static_injections": result.optional_static_injections,
        "categories": [asdict(c) for c in result.categories],
        "total_chars": result.total_chars,
        "total_tokens_approx": result.total_tokens_approx,
        "compaction": asdict(result.compaction),
        "reranking": asdict(result.reranking),
        "context_budget": result.context_budget,
        "mode": mode,
        "disclaimer": result.disclaimer,
    }
    if include_effective_settings:
        payload["effective_settings"] = {
            key: {"value": value.value, "source": value.source}
            for key, value in result.effective_settings.items()
        }
    return payload


async def compute_context_breakdown(
    channel_id: str,
    db: AsyncSession,
    *,
    mode: str = "last_turn",
    session_id: str | Any | None = None,
    include_budget: bool = True,
) -> ContextBreakdownResult:
    """Compute the dev-panel context breakdown for a channel.

    ``mode`` controls how the totals reconcile with the chat-header value:

    - ``last_turn`` (default) — categories describe the channel's *current*
      configuration (what would be assembled now), but the headline
      ``total_tokens_approx`` is overridden with the API-reported
      ``prompt_tokens`` from the most recent ``token_usage`` trace event.
      This guarantees the dev panel total matches the chat header.
    - ``next_turn`` — same categories, but the headline total comes from the
      live tokenizer (``count_text_tokens_sync`` against the assembled char
      count). May differ from the chat header by design.
    """
    session_id_str = str(session_id) if session_id is not None else None
    cache_key = (str(channel_id), mode, session_id_str, "budget" if include_budget else "nobudget")
    cached = _breakdown_cache.get(cache_key)
    if cached is not None:
        expiry, payload = cached
        if expiry > time.monotonic():
            return payload
        _breakdown_cache.pop(cache_key, None)

    scope = await _load_breakdown_scope(channel_id, db, session_id=session_id)
    runtime_preview = await _assemble_runtime_preview(scope, db)
    categories = _runtime_preview_categories(runtime_preview)
    stats = await _load_conversation_stats(
        db,
        session_pk=scope.session_pk,
        session=scope.session,
    )
    _append_conversation_category(categories, stats=stats, session=scope.session)
    await _append_pruning_category(categories, db=db, scope=scope, stats=stats)
    compaction = await _build_compaction_state(categories, db=db, scope=scope, stats=stats)
    reranking = _build_rerank_state(categories)
    effective_settings = _effective_settings(scope.channel, scope.bot)
    total_chars = _finalize_category_metrics(categories)
    forecast_total_tokens = _preview_forecast_tokens(runtime_preview, total_chars)
    budget_info, api_total_tokens, policy = await _build_context_budget_info(
        db=db,
        scope=scope,
        runtime_preview=runtime_preview,
        forecast_total_tokens=forecast_total_tokens,
        include_budget=include_budget,
    )

    # Headline total: API ground truth in last_turn mode (when available),
    # forecast otherwise.
    if mode == "last_turn" and api_total_tokens is not None:
        total_tokens = api_total_tokens
    else:
        total_tokens = forecast_total_tokens

    result = ContextBreakdownResult(
        channel_id=scope.channel_id,
        session_id=scope.session_id,
        bot_id=scope.channel.bot_id,
        categories=categories,
        total_chars=total_chars,
        total_tokens_approx=total_tokens,
        compaction=compaction,
        reranking=reranking,
        effective_settings=effective_settings,
        context_profile=policy.context_profile,
        context_origin=policy.context_origin,
        live_history_turns=policy.live_history_turns,
        mandatory_static_injections=policy.mandatory_static_injections,
        optional_static_injections=policy.optional_static_injections,
        context_budget=budget_info,
        disclaimer="RAG components are heuristic estimates. Actual values vary per query based on semantic similarity scores.",
    )
    _breakdown_cache[cache_key] = (time.monotonic() + _BREAKDOWN_CACHE_TTL, result)
    return result


def _resolve_compaction_enabled(channel: Channel, bot) -> bool:
    if hasattr(channel, "context_compaction") and channel.context_compaction is not None:
        return channel.context_compaction
    return bot.context_compaction


def _resolve_compaction_interval(channel: Channel, bot) -> int:
    if hasattr(channel, "compaction_interval") and channel.compaction_interval is not None:
        return channel.compaction_interval
    if bot.compaction_interval is not None:
        return bot.compaction_interval
    return settings.COMPACTION_INTERVAL


def _resolve_compaction_keep_turns(channel: Channel, bot) -> int:
    if hasattr(channel, "compaction_keep_turns") and channel.compaction_keep_turns is not None:
        return channel.compaction_keep_turns
    if bot.compaction_keep_turns is not None:
        return bot.compaction_keep_turns
    return settings.COMPACTION_KEEP_TURNS
