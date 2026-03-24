"""Context injection pipeline — assembles RAG context before the agent tool loop."""

import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.agent.bots import BotConfig
from app.agent.context import set_ephemeral_delegates
from app.agent.knowledge import retrieve_knowledge
from app.agent.memory import retrieve_memories
from app.agent.message_utils import (
    _AUDIO_TRANSCRIPT_INSTRUCTION,
    _all_tool_schemas_by_name,
    _build_audio_user_message,
    _build_user_message_content,
    _merge_tool_schemas,
)
from app.agent.rag import retrieve_context, fetch_skill_chunks_by_id
from app.agent.recording import _record_trace_event
from app.agent.tags import resolve_tags
from app.agent.tools import retrieve_tools
from app.config import settings
from app.tools.client_tools import get_client_tool_schemas
from app.tools.mcp import get_mcp_server_for_tool

logger = logging.getLogger(__name__)


@dataclass
class AssemblyResult:
    """Side-channel outputs from context assembly needed by the caller."""
    pre_selected_tools: list[dict[str, Any]] | None = None
    user_msg_index: int = 0
    tagged_tool_names: list[str] = field(default_factory=list)
    tagged_bot_names: list[str] = field(default_factory=list)


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
) -> AsyncGenerator[dict[str, Any], None]:
    """Inject all RAG context into messages and yield status events.

    Mutates `messages` in-place. Populates `result` with side-channel outputs.
    """
    _inject_chars: dict[str, int] = {}

    # --- datetime ---
    try:
        from zoneinfo import ZoneInfo
        _tz = ZoneInfo(settings.TIMEZONE)
        _now_local = datetime.now(_tz)
        _now_utc = datetime.now(timezone.utc)
        messages.append({
            "role": "system",
            "content": (
                f"Current time: {_now_local.strftime('%Y-%m-%d %H:%M %Z')} "
                f"({_now_utc.strftime('%H:%M UTC')})"
            ),
        })
    except Exception:
        pass  # non-fatal if timezone lookup fails

    # --- @mention tag resolution ---
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
    _tagged_knowledge_names = [t.name for t in _tagged if t.tag_type == "knowledge"]
    _tagged_tool_names = [t.name for t in _tagged if t.tag_type == "tool"]
    _tagged_bot_names = [t.name for t in _tagged if t.tag_type == "bot"]
    result.tagged_tool_names = _tagged_tool_names
    result.tagged_bot_names = _tagged_bot_names
    if _tagged_bot_names:
        set_ephemeral_delegates(_tagged_bot_names)

    if _tagged:
        # Inject tagged skill chunks (bypasses similarity threshold)
        if _tagged_skill_names:
            _tagged_skill_chunks: list[str] = []
            for _sid in _tagged_skill_names:
                _tagged_skill_chunks.extend(await fetch_skill_chunks_by_id(_sid))
            if _tagged_skill_chunks:
                messages.append({
                    "role": "system",
                    "content": "Tagged skill context (explicitly requested):\n\n"
                               + "\n\n---\n\n".join(_tagged_skill_chunks),
                })

        # Inject tagged knowledge docs (bypasses similarity threshold)
        if _tagged_knowledge_names and client_id:
            from app.agent.knowledge import get_knowledge_by_name
            _tagged_know_chunks: list[str] = []
            for _kname in _tagged_knowledge_names:
                _doc = await get_knowledge_by_name(
                    _kname,
                    bot.id,
                    client_id,
                    session_id=session_id,
                    ignore_session_scope=True,
                )
                if _doc:
                    _tagged_know_chunks.append(_doc)
                else:
                    logger.warning("Tagged knowledge %r not found", _kname)
            if _tagged_know_chunks:
                messages.append({
                    "role": "system",
                    "content": "Tagged knowledge (explicitly requested):\n\n"
                               + "\n\n---\n\n".join(_tagged_know_chunks),
                })

        yield {
            "type": "tagged_context",
            "tags": [t.raw for t in _tagged],
            "skills": _tagged_skill_names,
            "knowledge": _tagged_knowledge_names,
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
                    "knowledge": _tagged_knowledge_names,
                    "tools": _tagged_tool_names,
                    "bots": _tagged_bot_names,
                },
            ))

    # --- skills ---
    if bot.skills:
        _pinned_skills = [s for s in bot.skills if s.mode == "pinned"]
        _rag_skills = [s for s in bot.skills if s.mode == "rag"]
        _on_demand_skills = [s for s in bot.skills if s.mode == "on_demand"]

        # Pinned skills: inject full content every turn
        if _pinned_skills:
            _pinned_chunks: list[str] = []
            for _ps in _pinned_skills:
                _pinned_chunks.extend(await fetch_skill_chunks_by_id(_ps.id))
            if _pinned_chunks:
                _pinned_chars = sum(len(c) for c in _pinned_chunks)
                _inject_chars["skill_pinned"] = _pinned_chars
                messages.append({
                    "role": "system",
                    "content": "Pinned skill context:\n\n" + "\n\n---\n\n".join(_pinned_chunks),
                })
                yield {"type": "skill_pinned_context", "count": len(_pinned_chunks), "chars": _pinned_chars}
                if correlation_id is not None:
                    asyncio.create_task(_record_trace_event(
                        correlation_id=correlation_id,
                        session_id=session_id,
                        bot_id=bot.id,
                        client_id=client_id,
                        event_type="skill_pinned_context",
                        count=len(_pinned_chunks),
                        data={"skill_ids": [s.id for s in _pinned_skills], "chars": _pinned_chars},
                    ))

        # RAG skills: semantic similarity retrieval
        if _rag_skills:
            _rag_ids = [s.id for s in _rag_skills]
            _thresholds = [s.similarity_threshold for s in _rag_skills if s.similarity_threshold is not None]
            _min_threshold = min(_thresholds) if _thresholds else None
            chunks, skill_sim = await retrieve_context(
                user_message, skill_ids=_rag_ids, similarity_threshold=_min_threshold,
            )
            if chunks:
                _skill_chars = sum(len(c) for c in chunks)
                _inject_chars["skill_rag"] = _skill_chars
                yield {"type": "skill_context", "count": len(chunks), "chars": _skill_chars}
                if correlation_id is not None:
                    asyncio.create_task(_record_trace_event(
                        correlation_id=correlation_id,
                        session_id=session_id,
                        bot_id=bot.id,
                        client_id=client_id,
                        event_type="skill_context",
                        count=len(chunks),
                        data={"preview": chunks[0][:200], "best_similarity": round(skill_sim, 4), "chars": _skill_chars},
                    ))
                context = "\n\n---\n\n".join(chunks)
                messages.append({
                    "role": "system",
                    "content": f"Relevant skill context:\n\n{context}",
                })

        # On-demand skills: inject index, agent uses get_skill()
        if _on_demand_skills:
            from sqlalchemy import select as _sa_select
            from app.db.engine import async_session as _async_session
            from app.db.models import Skill as _SkillRow
            _od_ids = [s.id for s in _on_demand_skills]
            async with _async_session() as _db:
                _rows = (await _db.execute(
                    _sa_select(_SkillRow.id, _SkillRow.name)
                    .where(_SkillRow.id.in_(_od_ids))
                )).all()
            if _rows:
                _index_lines = "\n".join(f"- {r.id}: {r.name}" for r in _rows)
                messages.append({
                    "role": "system",
                    "content": (
                        f"Available skills (use get_skill to retrieve full content):\n{_index_lines}"
                    ),
                })
                yield {"type": "skill_index", "count": len(_rows)}
                if correlation_id is not None:
                    asyncio.create_task(_record_trace_event(
                        correlation_id=correlation_id,
                        session_id=session_id,
                        bot_id=bot.id,
                        client_id=client_id,
                        event_type="skill_index",
                        count=len(_rows),
                        data={"skill_ids": [r.id for r in _rows]},
                    ))

    # --- delegate bot index ---
    _all_delegate_ids = list(dict.fromkeys(bot.delegate_bots + _tagged_bot_names))
    if _all_delegate_ids:
        from app.agent.bots import get_bot as _get_bot
        _delegate_lines: list[str] = []
        for _did in _all_delegate_ids:
            try:
                _db = _get_bot(_did)
                _desc = (_db.system_prompt or "").strip().splitlines()[0][:120] if _db.system_prompt else ""
                _delegate_lines.append(f"  • {_did} — {_db.name}" + (f": {_desc}" if _desc else ""))
            except Exception:
                _delegate_lines.append(f"  • {_did}")
        if _delegate_lines:
            messages.append({
                "role": "system",
                "content": (
                    "Available sub-agents (delegate via delegate_to_agent or @bot-id in your reply):\n"
                    + "\n".join(_delegate_lines)
                ),
            })
            yield {"type": "delegate_index", "count": len(_delegate_lines)}

    # --- memories ---
    if bot.memory.enabled and session_id and client_id:
        memories, mem_sim = await retrieve_memories(
            query=user_message,
            session_id=session_id,
            client_id=client_id,
            bot_id=bot.id,
            cross_channel=bot.memory.cross_channel,
            cross_client=bot.memory.cross_client,
            cross_bot=bot.memory.cross_bot,
            similarity_threshold=bot.memory.similarity_threshold,
            channel_id=channel_id,
            user_id=bot.user_id,
        )
        if memories:
            _mem_limit = bot.memory_max_inject_chars or settings.MEMORY_MAX_INJECT_CHARS
            memories = [
                m[:_mem_limit] + ("…" if len(m) > _mem_limit else "")
                for m in memories
            ]
            _mem_chars = sum(len(m) for m in memories)
            _inject_chars["memory"] = _mem_chars
            memory_preview = memories[0][:100] + "..." if len(memories[0]) > 100 else memories[0]
            yield {"type": "memory_context", "count": len(memories), "memory_preview": memory_preview, "chars": _mem_chars}
            if correlation_id is not None:
                asyncio.create_task(_record_trace_event(
                    correlation_id=correlation_id,
                    session_id=session_id,
                    bot_id=bot.id,
                    client_id=client_id,
                    event_type="memory_injection",
                    count=len(memories),
                    data={"preview": memories[0][:200], "best_similarity": round(mem_sim, 4), "chars": _mem_chars},
                ))
            messages.append({
                "role": "system",
                "content": (
                    "Relevant memories from past conversations (automatically recalled "
                    "based on the user's message; you can use these directly):\n\n"
                    + "\n\n---\n\n".join(memories)
                ),
            })

    # --- pinned knowledge ---
    if client_id:
        from app.agent.knowledge import get_pinned_knowledge_docs
        pinned_docs, pinned_names = await get_pinned_knowledge_docs(
            bot.id, client_id, session_id=session_id, channel_id=channel_id,
        )
        if pinned_docs:
            _know_limit = bot.knowledge_max_inject_chars or settings.KNOWLEDGE_MAX_INJECT_CHARS
            pinned_docs = [
                d[:_know_limit] + ("…" if len(d) > _know_limit else "")
                for d in pinned_docs
            ]
            _pinned_chars = sum(len(d) for d in pinned_docs)
            _inject_chars["pinned_knowledge"] = _pinned_chars
            yield {"type": "pinned_knowledge_context", "count": len(pinned_docs), "chars": _pinned_chars}
            if correlation_id is not None:
                asyncio.create_task(_record_trace_event(
                    correlation_id=correlation_id,
                    session_id=session_id,
                    bot_id=bot.id,
                    client_id=client_id,
                    event_type="pinned_knowledge_context",
                    count=len(pinned_docs),
                    data={"names": pinned_names, "chars": _pinned_chars},
                ))
            messages.append({
                "role": "system",
                "content": "Pinned knowledge (always available):\n\n" + "\n\n---\n\n".join(pinned_docs),
            })

    # --- RAG knowledge ---
    if bot.knowledge.enabled and client_id:
        chunks, know_sim = await retrieve_knowledge(
            query=user_message,
            bot_id=bot.id,
            client_id=client_id,
            fallback_threshold=settings.KNOWLEDGE_SIMILARITY_THRESHOLD,
            session_id=session_id,
            channel_id=channel_id,
        )
        if chunks:
            _know_limit = bot.knowledge_max_inject_chars or settings.KNOWLEDGE_MAX_INJECT_CHARS
            chunks = [
                c[:_know_limit] + ("…" if len(c) > _know_limit else "")
                for c in chunks
            ]
            _know_chars = sum(len(c) for c in chunks)
            _inject_chars["knowledge"] = _know_chars
            knowledge_preview = chunks[0][:100] + "..." if len(chunks[0]) > 100 else chunks[0]
            yield {"type": "knowledge_context", "count": len(chunks), "knowledge_preview": knowledge_preview, "chars": _know_chars}
            if correlation_id is not None:
                asyncio.create_task(_record_trace_event(
                    correlation_id=correlation_id,
                    session_id=session_id,
                    bot_id=bot.id,
                    client_id=client_id,
                    event_type="knowledge_context",
                    count=len(chunks),
                    data={"preview": chunks[0][:200], "best_similarity": round(know_sim, 4), "chars": _know_chars},
                ))
            messages.append({"role": "system", "content": "Relevant knowledge:\n\n" + "\n\n---\n\n".join(chunks)})

    # --- active plans ---
    if session_id or channel_id:
        from app.db.models import Plan as _Plan, PlanItem as _PlanItem
        from app.db.engine import async_session as _async_session_plans
        from sqlalchemy import select as _sa_select_plans, or_ as _sa_or
        async with _async_session_plans() as _pdb:
            _plan_filters = []
            if session_id:
                _plan_filters.append(_Plan.session_id == session_id)
            if channel_id:
                _plan_filters.append(_Plan.channel_id == channel_id)
            _plan_rows = (await _pdb.execute(
                _sa_select_plans(_Plan)
                .where(_sa_or(*_plan_filters), _Plan.status == "active")
                .order_by(_Plan.created_at)
            )).scalars().all()
        if _plan_rows:
            _plan_lines: list[str] = []
            for _p in _plan_rows:
                async with _async_session_plans() as _idb:
                    _items = (await _idb.execute(
                        _sa_select_plans(_PlanItem)
                        .where(_PlanItem.plan_id == _p.id)
                        .order_by(_PlanItem.position)
                    )).scalars().all()
                _plan_lines.append(
                    f"## {_p.title}\n" + "\n".join(
                        f"{i.position}. [{i.status}] {i.content}"
                        + (f"\n   notes: {i.notes}" if i.notes else "")
                        for i in _items
                    )
                )
            messages.append({
                "role": "system",
                "content": "Active plans for this session:\n\n" + "\n\n".join(_plan_lines),
            })
            yield {"type": "plans_context", "count": len(_plan_rows)}

    # --- workspace filesystem context ---
    _do_workspace_rag = False
    if bot.workspace.enabled and bot.workspace.indexing.enabled:
        # Check channel override
        _channel_rag = True
        if channel_id:
            try:
                from app.db.engine import async_session as _async_session_ch
                from app.db.models import Channel as _Channel
                async with _async_session_ch() as _chdb:
                    _ch = await _chdb.get(_Channel, channel_id)
                    if _ch and not _ch.workspace_rag:
                        _channel_rag = False
            except Exception:
                pass
        _do_workspace_rag = _channel_rag

    if _do_workspace_rag:
        from app.agent.fs_indexer import retrieve_filesystem_context
        from app.services.workspace import workspace_service
        _ws_root = workspace_service.get_workspace_root(bot.id, bot=bot)
        _ws_threshold = bot.workspace.indexing.similarity_threshold
        _ws_top_k = bot.workspace.indexing.top_k
        fs_chunks, fs_sim = await retrieve_filesystem_context(
            user_message, bot.id, roots=[_ws_root],
            threshold=_ws_threshold, top_k=_ws_top_k,
        )
        if fs_chunks:
            yield {"type": "fs_context", "count": len(fs_chunks)}
            if correlation_id is not None:
                asyncio.create_task(_record_trace_event(
                    correlation_id=correlation_id,
                    session_id=session_id,
                    bot_id=bot.id,
                    client_id=client_id,
                    event_type="fs_context",
                    count=len(fs_chunks),
                    data={"preview": fs_chunks[0][:200], "best_similarity": round(fs_sim, 4)},
                ))
            messages.append({
                "role": "system",
                "content": "Relevant files from workspace (hint: use exec_command with `cat <filepath>` to read full contents):\n\n"
                           + "\n\n---\n\n".join(fs_chunks),
            })
    elif bot.filesystem_indexes:
        # Legacy filesystem_indexes path
        from app.agent.fs_indexer import retrieve_filesystem_context
        fs_threshold = min(
            (cfg.similarity_threshold for cfg in bot.filesystem_indexes if cfg.similarity_threshold is not None),
            default=None,
        )
        fs_chunks, fs_sim = await retrieve_filesystem_context(user_message, bot.id, threshold=fs_threshold)
        if fs_chunks:
            yield {"type": "fs_context", "count": len(fs_chunks)}
            if correlation_id is not None:
                asyncio.create_task(_record_trace_event(
                    correlation_id=correlation_id,
                    session_id=session_id,
                    bot_id=bot.id,
                    client_id=client_id,
                    event_type="fs_context",
                    count=len(fs_chunks),
                    data={"preview": fs_chunks[0][:200], "best_similarity": round(fs_sim, 4)},
                ))
            messages.append({
                "role": "system",
                "content": "Relevant code/files from indexed directories (hint: use exec_command with `cat <filepath>` to read full contents):\n\n"
                           + "\n\n---\n\n".join(fs_chunks),
            })

    # --- tool retrieval (tool RAG) ---
    pre_selected_tools: list[dict[str, Any]] | None = None
    if bot.tool_retrieval and (bot.local_tools or bot.mcp_servers or bot.client_tools):
        by_name = await _all_tool_schemas_by_name(bot)
        if by_name:
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
            )
            if correlation_id is not None:
                asyncio.create_task(_record_trace_event(
                    correlation_id=correlation_id,
                    session_id=session_id,
                    bot_id=bot.id,
                    client_id=client_id,
                    event_type="tool_retrieval",
                    count=len(retrieved),
                    data={"best_similarity": tool_sim, "threshold": th,
                          "selected": [t["function"]["name"] for t in retrieved],
                          "top_candidates": tool_candidates},
                ))
            _effective_pinned = list(bot.pinned_tools or []) + _tagged_tool_names + ["get_tool_info"]
            pinned_list = [by_name[n] for n in _effective_pinned if n in by_name]
            # Also support server-level pinning: if a pinned entry is an MCP server name,
            # include all tools from that server.
            _server_pins = {n for n in _effective_pinned if n not in by_name}
            if _server_pins:
                for _tool_name, _schema in by_name.items():
                    if get_mcp_server_for_tool(_tool_name) in _server_pins:
                        pinned_list.append(_schema)
            client_only = get_client_tool_schemas(bot.client_tools)
            merged = _merge_tool_schemas(pinned_list, retrieved, client_only)
            if not merged:
                pre_selected_tools = list(by_name.values())
            else:
                pre_selected_tools = merged

            # Inject compact names index for unretrieved tools
            _retrieved_names = {t["function"]["name"] for t in pre_selected_tools}
            _unretrieved = [
                (n, s["function"].get("description", "")[:80])
                for n, s in by_name.items()
                if n not in _retrieved_names and n != "get_tool_info"
            ]
            if _unretrieved:
                _index_lines = "\n".join(f"  • {n}: {d}" for n, d in _unretrieved)
                messages.append({
                    "role": "system",
                    "content": (
                        "Available tools (not yet loaded — use get_tool_info(tool_name) to get full schema):\n"
                        + _index_lines
                    ),
                })
                yield {"type": "tool_index", "unretrieved_count": len(_unretrieved)}
    result.pre_selected_tools = pre_selected_tools

    # --- user message (audio or text) ---
    if native_audio:
        messages.append({
            "role": "system",
            "content": _AUDIO_TRANSCRIPT_INSTRUCTION,
        })
        user_msg = _build_audio_user_message(audio_data, audio_format)
        messages.append(user_msg)
        result.user_msg_index = len(messages) - 1
    else:
        user_content = _build_user_message_content(user_message, attachments)
        messages.append({"role": "user", "content": user_content})
        result.user_msg_index = len(messages) - 1

    # --- injection summary trace ---
    if correlation_id is not None and _inject_chars:
        asyncio.create_task(_record_trace_event(
            correlation_id=correlation_id,
            session_id=session_id,
            bot_id=bot.id,
            client_id=client_id,
            event_type="context_injection_summary",
            data={
                "breakdown": _inject_chars,
                "total_chars": sum(_inject_chars.values()),
            },
        ))
