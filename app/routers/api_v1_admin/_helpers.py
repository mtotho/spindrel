"""Shared helpers for admin sub-modules."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, Task, TraceEvent

from ._schemas import (
    BotOut,
    KnowledgeConfigOut,
    MemoryConfigOut,
    SkillConfigOut,
)


def _to_dict(obj: Any) -> dict:
    """Convert a dataclass (or dict) to a plain dict."""
    import dataclasses
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, dict):
        return obj
    return {"enabled": False}


def _bot_to_out(
    bot,
    *,
    persona_content: str | None = None,
    persona_from_workspace: bool = False,
    workspace_persona_content: str | None = None,
) -> BotOut:
    """Convert a BotConfig dataclass to a BotOut Pydantic model."""
    return BotOut(
        id=bot.id,
        name=bot.name,
        model=bot.model,
        system_prompt=bot.system_prompt,
        display_name=bot.display_name,
        avatar_url=bot.avatar_url,
        local_tools=bot.local_tools,
        mcp_servers=bot.mcp_servers,
        client_tools=bot.client_tools,
        pinned_tools=bot.pinned_tools,
        skills=[
            SkillConfigOut(id=s.id, mode=s.mode, similarity_threshold=s.similarity_threshold)
            for s in bot.skills
        ],
        tool_retrieval=bot.tool_retrieval,
        tool_similarity_threshold=bot.tool_similarity_threshold,
        tool_result_config=getattr(bot, "tool_result_config", {}),
        compression_config=getattr(bot, "compression_config", {}),
        persona=bot.persona,
        persona_content=persona_content,
        persona_from_workspace=persona_from_workspace,
        workspace_persona_content=workspace_persona_content,
        context_compaction=bot.context_compaction,
        compaction_interval=bot.compaction_interval,
        compaction_keep_turns=bot.compaction_keep_turns,
        compaction_model=getattr(bot, "compaction_model", None),
        audio_input=bot.audio_input,
        memory=MemoryConfigOut(
            enabled=bot.memory.enabled,
            cross_channel=bot.memory.cross_channel,
            cross_client=bot.memory.cross_client,
            cross_bot=bot.memory.cross_bot,
            prompt=bot.memory.prompt,
            similarity_threshold=bot.memory.similarity_threshold,
        ),
        memory_max_inject_chars=getattr(bot, "memory_max_inject_chars", None),
        knowledge=KnowledgeConfigOut(enabled=bot.knowledge.enabled),
        knowledge_max_inject_chars=getattr(bot, "knowledge_max_inject_chars", None),
        delegate_bots=bot.delegate_bots,
        harness_access=bot.harness_access,
        model_provider_id=bot.model_provider_id,
        integration_config=getattr(bot, "integration_config", {}),
        workspace=_to_dict(getattr(bot, "workspace", {"enabled": False})),
        docker_sandbox_profiles=getattr(bot, "docker_sandbox_profiles", []),
        elevation_enabled=getattr(bot, "elevation_enabled", None),
        elevation_threshold=getattr(bot, "elevation_threshold", None),
        elevated_model=getattr(bot, "elevated_model", None),
        attachment_summarization_enabled=getattr(bot, "attachment_summarization_enabled", None),
        attachment_summary_model=getattr(bot, "attachment_summary_model", None),
        attachment_text_max_chars=getattr(bot, "attachment_text_max_chars", None),
        attachment_vision_concurrency=getattr(bot, "attachment_vision_concurrency", None),
        history_mode=getattr(bot, "history_mode", "summary"),
        model_params=getattr(bot, "model_params", {}),
        delegation_config={
            "delegate_bots": bot.delegate_bots or [],
            "harness_access": bot.harness_access or [],
        },
        user_id=getattr(bot, "user_id", None),
        shared_workspace_id=getattr(bot, "shared_workspace_id", None),
        shared_workspace_role=getattr(bot, "shared_workspace_role", None),
        created_at=bot.created_at.isoformat() if hasattr(bot, "created_at") and bot.created_at else None,
        updated_at=bot.updated_at.isoformat() if hasattr(bot, "updated_at") and bot.updated_at else None,
    )


async def _heartbeat_correlation_ids(
    db: AsyncSession, tasks: list[Task],
) -> dict[uuid.UUID, uuid.UUID]:
    """Look up correlation_id for each heartbeat task.

    Tries Messages first (user message created after task.run_at), then falls
    back to TraceEvents for tasks that failed before messages were persisted.
    Returns {task_id: correlation_id}.
    """
    if not tasks:
        return {}
    candidates = [t for t in tasks if t.session_id and t.run_at]
    if not candidates:
        return {}

    session_ids = list({t.session_id for t in candidates})
    earliest_run = min(t.run_at for t in candidates)

    # Primary: user messages with correlation_id
    msg_rows = (await db.execute(
        select(Message.session_id, Message.correlation_id, Message.created_at)
        .where(
            Message.session_id.in_(session_ids),
            Message.role == "user",
            Message.correlation_id.is_not(None),
            Message.created_at >= earliest_run,
        )
        .order_by(Message.created_at)
    )).all()

    result: dict[uuid.UUID, uuid.UUID] = {}
    unmatched = []
    for t in candidates:
        found = False
        for row in msg_rows:
            if row.session_id == t.session_id and row.created_at >= t.run_at:
                result[t.id] = row.correlation_id
                found = True
                break
        if not found:
            unmatched.append(t)

    # Fallback: trace events for tasks with no message match
    if unmatched:
        te_rows = (await db.execute(
            select(TraceEvent.session_id, TraceEvent.correlation_id, TraceEvent.created_at)
            .where(
                TraceEvent.session_id.in_([t.session_id for t in unmatched]),
                TraceEvent.correlation_id.is_not(None),
                TraceEvent.created_at >= earliest_run,
            )
            .order_by(TraceEvent.created_at)
        )).all()
        for t in unmatched:
            for row in te_rows:
                if row.session_id == t.session_id and row.created_at >= t.run_at:
                    result[t.id] = row.correlation_id
                    break

    return result
