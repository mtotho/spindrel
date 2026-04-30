"""Static context-admission stages for context assembly."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from app.agent.bots import BotConfig
from app.agent.context_profiles import ContextProfile
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
from app.config import settings

logger = logging.getLogger(__name__)

CHANNEL_WORKSPACE_TOOLS = [
    "file",
    "search_channel_archive",
    "search_channel_workspace",
    "search_channel_knowledge",
    "search_bot_knowledge",
    "list_channels",
]
_CHANNEL_WORKSPACE_BUDGET = 50_000


def _safe_sim(value: float) -> float | None:
    import math

    if math.isnan(value):
        return None
    return round(value, 4)


def _mark_injection_decision(
    inject_decisions: dict[str, str],
    key: str,
    decision: str,
) -> None:
    inject_decisions[key] = decision


def apply_channel_workspace_tools(bot: BotConfig) -> BotConfig:
    local_tools = list(bot.local_tools)
    for tool_name in CHANNEL_WORKSPACE_TOOLS:
        if tool_name not in local_tools:
            local_tools.append(tool_name)
    return replace(
        bot,
        local_tools=local_tools,
        pinned_tools=list(dict.fromkeys((bot.pinned_tools or []) + CHANNEL_WORKSPACE_TOOLS)),
    )


def render_channel_workspace_prompt(
    *,
    workspace_path: str,
    channel_id: str,
    data_listing: str,
    style: str = "markdown",
) -> str:
    """Render the channel workspace helper prompt from the configured template."""
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


async def inject_plan_artifact(
    messages: list[dict],
    session_id: uuid.UUID | None,
    ledger: Any,
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


async def inject_memory_scheme(
    messages: list[dict],
    bot: BotConfig,
    ledger: Any,
    injected_paths: set[str],
    context_profile: ContextProfile,
) -> AsyncGenerator[dict[str, Any], None]:
    """Inject memory scheme files (MEMORY.md, daily logs, reference index)."""
    import os
    from datetime import date, timedelta

    from app.services.memory_scheme import get_memory_index_prefix, get_memory_rel_path, get_memory_root
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
                    nudge_text = (
                        f"[Memory housekeeping] Your MEMORY.md is {line_count} lines "
                        f"(threshold: {settings.MEMORY_MD_NUDGE_THRESHOLD}). "
                        "Consider pruning stale entries, merging duplicates, or moving detailed "
                        "notes to reference/ files to keep MEMORY.md concise and fast to scan."
                    )
                    if context_profile.allow_memory_recent_logs and budget_can_afford(nudge_text):
                        messages.append({"role": "system", "content": nudge_text})
                        budget_consume("memory_housekeeping", nudge_text)
                        _mark_injection_decision(inject_decisions, "memory_housekeeping", "admitted")
                    elif not context_profile.allow_memory_recent_logs:
                        _mark_injection_decision(inject_decisions, "memory_housekeeping", "skipped_by_profile")
                    else:
                        _mark_injection_decision(inject_decisions, "memory_housekeeping", "skipped_by_budget")
            else:
                _mark_injection_decision(inject_decisions, "memory_bootstrap", "skipped_empty")
        else:
            _mark_injection_decision(inject_decisions, "memory_bootstrap", "skipped_missing")

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

        skip_files = {"MEMORY.md"}
        if not context_profile.allow_memory_recent_logs:
            _mark_injection_decision(inject_decisions, "memory_loose_files", "skipped_by_profile")
        else:
            loose_files = sorted(
                f for f in os.listdir(mem_root)
                if f.endswith(".md") and f not in skip_files and os.path.isfile(os.path.join(mem_root, f))
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

        nudge_turn_threshold = 5
        user_turns_since_memory_write = 0
        found_memory_write = False
        for msg in reversed(messages):
            role = msg.get("role", "")
            if role == "user":
                user_turns_since_memory_write += 1
                if user_turns_since_memory_write > nudge_turn_threshold:
                    break
            elif role == "tool":
                content_str = msg.get("content", "")
                if isinstance(content_str, str) and "memory/" in content_str and '"ok"' in content_str:
                    found_memory_write = True
                    break
            elif role == "assistant":
                for tc in msg.get("tool_calls", []):
                    args = tc.get("function", {}).get("arguments", "")
                    if isinstance(args, str) and "memory/" in args:
                        name = tc.get("function", {}).get("name", "")
                        if name == "file":
                            found_memory_write = True
                            break
                if found_memory_write:
                    break

        if user_turns_since_memory_write >= nudge_turn_threshold and not found_memory_write:
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


async def inject_channel_workspace(
    messages: list[dict],
    bot: BotConfig,
    ch_row: Any,
    user_message: str,
    ledger: Any,
    context_profile: ContextProfile,
    model_override: str | None = None,
    provider_id_override: str | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Inject channel workspace files, data listing, schema, index segments, and plan stall detection."""
    import os

    from app.services.channel_workspace import ensure_channel_workspace, get_channel_workspace_root

    ch_id = str(ch_row.id)
    inject_chars = ledger.inject_chars
    budget_consume = ledger.consume
    budget_can_afford = ledger.can_afford
    inject_decisions = ledger.inject_decisions

    try:
        from app.db.engine import async_session
        from app.services.projects import is_project_like_surface, resolve_channel_work_surface

        try:
            async with async_session() as db:
                surface = await resolve_channel_work_surface(db, ch_row, bot)
        except Exception as exc:
            logger.debug(
                "Failed to resolve channel work surface for channel %s",
                ch_row.id,
                exc_info=True,
            )
            if getattr(ch_row, "project_id", None):
                text = f"Project work surface could not be resolved for this channel: {exc}"
                messages.append({"role": "system", "content": text})
                inject_chars["project_work_surface_error"] = len(text)
                budget_consume("project_work_surface_error", text)
                return
            surface = None

        if is_project_like_surface(surface):
            cw_root = surface.root_host_path
            cw_abs = surface.display_path
            index_root = surface.index_root_host_path
            channel_index_prefix = surface.index_prefix
            surface_label = "Fresh Project instance" if surface.kind == "project_instance" else "Project workspace"
            helper_prefix = (
                f"{surface_label} — {surface.project_name or surface.index_prefix}\n"
                "This channel is attached to the Project root below; treat it as the default working surface for code, files, search, and exec.\n"
            )
        else:
            ensure_channel_workspace(ch_id, bot, display_name=ch_row.name)
            cw_root = get_channel_workspace_root(ch_id, bot)
            cw_abs = f"/workspace/channels/{ch_id}"
            index_root = str(Path(cw_root).parent.parent)
            channel_index_prefix = f"channels/{ch_id}"
            helper_prefix = ""

        cw_files: list[tuple[str, str]] = []
        total_chars = 0
        if os.path.isdir(cw_root):
            for entry in sorted(os.scandir(cw_root), key=lambda e: e.name):
                if entry.is_file() and entry.name.endswith(".md"):
                    try:
                        content = Path(entry.path).read_text()
                        if content.strip():
                            if total_chars + len(content) > _CHANNEL_WORKSPACE_BUDGET:
                                content = content[:_CHANNEL_WORKSPACE_BUDGET - total_chars] + "\n\n[...truncated]"
                            cw_files.append((entry.name, content))
                            total_chars += len(content)
                            if total_chars >= _CHANNEL_WORKSPACE_BUDGET:
                                break
                    except Exception:
                        pass
        else:
            logger.warning("Channel workspace dir does not exist: %s", cw_root)

        data_dir = os.path.join(cw_root, "data")
        data_listing = ""
        if os.path.isdir(data_dir):
            data_entries = sorted(e.name for e in os.scandir(data_dir) if e.is_file())
            if data_entries:
                data_listing = (
                    "\nData files (data/ — not auto-injected, reference via workspace .md files):\n"
                    + "\n".join(f"  - {name}" for name in data_entries)
                    + "\n"
                )

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
                        str(ch_row.workspace_schema_template_id),
                        fallback="",
                        db=db,
                    )
            except Exception:
                logger.warning("Failed to resolve workspace schema template for channel %s", ch_row.id, exc_info=True)

        from app.services.providers import resolve_prompt_style

        helper = render_channel_workspace_prompt(
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

        from app.services.bot_indexing import reindex_channel

        cw_segments = getattr(ch_row, "index_segments", None) or []
        asyncio.create_task(
            reindex_channel(
                ch_id,
                bot,
                channel_segments=cw_segments if cw_segments else None,
                force=False,
            )
        )

        try:
            from app.agent.fs_indexer import retrieve_filesystem_context
            from app.services.bot_indexing import resolve_for

            plan = resolve_for(bot, scope="workspace")
            if plan is None:
                raise RuntimeError("channel RAG requires workspace-enabled bot")

            implicit_kb_prefix = surface.knowledge_index_prefix if surface is not None else f"channels/{ch_id}/knowledge-base"
            seg_dicts: list[dict] = [{
                "path_prefix": implicit_kb_prefix,
                "embedding_model": plan.embedding_model,
            }]
            for seg in cw_segments:
                explicit_prefix = f"{channel_index_prefix}/{seg['path_prefix'].strip('/')}"
                if explicit_prefix.rstrip("/") == implicit_kb_prefix:
                    continue
                seg_dicts.append({
                    "path_prefix": explicit_prefix,
                    "embedding_model": seg.get("embedding_model") or plan.embedding_model,
                })

            seg_top_k = max((seg.get("top_k", 8) for seg in cw_segments), default=8)
            seg_threshold = min((seg.get("similarity_threshold", 0.35) for seg in cw_segments), default=0.35)
            chunks, sim = await retrieve_filesystem_context(
                user_message,
                f"channel:{ch_row.id}",
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
            logger.warning(
                "Failed to retrieve channel knowledge-base / index segments for channel %s",
                ch_row.id,
                exc_info=True,
            )

    except Exception:
        logger.warning("Failed to inject channel workspace files for channel %s", ch_row.id, exc_info=True)


async def inject_conversation_sections(
    messages: list[dict],
    bot: BotConfig,
    ch_row: Any,
    channel_id: uuid.UUID,
    session_id: uuid.UUID | None,
    user_message: str,
    ledger: Any,
    context_profile: ContextProfile,
) -> AsyncGenerator[dict[str, Any], None]:
    """Inject conversation section context (structured mode) or section index (file mode)."""
    from sqlalchemy import func, select
    from sqlalchemy.orm import defer

    from app.db.engine import async_session
    from app.db.models import ConversationSection
    from app.services.compaction import _get_history_mode

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
            texts = [row.transcript if row.transcript else f"## {row.title}\n{row.summary}" for row in rows]
            chars = sum(len(text) for text in texts)
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

                text = format_section_index(
                    rows,
                    verbosity=si_verbosity,
                    total_sections=total,
                    all_tags=all_tags,
                )
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


async def inject_workspace_rag(
    messages: list[dict],
    bot: BotConfig,
    ch_row: Any | None,
    channel_id: uuid.UUID | None,
    user_message: str,
    correlation_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    client_id: str | None,
    ledger: Any,
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
        assert plan is not None
        fs_chunks, fs_sim = await retrieve_filesystem_context(
            user_message,
            bot.id,
            roots=list(plan.roots),
            threshold=plan.similarity_threshold,
            top_k=plan.top_k,
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
                        correlation_id=correlation_id,
                        session_id=session_id,
                        bot_id=bot.id,
                        client_id=client_id,
                        event_type="fs_context",
                        count=len(fs_chunks),
                        data={"preview": fs_chunks[0][:200], "best_similarity": _safe_sim(fs_sim)},
                    ))
                messages.append({"role": "system", "content": body})
                budget_consume("fs_context", body)
                _mark_injection_decision(inject_decisions, "workspace_rag", "admitted")
            else:
                _mark_injection_decision(inject_decisions, "workspace_rag", "skipped_by_budget")
                logger.info(
                    "Budget: skipping workspace fs RAG (%d chunks, budget remaining: %d)",
                    len(fs_chunks),
                    budget.remaining if budget else 0,
                )
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
                    correlation_id=correlation_id,
                    session_id=session_id,
                    bot_id=bot.id,
                    client_id=client_id,
                    event_type="fs_context",
                    count=len(fs_chunks),
                    data={"preview": fs_chunks[0][:200], "best_similarity": _safe_sim(fs_sim)},
                ))
            messages.append({"role": "system", "content": body})
            budget_consume("fs_context", body)
            _mark_injection_decision(inject_decisions, "workspace_rag", "admitted")
        else:
            _mark_injection_decision(inject_decisions, "workspace_rag", "skipped_empty")


async def inject_bot_knowledge_base(
    messages: list[dict],
    bot: BotConfig,
    user_message: str,
    ledger: Any,
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
        assert plan is not None
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
