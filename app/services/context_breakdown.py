"""Compute a detailed context breakdown for a channel's active session.

Used by the admin UI to show what goes into each agent turn.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import (
    Channel,
    ConversationSection,
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
_breakdown_cache: dict[tuple[str, str], tuple[float, "ContextBreakdownResult"]] = {}


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
    2. Fall back to the most recent ``context_injection_summary``'s
       ``context_budget`` dict (pre-call estimate) when no turn has been
       sent yet, or when the model's response didn't include usage.
    3. Sentinel with null fields when no turn has been recorded.

    Shared by ``GET /admin/channels/{id}/context-budget`` and
    ``GET /channels/{id}/context-budget`` so the two cannot drift.
    """
    # Latest pre-call estimate carries `total_tokens` (the model's window)
    # which the API usage event doesn't, so we read both and merge.
    inj_query = (
        select(TraceEvent.data)
        .join(Session, TraceEvent.session_id == Session.id)
        .where(
            Session.channel_id == channel_id,
            TraceEvent.event_type == "context_injection_summary",
        )
    )
    if session_id is not None:
        inj_query = inj_query.where(TraceEvent.session_id == session_id)
    inj_row = await db.execute(
        inj_query.order_by(TraceEvent.created_at.desc()).limit(1)
    )
    inj_data = inj_row.scalar_one_or_none()
    inj_budget = (inj_data or {}).get("context_budget") or {}
    context_profile = (inj_data or {}).get("context_profile")
    context_origin = (inj_data or {}).get("context_origin")
    context_policy = (inj_data or {}).get("context_policy") or {}
    live_history_turns = context_policy.get("live_history_turns")
    mandatory_static_injections = context_policy.get("mandatory_static_injections") or []
    optional_static_injections = context_policy.get("optional_static_injections") or []
    total_tokens = inj_budget.get("total_tokens")
    est_consumed = inj_budget.get("consumed_tokens")

    usage_query = (
        select(TraceEvent.data)
        .join(Session, TraceEvent.session_id == Session.id)
        .where(
            Session.channel_id == channel_id,
            TraceEvent.event_type == "token_usage",
        )
    )
    if session_id is not None:
        usage_query = usage_query.where(TraceEvent.session_id == session_id)
    usage_row = await db.execute(
        usage_query.order_by(TraceEvent.created_at.desc()).limit(1)
    )
    usage_data = usage_row.scalar_one_or_none() or {}
    api_prompt_tokens = usage_data.get("gross_prompt_tokens")
    if api_prompt_tokens is None:
        api_prompt_tokens = usage_data.get("prompt_tokens")
    cached_prompt_tokens = usage_data.get("cached_prompt_tokens")
    if cached_prompt_tokens is None:
        cached_prompt_tokens = usage_data.get("cached_tokens")
    current_prompt_tokens = usage_data.get("current_prompt_tokens")
    if current_prompt_tokens is None and api_prompt_tokens is not None:
        if cached_prompt_tokens is None:
            current_prompt_tokens = api_prompt_tokens
        else:
            current_prompt_tokens = max(0, api_prompt_tokens - cached_prompt_tokens)
    completion_tokens = usage_data.get("completion_tokens")

    if api_prompt_tokens is None and est_consumed is None:
        return {
            "utilization": None,
            "consumed_tokens": None,
            "total_tokens": None,
            "gross_prompt_tokens": None,
            "current_prompt_tokens": None,
            "cached_prompt_tokens": None,
            "completion_tokens": None,
            "context_profile": context_profile,
            "context_origin": context_origin,
            "live_history_turns": live_history_turns,
            "mandatory_static_injections": mandatory_static_injections,
            "optional_static_injections": optional_static_injections,
            "source": "none",
        }

    consumed = api_prompt_tokens if api_prompt_tokens is not None else est_consumed
    utilization = None
    if total_tokens and consumed is not None and total_tokens > 0:
        utilization = round(consumed / total_tokens, 3)
    elif api_prompt_tokens is None:
        # No API number AND no total — preserve the estimator's utilization
        utilization = inj_budget.get("utilization")

    return {
        "utilization": utilization,
        "consumed_tokens": consumed,
        "total_tokens": total_tokens,
        "gross_prompt_tokens": consumed,
        "current_prompt_tokens": current_prompt_tokens if api_prompt_tokens is not None else est_consumed,
        "cached_prompt_tokens": cached_prompt_tokens if api_prompt_tokens is not None else None,
        "completion_tokens": completion_tokens if api_prompt_tokens is not None else None,
        "context_profile": context_profile,
        "context_origin": context_origin,
        "live_history_turns": live_history_turns,
        "mandatory_static_injections": mandatory_static_injections,
        "optional_static_injections": optional_static_injections,
        "source": "api" if api_prompt_tokens is not None else "estimate",
    }


def _resolve_setting(channel_val, bot_val, global_val, channel_attr: str) -> EffectiveSetting:
    """Resolve a setting with channel > bot > global priority."""
    if channel_val is not None:
        return EffectiveSetting(value=channel_val, source="channel")
    if bot_val is not None:
        return EffectiveSetting(value=bot_val, source="bot")
    return EffectiveSetting(value=global_val, source="global")


async def compute_context_breakdown(
    channel_id: str,
    db: AsyncSession,
    *,
    mode: str = "last_turn",
    session_id: str | Any | None = None,
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
    cache_key = (str(channel_id), mode, session_id_str)
    cached = _breakdown_cache.get(cache_key)
    if cached is not None:
        expiry, payload = cached
        if expiry > time.monotonic():
            return payload
        _breakdown_cache.pop(cache_key, None)

    from app.agent.base_prompt import render_base_prompt
    from app.agent.bots import get_bot
    from app.agent.persona import get_persona

    import uuid as _uuid
    _ch_pk = _uuid.UUID(channel_id) if isinstance(channel_id, str) else channel_id
    channel = await db.get(Channel, _ch_pk)
    if not channel:
        raise ValueError(f"Channel not found: {channel_id}")

    bot = get_bot(channel.bot_id)
    categories: list[ContextCategory] = []

    # -----------------------------------------------------------------------
    # 1. Static context
    # -----------------------------------------------------------------------

    # Global base prompt (server-level, prepended before everything)
    from app.config import settings as _settings
    if _settings.GLOBAL_BASE_PROMPT:
        categories.append(ContextCategory(
            key="global_base_prompt", label="Global Base Prompt", chars=len(_settings.GLOBAL_BASE_PROMPT),
            tokens_approx=0, percentage=0, category="static",
            description="Server-wide prompt prepended before all other base/system prompts",
        ))

    # Base prompt
    base = render_base_prompt(bot)
    if base:
        categories.append(ContextCategory(
            key="base_prompt", label="Base Prompt", chars=len(base),
            tokens_approx=0, percentage=0, category="static",
            description="Universal platform prompt prepended to every bot",
        ))

    # Bot system prompt
    sp_chars = len(bot.system_prompt.strip())
    if sp_chars:
        categories.append(ContextCategory(
            key="system_prompt", label="System Prompt", chars=sp_chars,
            tokens_approx=0, percentage=0, category="static",
            description="Bot-specific system prompt",
        ))

    # Memory guidelines — DEPRECATED (DB memory no longer in use)

    # Persona
    if bot.persona:
        persona_text = await get_persona(bot.id)
        if persona_text:
            p_chars = len("[PERSONA]\n") + len(persona_text)
            categories.append(ContextCategory(
                key="persona", label="Persona", chars=p_chars,
                tokens_approx=0, percentage=0, category="static",
                description="Bot persona layer injected as system message",
            ))

    # Workspace-files memory scheme: MEMORY.md + daily logs (injected every turn from disk)
    if bot.memory_scheme == "workspace-files":
        import os as _bd_os
        from datetime import date as _bd_date
        from app.services.memory_scheme import get_memory_root, get_memory_rel_path
        from app.services.workspace import workspace_service
        try:
            _bd_ws_root = workspace_service.get_workspace_root(bot.id, bot)
            _bd_mem_root = get_memory_root(bot, ws_root=_bd_ws_root)
            _bd_mem_rel = get_memory_rel_path(bot)

            # MEMORY.md
            _bd_mem_md = _bd_os.path.join(_bd_mem_root, "MEMORY.md")
            if _bd_os.path.isfile(_bd_mem_md):
                _bd_md_chars = len(Path(_bd_mem_md).read_text())
                if _bd_md_chars > 0:
                    categories.append(ContextCategory(
                        key="memory_md", label="MEMORY.md", chars=_bd_md_chars,
                        tokens_approx=0, percentage=0, category="static",
                        description=f"Curated stable facts ({_bd_mem_rel}/MEMORY.md) — injected every turn",
                    ))

            # Today's daily log
            _bd_today = _bd_date.today().isoformat()
            _bd_today_path = _bd_os.path.join(_bd_mem_root, "logs", f"{_bd_today}.md")
            if _bd_os.path.isfile(_bd_today_path):
                _bd_today_chars = len(Path(_bd_today_path).read_text())
                if _bd_today_chars > 0:
                    categories.append(ContextCategory(
                        key="memory_today_log", label="Today's Log", chars=_bd_today_chars,
                        tokens_approx=0, percentage=0, category="static",
                        description=f"Daily log ({_bd_mem_rel}/logs/{_bd_today}.md) — injected every turn",
                    ))

            # Yesterday's daily log
            _bd_yest = (_bd_date.today() - __import__("datetime").timedelta(days=1)).isoformat()
            _bd_yest_path = _bd_os.path.join(_bd_mem_root, "logs", f"{_bd_yest}.md")
            if _bd_os.path.isfile(_bd_yest_path):
                _bd_yest_chars = len(Path(_bd_yest_path).read_text())
                if _bd_yest_chars > 0:
                    categories.append(ContextCategory(
                        key="memory_yesterday_log", label="Yesterday's Log", chars=_bd_yest_chars,
                        tokens_approx=0, percentage=0, category="static",
                        description=f"Daily log ({_bd_mem_rel}/logs/{_bd_yest}.md) — injected every turn",
                    ))

            # Reference file count
            _bd_ref_dir = _bd_os.path.join(_bd_mem_root, "reference")
            if _bd_os.path.isdir(_bd_ref_dir):
                _bd_ref_files = [f for f in _bd_os.listdir(_bd_ref_dir) if f.endswith(".md")]
                if _bd_ref_files:
                    categories.append(ContextCategory(
                        key="memory_reference_index", label="Reference Index", chars=len(_bd_ref_files) * 40,
                        tokens_approx=0, percentage=0, category="static",
                        description=f"{len(_bd_ref_files)} reference file(s) listed (names only; read via get_memory_file)",
                    ))
        except Exception:
            logger.debug("Could not compute memory scheme breakdown for bot %s", bot.id, exc_info=True)

    # Datetime
    categories.append(ContextCategory(
        key="datetime", label="Date/Time", chars=72,
        tokens_approx=0, percentage=0, category="static",
        description="Current timestamp injected every turn",
    ))

    # -----------------------------------------------------------------------
    # 2. Per-turn RAG (heuristic estimates)
    # -----------------------------------------------------------------------

    # Skills (all on-demand)
    if bot.skills:
        from app.db.models import Skill as SkillRow
        ids = [s.id for s in bot.skills]
        rows = (await db.execute(
            select(SkillRow.id, SkillRow.name).where(SkillRow.id.in_(ids))
        )).all()
        if rows:
            hdr = len("Available skills (use get_skill to retrieve full content):\n")
            body = sum(len(f"- {r.id}: {r.name}\n") for r in rows)
            categories.append(ContextCategory(
                key="skills_index", label="Skill Index", chars=hdr + body,
                tokens_approx=0, percentage=0, category="rag",
                description=f"{len(rows)} skill(s) listed by name",
            ))

    # Tool schemas (rough estimate)
    tool_count = len(bot.local_tools) + len(bot.client_tools)
    if tool_count > 0 or bot.mcp_servers:
        avg_schema = 400
        if bot.tool_retrieval:
            top_k = settings.TOOL_RETRIEVAL_TOP_K
            est_tools = min(top_k, tool_count) + len(bot.pinned_tools)
            categories.append(ContextCategory(
                key="tool_schemas", label="Tool Schemas", chars=est_tools * avg_schema,
                tokens_approx=0, percentage=0, category="rag",
                description=f"~{est_tools} tool schemas (RAG + pinned); varies by query",
            ))
            unretrieved = max(0, tool_count - est_tools)
            if unretrieved:
                idx_chars = len("Available tools (not yet loaded):\n") + unretrieved * 105
                categories.append(ContextCategory(
                    key="tool_index", label="Tool Index", chars=idx_chars,
                    tokens_approx=0, percentage=0, category="rag",
                    description=f"~{unretrieved} compact entries for non-loaded tools",
                ))
        else:
            categories.append(ContextCategory(
                key="tool_schemas", label="Tool Schemas (all)", chars=tool_count * avg_schema,
                tokens_approx=0, percentage=0, category="rag",
                description=f"{tool_count} tool schemas (RAG disabled, all sent every turn)",
            ))

    # Delegation index
    if bot.delegate_bots:
        dele_chars = len("Available sub-agents:\n") + len(bot.delegate_bots) * 80
        categories.append(ContextCategory(
            key="delegation_index", label="Delegation Index", chars=dele_chars,
            tokens_approx=0, percentage=0, category="rag",
            description=f"{len(bot.delegate_bots)} delegatable bot(s)",
        ))

    # Channel workspace active files (injected every turn as static context)
    if channel is not None:
        try:
            import os as _cw_os
            from app.services.channel_workspace import get_channel_workspace_root
            _cw_root = get_channel_workspace_root(str(channel_id), bot)
            _cw_active_chars = 0
            _cw_active_count = 0
            if _cw_os.path.isdir(_cw_root):
                for _cw_entry in sorted(_cw_os.scandir(_cw_root), key=lambda e: e.name):
                    if _cw_entry.is_file() and _cw_entry.name.endswith(".md"):
                        try:
                            _cw_content = Path(_cw_entry.path).read_text()
                            if _cw_content.strip():
                                _cw_active_chars += len(_cw_content)
                                _cw_active_count += 1
                        except Exception:
                            pass
            if _cw_active_chars > 0:
                # Cap at the same budget used in context_assembly
                _CW_BUDGET = 50_000
                _cw_injected = min(_cw_active_chars, _CW_BUDGET)
                categories.append(ContextCategory(
                    key="channel_workspace_files", label="Channel Workspace Files",
                    chars=_cw_injected,
                    tokens_approx=0, percentage=0, category="static",
                    description=f"{_cw_active_count} active .md file(s) injected every turn ({_cw_active_chars:,} chars total"
                                + (f", capped to {_CW_BUDGET:,})" if _cw_active_chars > _CW_BUDGET else ")"),
                ))
        except Exception:
            logger.debug("Could not compute channel workspace files for channel %s", channel_id, exc_info=True)

    # Workspace / filesystem RAG context
    if bot.workspace.enabled and bot.workspace.indexing.enabled:
        est_ws = int(settings.FS_INDEX_TOP_K * settings.FS_INDEX_CHUNK_WINDOW * 0.3)
        categories.append(ContextCategory(
            key="workspace_context", label="Workspace Files (RAG)", chars=est_ws,
            tokens_approx=0, percentage=0, category="rag",
            description="Workspace file chunks retrieved by semantic search; varies by query",
        ))

    # Section index (file mode)
    from app.services.compaction import _get_history_mode
    _hist_mode = _get_history_mode(bot, channel)
    if _hist_mode == "file":
        _si_count = getattr(channel, "section_index_count", None)
        _si_count = _si_count if _si_count is not None else settings.SECTION_INDEX_COUNT
        if _si_count > 0:
            _si_verbosity = getattr(channel, "section_index_verbosity", None) or settings.SECTION_INDEX_VERBOSITY
            _actual_sections = (await db.execute(
                select(func.count()).select_from(ConversationSection)
                .where(ConversationSection.channel_id == channel_id)
            )).scalar_one()
            _shown = min(_si_count, _actual_sections)
            if _shown > 0:
                # Estimate chars per section by verbosity
                _per_section = {"compact": 60, "standard": 120, "detailed": 160}.get(_si_verbosity, 120)
                _si_chars = 100 + _shown * _per_section  # header + entries
                categories.append(ContextCategory(
                    key="section_index", label="Section Index", chars=_si_chars,
                    tokens_approx=0, percentage=0, category="rag",
                    description=f"{_shown} recent section(s) in {_si_verbosity} mode (file history)",
                ))

    target_session_id = session_id_str or (str(channel.active_session_id) if channel.active_session_id else None)
    target_session_pk = _uuid.UUID(target_session_id) if target_session_id else None
    target_session = None
    if target_session_pk is not None:
        target_session = await db.get(Session, target_session_pk)
        if target_session is None:
            raise ValueError(f"Session not found: {target_session_id}")
        if str(target_session.channel_id) != str(channel.id):
            raise ValueError(f"Session {target_session_id} does not belong to channel {channel_id}")

    # -----------------------------------------------------------------------
    # 3. Conversation history (live from DB)
    # -----------------------------------------------------------------------
    total_messages = 0
    total_msg_chars = 0
    msgs_since_watermark = 0
    chars_since_watermark = 0
    watermark_msg = None

    if target_session_pk:
        session = target_session

        # Total messages
        total_messages = (await db.execute(
            select(func.count()).select_from(Message)
            .where(Message.session_id == target_session_pk)
        )).scalar_one()

        total_msg_chars = (await db.execute(
            select(func.coalesce(func.sum(func.length(Message.content)), 0))
            .where(Message.session_id == target_session_pk)
        )).scalar_one()

        # Messages since watermark
        if session and session.summary_message_id and session.summary:
            watermark_msg = await db.get(Message, session.summary_message_id)
            if watermark_msg:
                result = await db.execute(
                    select(func.count(), func.coalesce(func.sum(func.length(Message.content)), 0))
                    .where(
                        Message.session_id == target_session_pk,
                        Message.created_at > watermark_msg.created_at,
                    )
                )
                row = result.one()
                msgs_since_watermark = row[0]
                chars_since_watermark = row[1]
                # Count user messages only (matches compaction trigger logic)
                user_msgs_since_watermark = (await db.execute(
                    select(func.count())
                    .where(
                        Message.session_id == target_session_pk,
                        Message.created_at > watermark_msg.created_at,
                        Message.role == "user",
                    )
                )).scalar_one()
            else:
                msgs_since_watermark = total_messages
                chars_since_watermark = total_msg_chars
                user_msgs_since_watermark = None
        else:
            msgs_since_watermark = total_messages
            chars_since_watermark = total_msg_chars
            user_msgs_since_watermark = None

        # Add conversation history category
        if chars_since_watermark > 0:
            # Show user turn count since compaction triggers on user messages
            if session and session.summary:
                if user_msgs_since_watermark is not None:
                    desc = f"{user_msgs_since_watermark} user turns since last compaction ({msgs_since_watermark} messages total)"
                else:
                    desc = f"{msgs_since_watermark} messages since last compaction"
            else:
                desc = f"{total_messages} messages (no compaction yet)"
            categories.append(ContextCategory(
                key="conversation", label="Conversation History",
                chars=chars_since_watermark,
                tokens_approx=0, percentage=0, category="conversation",
                description=desc,
            ))

        # Context pruning savings estimate.
        # Tool results with a stored record_id are replaced with retrieval
        # pointers regardless of turn position.  Old results without a
        # record_id are pruned only in turns outside the keep_turns window.
        # Rather than re-implementing the full turn-splitting logic here,
        # we count all tool messages >= min_length as eligible — this is
        # accurate for new messages (all have record IDs) and slightly
        # overestimates for legacy messages in kept turns.
        _pruning_on = _resolve_setting(
            getattr(channel, "context_pruning", None),
            getattr(bot, "context_pruning", None),
            settings.CONTEXT_PRUNING_ENABLED, "context_pruning",
        ).value
        if _pruning_on and chars_since_watermark > 0:
            _min_len = settings.CONTEXT_PRUNING_MIN_LENGTH
            _watermark_clause = Message.created_at > watermark_msg.created_at if (session and session.summary_message_id and watermark_msg) else True

            _tool_msg_stats = (await db.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(func.length(Message.content)), 0),
                ).where(
                    Message.session_id == target_session_pk,
                    _watermark_clause,
                    Message.role == "tool",
                    func.length(Message.content) >= _min_len,
                )
            )).one()
            _tool_count, _tool_chars = _tool_msg_stats
            if _tool_count > 0:
                # Compute marker length from a representative sample so the
                # estimate stays in sync if the marker format in
                # context_pruning.py changes.  New messages get retrieval
                # pointers (~140 chars); legacy messages get dead markers
                # (~45 chars).  We use the retrieval pointer length as the
                # conservative (smaller) savings estimate.
                _sample_marker = (
                    f"[Tool output from generic_tool (10,000 chars)"
                    f" — use read_conversation_history(section='tool:00000000-0000-0000-0000-000000000000')"
                    f" to retrieve]"
                )
                _marker_chars = _tool_count * len(_sample_marker)
                _est_savings = max(0, _tool_chars - _marker_chars)
                categories.append(ContextCategory(
                    key="context_pruning", label="Context Pruning (savings)",
                    chars=-_est_savings,
                    tokens_approx=0, percentage=0, category="conversation",
                    description=f"~{_tool_count} tool results replaced with retrieval pointers",
                ))

    # -----------------------------------------------------------------------
    # 4. Compaction state
    # -----------------------------------------------------------------------
    compaction_interval = _resolve_compaction_interval(channel, bot)
    compaction_keep_turns = _resolve_compaction_keep_turns(channel, bot)
    compaction_enabled = _resolve_compaction_enabled(channel, bot)

    summary_chars = 0
    has_summary = False
    if target_session_pk:
        session = target_session
        if session and session.summary:
            has_summary = True
            summary_chars = len(session.summary)
            categories.append(ContextCategory(
                key="compaction_summary", label="Compaction Summary",
                chars=summary_chars,
                tokens_approx=0, percentage=0, category="compaction",
                description="Summary of compacted conversation history",
            ))

    # Count user turns since watermark for "turns until next"
    user_turns_since = 0
    if target_session_pk:
        session = target_session
        if session and session.summary_message_id:
            if watermark_msg:
                user_turns_since = (await db.execute(
                    select(func.count()).select_from(Message)
                    .where(
                        Message.session_id == target_session_pk,
                        Message.created_at > watermark_msg.created_at,
                        Message.role == "user",
                    )
                )).scalar_one()
            else:
                user_turns_since = (await db.execute(
                    select(func.count()).select_from(Message)
                    .where(
                        Message.session_id == target_session_pk,
                        Message.role == "user",
                    )
                )).scalar_one()
        else:
            user_turns_since = (await db.execute(
                select(func.count()).select_from(Message)
                .where(
                    Message.session_id == target_session_pk,
                    Message.role == "user",
                )
            )).scalar_one()

    turns_until_next = max(0, compaction_interval - user_turns_since) if compaction_enabled else None

    compaction = CompactionState(
        enabled=compaction_enabled,
        has_summary=has_summary,
        summary_chars=summary_chars,
        messages_since_watermark=msgs_since_watermark,
        total_messages=total_messages,
        compaction_interval=compaction_interval,
        compaction_keep_turns=compaction_keep_turns,
        turns_until_next=turns_until_next,
    )

    # -----------------------------------------------------------------------
    # 5. RAG re-ranking state
    # -----------------------------------------------------------------------
    total_rag_chars = sum(c.chars for c in categories if c.category == "rag")
    rerank_model = settings.RAG_RERANK_MODEL or settings.COMPACTION_MODEL
    reranking = RerankState(
        enabled=settings.RAG_RERANK_ENABLED,
        model=rerank_model,
        threshold_chars=settings.RAG_RERANK_THRESHOLD_CHARS,
        max_chunks=settings.RAG_RERANK_MAX_CHUNKS,
        total_rag_chars=total_rag_chars,
        would_rerank=settings.RAG_RERANK_ENABLED and total_rag_chars >= settings.RAG_RERANK_THRESHOLD_CHARS,
    )

    # -----------------------------------------------------------------------
    # 6. Effective settings
    # -----------------------------------------------------------------------
    effective_settings = {
        "context_compaction": _resolve_setting(
            channel.context_compaction if channel.context_compaction != True else None,
            bot.context_compaction if not bot.context_compaction else None,
            True, "context_compaction",
        ),
        "compaction_interval": _resolve_setting(
            channel.compaction_interval, bot.compaction_interval,
            settings.COMPACTION_INTERVAL, "compaction_interval",
        ),
        "compaction_keep_turns": _resolve_setting(
            channel.compaction_keep_turns, bot.compaction_keep_turns,
            settings.COMPACTION_KEEP_TURNS, "compaction_keep_turns",
        ),
        "memory_enabled": EffectiveSetting(value=False, source="deprecated"),
        "max_iterations": _resolve_setting(
            channel.max_iterations, None, settings.AGENT_MAX_ITERATIONS, "max_iterations",
        ),
        "tool_retrieval": EffectiveSetting(value=bot.tool_retrieval, source="bot"),
        "tool_similarity_threshold": EffectiveSetting(
            value=bot.tool_similarity_threshold or settings.TOOL_RETRIEVAL_THRESHOLD,
            source="bot" if bot.tool_similarity_threshold else "global",
        ),
        "base_prompt": EffectiveSetting(value=bot.base_prompt, source="bot"),
        "rag_reranking": EffectiveSetting(value=settings.RAG_RERANK_ENABLED, source="global"),
        "context_pruning": _resolve_setting(
            getattr(channel, "context_pruning", None),
            getattr(bot, "context_pruning", None),
            settings.CONTEXT_PRUNING_ENABLED, "context_pruning",
        ),
    }

    # -----------------------------------------------------------------------
    # Finalize: compute totals and percentages
    # -----------------------------------------------------------------------
    total_chars = sum(c.chars for c in categories)
    # Use gross (positive-only) chars as denominator so percentages are intuitive:
    # positive components sum to ~100%, pruning savings shows as a negative percentage.
    gross_chars = sum(c.chars for c in categories if c.chars > 0)

    # Resolve effective model+provider for the budget block. Per-category
    # tokens use the cheap chars/3.5 estimate — running tiktoken against
    # `"x" * chars` is both bogus (chars are placeholders, not real text)
    # and expensive on large categories. The headline total still comes from
    # the real API count in last_turn mode, which is what users actually see.
    from app.agent.loop import _resolve_effective_provider
    _model = channel.model_override or bot.model
    _provider = _resolve_effective_provider(
        channel.model_override,
        getattr(channel, "model_provider_id_override", None),
        bot.model_provider_id,
    )

    for cat in categories:
        cat.tokens_approx = _chars_to_tokens(cat.chars)
        cat.percentage = round((cat.chars / gross_chars * 100) if gross_chars > 0 else 0, 1)

    forecast_total_tokens = _chars_to_tokens(total_chars)

    # Context budget info (if enabled)
    _budget_info = None
    api_total_tokens: int | None = None
    context_profile: str | None = None
    context_origin: str | None = None
    live_history_turns: int | None = None
    mandatory_static_injections: list[str] = []
    optional_static_injections: list[str] = []
    if settings.CONTEXT_BUDGET_ENABLED:
        try:
            from app.agent.context_budget import get_model_context_window
            _window = get_model_context_window(_model, _provider)
            _reserve = int(_window * settings.CONTEXT_BUDGET_RESERVE_RATIO)
            _available = _window - _reserve
            # Pull the API-reported prompt_tokens for last_turn alignment.
            _latest = await fetch_latest_context_budget(channel_id, db, session_id=target_session_id)
            context_profile = _latest.get("context_profile")
            context_origin = _latest.get("context_origin")
            live_history_turns = _latest.get("live_history_turns")
            mandatory_static_injections = list(_latest.get("mandatory_static_injections") or [])
            optional_static_injections = list(_latest.get("optional_static_injections") or [])
            api_total_tokens = _latest.get("consumed_tokens") if _latest.get("source") == "api" else None
            _budget_info = {
                "context_profile": context_profile,
                "context_origin": context_origin,
                "live_history_turns": live_history_turns,
                "mandatory_static_injections": mandatory_static_injections,
                "optional_static_injections": optional_static_injections,
                "estimate": {
                    "total_tokens": _window,
                    "reserve_tokens": _reserve,
                    "available_tokens": _available,
                    "gross_prompt_tokens": forecast_total_tokens,
                    "current_prompt_tokens": forecast_total_tokens,
                    "cached_prompt_tokens": None,
                    "completion_tokens": None,
                    "utilization": round(forecast_total_tokens / _available, 3) if _available > 0 else 1.0,
                    "source": "estimate",
                },
                "usage": None if _latest.get("source") == "none" else {
                    "total_tokens": _latest.get("total_tokens"),
                    "gross_prompt_tokens": _latest.get("gross_prompt_tokens"),
                    "current_prompt_tokens": _latest.get("current_prompt_tokens"),
                    "cached_prompt_tokens": _latest.get("cached_prompt_tokens"),
                    "completion_tokens": _latest.get("completion_tokens"),
                    "utilization": _latest.get("utilization"),
                    "source": _latest.get("source"),
                },
            }
        except Exception:
            logger.debug("budget block compute failed", exc_info=True)

    # Headline total: API ground truth in last_turn mode (when available),
    # forecast otherwise.
    if mode == "last_turn" and api_total_tokens is not None:
        total_tokens = api_total_tokens
    else:
        total_tokens = forecast_total_tokens

    result = ContextBreakdownResult(
        channel_id=str(channel_id),
        session_id=target_session_id,
        bot_id=channel.bot_id,
        categories=categories,
        total_chars=total_chars,
        total_tokens_approx=total_tokens,
        compaction=compaction,
        reranking=reranking,
        effective_settings=effective_settings,
        context_profile=context_profile,
        context_origin=context_origin,
        live_history_turns=live_history_turns,
        mandatory_static_injections=mandatory_static_injections,
        optional_static_injections=optional_static_injections,
        context_budget=_budget_info,
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
