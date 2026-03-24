"""Compute a detailed context breakdown for a channel's active session.

Used by the admin UI to show what goes into each agent turn.
"""
from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import (
    BotKnowledge,
    Channel,
    KnowledgeAccess,
    Memory,
    Message,
    Plan,
    Session,
)

logger = logging.getLogger(__name__)


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
class CompressionState:
    enabled: bool = False
    model: str = ""
    threshold: int = 0
    keep_turns: int = 0
    conversation_chars: int = 0
    would_compress: bool = False


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
    compression: CompressionState
    effective_settings: dict[str, EffectiveSetting]
    disclaimer: str


def _chars_to_tokens(chars: int) -> int:
    return max(1, int(math.ceil(chars / 4))) if chars > 0 else 0


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
) -> ContextBreakdownResult:
    from app.agent.base_prompt import render_base_prompt
    from app.agent.bots import get_bot
    from app.agent.persona import get_persona

    channel = await db.get(Channel, channel_id)
    if not channel:
        raise ValueError(f"Channel not found: {channel_id}")

    bot = get_bot(channel.bot_id)
    categories: list[ContextCategory] = []

    # -----------------------------------------------------------------------
    # 1. Static context
    # -----------------------------------------------------------------------

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

    # Memory guidelines (appended to system prompt)
    if bot.memory.enabled and bot.memory.prompt:
        mg_chars = len(bot.memory.prompt.strip())
        if mg_chars:
            categories.append(ContextCategory(
                key="memory_guidelines", label="Memory Guidelines", chars=mg_chars,
                tokens_approx=0, percentage=0, category="static",
                description="Instructions for memory usage appended to system prompt",
            ))

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

    # Datetime
    categories.append(ContextCategory(
        key="datetime", label="Date/Time", chars=72,
        tokens_approx=0, percentage=0, category="static",
        description="Current timestamp injected every turn",
    ))

    # -----------------------------------------------------------------------
    # 2. Per-turn RAG (heuristic estimates)
    # -----------------------------------------------------------------------

    # Skills
    pinned_skills = [s for s in bot.skills if s.mode == "pinned"]
    rag_skills = [s for s in bot.skills if s.mode == "rag"]
    od_skills = [s for s in bot.skills if s.mode == "on_demand"]

    if pinned_skills:
        from app.db.models import Skill as SkillRow
        ids = [s.id for s in pinned_skills]
        total_len = (await db.execute(
            select(func.sum(func.length(SkillRow.content))).where(SkillRow.id.in_(ids))
        )).scalar() or 0
        wrap = len("Pinned skill context:\n\n") + len("\n\n---\n\n") * max(0, len(ids) - 1)
        categories.append(ContextCategory(
            key="skills_pinned", label="Pinned Skills", chars=wrap + total_len,
            tokens_approx=0, percentage=0, category="rag",
            description=f"{len(ids)} pinned skill(s) injected in full every turn",
        ))

    if rag_skills:
        est = int(settings.RAG_TOP_K * 1200 * 0.45 * 0.7)
        categories.append(ContextCategory(
            key="skills_rag", label="RAG Skills", chars=est,
            tokens_approx=0, percentage=0, category="rag",
            description=f"{len(rag_skills)} RAG skill(s); varies by query",
        ))

    if od_skills:
        from app.db.models import Skill as SkillRow
        ids = [s.id for s in od_skills]
        rows = (await db.execute(
            select(SkillRow.id, SkillRow.name).where(SkillRow.id.in_(ids))
        )).all()
        if rows:
            hdr = len("Available skills (use get_skill to retrieve full content):\n")
            body = sum(len(f"- {r.id}: {r.name}\n") for r in rows)
            categories.append(ContextCategory(
                key="skills_index", label="Skill Index", chars=hdr + body,
                tokens_approx=0, percentage=0, category="rag",
                description=f"{len(rows)} on-demand skill(s) listed by name",
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

    # Memory RAG
    if bot.memory.enabled:
        mem_max = bot.memory_max_inject_chars or settings.MEMORY_MAX_INJECT_CHARS
        est_mem = int(settings.MEMORY_RETRIEVAL_LIMIT * mem_max * 0.4)
        categories.append(ContextCategory(
            key="memory_rag", label="Memory (RAG)", chars=est_mem,
            tokens_approx=0, percentage=0, category="rag",
            description="Semantically recalled memories; varies by query",
        ))

    # Knowledge RAG
    if bot.knowledge.enabled:
        know_max = bot.knowledge_max_inject_chars or settings.KNOWLEDGE_MAX_INJECT_CHARS
        est_k = int(3 * know_max * 0.35)
        categories.append(ContextCategory(
            key="knowledge_rag", label="Knowledge (RAG)", chars=est_k,
            tokens_approx=0, percentage=0, category="rag",
            description="Up to 3 knowledge docs; varies by query",
        ))

    # Pinned knowledge
    pinned_k_count = (await db.execute(
        select(func.count()).select_from(KnowledgeAccess)
        .where(
            KnowledgeAccess.scope_type == "channel",
            KnowledgeAccess.scope_key == str(channel_id),
            KnowledgeAccess.mode == "pinned",
        )
    )).scalar_one()
    if pinned_k_count:
        categories.append(ContextCategory(
            key="knowledge_pinned", label="Pinned Knowledge", chars=pinned_k_count * 2000,
            tokens_approx=0, percentage=0, category="rag",
            description=f"{pinned_k_count} pinned knowledge doc(s)",
        ))

    # Plans
    active_plans = (await db.execute(
        select(func.count()).select_from(Plan)
        .where(Plan.channel_id == channel_id, Plan.status == "active")
    )).scalar_one()
    if active_plans:
        categories.append(ContextCategory(
            key="plans", label="Active Plans", chars=active_plans * 600,
            tokens_approx=0, percentage=0, category="rag",
            description=f"{active_plans} active plan(s) injected each turn",
        ))

    # Workspace / filesystem context
    if bot.workspace.enabled and bot.workspace.indexing.enabled:
        est_ws = int(settings.FS_INDEX_TOP_K * settings.FS_INDEX_CHUNK_WINDOW * 0.3)
        categories.append(ContextCategory(
            key="workspace_context", label="Workspace Files", chars=est_ws,
            tokens_approx=0, percentage=0, category="rag",
            description="Workspace file chunks; varies by query",
        ))

    # -----------------------------------------------------------------------
    # 3. Conversation history (live from DB)
    # -----------------------------------------------------------------------
    session_id = str(channel.active_session_id) if channel.active_session_id else None
    total_messages = 0
    total_msg_chars = 0
    msgs_since_watermark = 0
    chars_since_watermark = 0

    if channel.active_session_id:
        session = await db.get(Session, channel.active_session_id)

        # Total messages
        total_messages = (await db.execute(
            select(func.count()).select_from(Message)
            .where(Message.session_id == channel.active_session_id)
        )).scalar_one()

        total_msg_chars = (await db.execute(
            select(func.coalesce(func.sum(func.length(Message.content)), 0))
            .where(Message.session_id == channel.active_session_id)
        )).scalar_one()

        # Messages since watermark
        if session and session.summary_message_id and session.summary:
            watermark_msg = await db.get(Message, session.summary_message_id)
            if watermark_msg:
                result = await db.execute(
                    select(func.count(), func.coalesce(func.sum(func.length(Message.content)), 0))
                    .where(
                        Message.session_id == channel.active_session_id,
                        Message.created_at > watermark_msg.created_at,
                    )
                )
                row = result.one()
                msgs_since_watermark = row[0]
                chars_since_watermark = row[1]
            else:
                msgs_since_watermark = total_messages
                chars_since_watermark = total_msg_chars
        else:
            msgs_since_watermark = total_messages
            chars_since_watermark = total_msg_chars

        # Add conversation history category
        if chars_since_watermark > 0:
            categories.append(ContextCategory(
                key="conversation", label="Conversation History",
                chars=chars_since_watermark,
                tokens_approx=0, percentage=0, category="conversation",
                description=f"{msgs_since_watermark} messages since last compaction" if session and session.summary else f"{total_messages} messages (no compaction yet)",
            ))

    # -----------------------------------------------------------------------
    # 4. Compaction state
    # -----------------------------------------------------------------------
    compaction_interval = _resolve_compaction_interval(channel, bot)
    compaction_keep_turns = _resolve_compaction_keep_turns(channel, bot)
    compaction_enabled = _resolve_compaction_enabled(channel, bot)

    summary_chars = 0
    has_summary = False
    if channel.active_session_id:
        session = await db.get(Session, channel.active_session_id)
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
    if channel.active_session_id:
        session = await db.get(Session, channel.active_session_id)
        if session and session.summary_message_id:
            watermark_msg = await db.get(Message, session.summary_message_id)
            if watermark_msg:
                user_turns_since = (await db.execute(
                    select(func.count()).select_from(Message)
                    .where(
                        Message.session_id == channel.active_session_id,
                        Message.created_at > watermark_msg.created_at,
                        Message.role == "user",
                    )
                )).scalar_one()
            else:
                user_turns_since = (await db.execute(
                    select(func.count()).select_from(Message)
                    .where(
                        Message.session_id == channel.active_session_id,
                        Message.role == "user",
                    )
                )).scalar_one()
        else:
            user_turns_since = (await db.execute(
                select(func.count()).select_from(Message)
                .where(
                    Message.session_id == channel.active_session_id,
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
    # 5. Context compression (ephemeral, per-turn)
    # -----------------------------------------------------------------------
    from app.services.compression import (
        _is_compression_enabled,
        _get_compression_model,
        _get_compression_threshold,
        _get_compression_keep_turns,
    )

    comp_enabled = _is_compression_enabled(bot, channel)
    comp_model = _get_compression_model(bot, channel)
    comp_threshold = _get_compression_threshold(bot, channel)
    comp_keep_turns = _get_compression_keep_turns(bot, channel)
    comp_conv_chars = chars_since_watermark
    comp_would_compress = comp_enabled and comp_conv_chars >= comp_threshold

    compression = CompressionState(
        enabled=comp_enabled,
        model=comp_model,
        threshold=comp_threshold,
        keep_turns=comp_keep_turns,
        conversation_chars=comp_conv_chars,
        would_compress=comp_would_compress,
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
        "context_compression": _resolve_setting(
            channel.context_compression, (bot.compression_config or {}).get("enabled"),
            settings.CONTEXT_COMPRESSION_ENABLED, "context_compression",
        ),
        "compression_threshold": _resolve_setting(
            channel.compression_threshold, (bot.compression_config or {}).get("threshold"),
            settings.CONTEXT_COMPRESSION_THRESHOLD, "compression_threshold",
        ),
        "compression_model": _resolve_setting(
            channel.compression_model, (bot.compression_config or {}).get("model"),
            settings.CONTEXT_COMPRESSION_MODEL or "(compaction model)", "compression_model",
        ),
        "memory_enabled": EffectiveSetting(value=bot.memory.enabled, source="bot"),
        "knowledge_enabled": EffectiveSetting(value=bot.knowledge.enabled, source="bot"),
        "tool_retrieval": EffectiveSetting(value=bot.tool_retrieval, source="bot"),
        "tool_similarity_threshold": EffectiveSetting(
            value=bot.tool_similarity_threshold or settings.TOOL_RETRIEVAL_THRESHOLD,
            source="bot" if bot.tool_similarity_threshold else "global",
        ),
        "base_prompt": EffectiveSetting(value=bot.base_prompt, source="bot"),
    }

    # -----------------------------------------------------------------------
    # Finalize: compute totals and percentages
    # -----------------------------------------------------------------------
    total_chars = sum(c.chars for c in categories)
    total_tokens = _chars_to_tokens(total_chars)

    for cat in categories:
        cat.tokens_approx = _chars_to_tokens(cat.chars)
        cat.percentage = round((cat.chars / total_chars * 100) if total_chars > 0 else 0, 1)

    return ContextBreakdownResult(
        channel_id=str(channel_id),
        session_id=session_id,
        bot_id=channel.bot_id,
        categories=categories,
        total_chars=total_chars,
        total_tokens_approx=total_tokens,
        compaction=compaction,
        compression=compression,
        effective_settings=effective_settings,
        disclaimer="RAG components are heuristic estimates. Actual values vary per query based on semantic similarity scores.",
    )


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
