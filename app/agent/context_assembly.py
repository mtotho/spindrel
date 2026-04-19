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
from app.agent.context import set_ephemeral_delegates, set_ephemeral_skills
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
) -> str:
    """Render the channel workspace helper prompt from the configured template.

    Uses CHANNEL_WORKSPACE_PROMPT if set, otherwise DEFAULT_CHANNEL_WORKSPACE_PROMPT.
    Template placeholders: {workspace_path}, {channel_id}, {data_listing}.
    Falls back to appending a plain header if format_map fails.
    """
    from app.config import DEFAULT_CHANNEL_WORKSPACE_PROMPT

    template = settings.CHANNEL_WORKSPACE_PROMPT.strip() or DEFAULT_CHANNEL_WORKSPACE_PROMPT
    replacements = {
        "workspace_path": workspace_path,
        "channel_id": channel_id,
        "data_listing": data_listing,
    }
    try:
        return template.format_map(replacements)
    except (KeyError, ValueError) as exc:
        logger.warning(
            "Failed to render CHANNEL_WORKSPACE_PROMPT (%s), using fallback", exc,
        )
        return DEFAULT_CHANNEL_WORKSPACE_PROMPT.format_map(replacements)


def _compact_tool_usage(name: str, fn: dict[str, Any]) -> str:
    """Build a compact usage hint like: tool_name(required, [optional]) — description."""
    params = fn.get("parameters", {})
    props = params.get("properties", {})
    required = set(params.get("required", []))
    parts: list[str] = []
    for p in props:
        parts.append(p if p in required else f"[{p}]")
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


async def _inject_memory_scheme(
    messages: list[dict],
    bot: BotConfig,
    inject_chars: dict[str, int],
    budget_consume: Any,
    injected_paths: set[str],
) -> AsyncGenerator[dict[str, Any], None]:
    """Inject memory scheme files (MEMORY.md, daily logs, reference index).

    Populates `injected_paths` with relative paths of injected files (for fs RAG dedup).
    """
    import os
    from datetime import date, timedelta

    from app.services.memory_scheme import get_memory_root, get_memory_index_prefix, get_memory_rel_path
    from app.services.workspace import workspace_service
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
                yield {"type": "memory_scheme_bootstrap", "chars": len(content)}

                line_count = content.count("\n") + 1
                if settings.MEMORY_MD_NUDGE_THRESHOLD > 0 and line_count > settings.MEMORY_MD_NUDGE_THRESHOLD:
                    messages.append({
                        "role": "system",
                        "content": (
                            f"[Memory housekeeping] Your MEMORY.md is {line_count} lines "
                            f"(threshold: {settings.MEMORY_MD_NUDGE_THRESHOLD}). "
                            "Consider pruning stale entries, merging duplicates, or moving detailed "
                            "notes to reference/ files to keep MEMORY.md concise and fast to scan."
                        ),
                    })

        # 2. Today's daily log
        today = date.today().isoformat()
        today_path = os.path.join(mem_root, "logs", f"{today}.md")
        if os.path.isfile(today_path):
            content = Path(today_path).read_text()
            if content.strip():
                inject_chars["memory_today_log"] = len(content)
                messages.append({
                    "role": "system",
                    "content": f"Today's daily log ({mem_file_rel}/logs/{today}.md):\n\n{content}",
                })
                injected_paths.add(f"{mem_rel}/logs/{today}.md")
                yield {"type": "memory_scheme_today_log", "chars": len(content)}

        # 3. Yesterday's daily log
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        yesterday_path = os.path.join(mem_root, "logs", f"{yesterday}.md")
        if os.path.isfile(yesterday_path):
            content = Path(yesterday_path).read_text()
            if content.strip():
                inject_chars["memory_yesterday_log"] = len(content)
                messages.append({
                    "role": "system",
                    "content": f"Yesterday's daily log ({mem_file_rel}/logs/{yesterday}.md):\n\n{content}",
                })
                injected_paths.add(f"{mem_rel}/logs/{yesterday}.md")
                yield {"type": "memory_scheme_yesterday_log", "chars": len(content)}

        # 4. List reference/ files
        ref_dir = os.path.join(mem_root, "reference")
        if os.path.isdir(ref_dir):
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
                messages.append({
                    "role": "system",
                    "content": f"Reference documents in {mem_file_rel}/reference/ (use get_memory_file to read):\n"
                               + "\n".join(ref_entries),
                })
                yield {"type": "memory_scheme_reference_index", "count": len(ref_files)}

        # 5. List loose .md files in memory/ root (not MEMORY.md, not dirs)
        _skip = {"MEMORY.md"}
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
            messages.append({
                "role": "system",
                "content": (
                    f"Other files in {mem_file_rel}/ (use file(read) to access):\n"
                    + "\n".join(loose_entries)
                    + f"\n\nTip: consider moving these to {mem_file_rel}/reference/ "
                    "so they appear in the reference index."
                ),
            })
            yield {"type": "memory_scheme_loose_files", "count": len(loose_files)}

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
            messages.append({
                "role": "system",
                "content": (
                    f"[Memory reminder] {user_turns_since_memory_write} user messages since your "
                    "last memory write. If the user stated any preferences, corrections, facts, "
                    "or decisions, write them to memory NOW — they will be lost on compaction."
                ),
            })
            yield {"type": "memory_scheme_nudge", "turns_since_write": user_turns_since_memory_write}

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
    inject_chars: dict[str, int],
    budget_consume: Any,
) -> AsyncGenerator[dict[str, Any], None]:
    """Inject channel workspace files, data listing, schema, index segments, and plan stall detection."""
    import os
    import time

    from app.services.channel_workspace import get_channel_workspace_root, ensure_channel_workspace

    ch_id = str(ch_row.id)

    try:
        ensure_channel_workspace(ch_id, bot, display_name=ch_row.name)
        cw_root = get_channel_workspace_root(ch_id, bot)

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
        cw_abs = f"/workspace/channels/{ch_id}"
        helper = _render_channel_workspace_prompt(
            workspace_path=cw_abs, channel_id=ch_id, data_listing=data_listing,
        )
        if schema_content:
            helper = schema_content + "\n\n" + helper

        body = ""
        if cw_files:
            sections = [f"## {cw_abs}/{fname}\n\n{fcontent}" for fname, fcontent in cw_files]
            body = "\n\n---\n\n".join(sections)

        inject_chars["channel_workspace"] = total_chars
        full = helper + body
        messages.append({"role": "system", "content": full})
        budget_consume("channel_workspace", full)
        yield {"type": "channel_workspace_context", "count": len(cw_files), "chars": total_chars}

        # Background re-index
        from app.services.channel_workspace_indexing import index_channel_workspace
        cw_segments = getattr(ch_row, "index_segments", None) or []
        asyncio.create_task(index_channel_workspace(ch_id, bot, channel_segments=cw_segments if cw_segments else None))

        # Channel index segment RAG retrieval.
        # Always include the implicit channels/{id}/knowledge-base/ segment so the
        # convention-based KB folder is retrievable without any configuration.
        try:
            from app.agent.fs_indexer import retrieve_filesystem_context
            from app.services.workspace_indexing import resolve_indexing
            ws_res = resolve_indexing(bot.workspace.indexing, bot._workspace_raw, bot._ws_indexing_config)

            implicit_kb_prefix = f"channels/{ch_id}/knowledge-base"
            seg_dicts: list[dict] = [{
                "path_prefix": implicit_kb_prefix,
                "embedding_model": ws_res["embedding_model"],
            }]
            for seg in cw_segments:
                explicit_prefix = f"channels/{ch_id}/{seg['path_prefix'].strip('/')}"
                if explicit_prefix.rstrip("/") == implicit_kb_prefix:
                    continue  # user's explicit segment wins, don't double-register
                seg_dicts.append({
                    "path_prefix": explicit_prefix,
                    "embedding_model": seg.get("embedding_model") or ws_res["embedding_model"],
                })

            seg_top_k = max((seg.get("top_k", 8) for seg in cw_segments), default=8)
            seg_threshold = min((seg.get("similarity_threshold", 0.35) for seg in cw_segments), default=0.35)
            chunks, sim = await retrieve_filesystem_context(
                user_message, f"channel:{ch_row.id}",
                roots=[str(Path(cw_root).parent.parent)],
                embedding_model=ws_res["embedding_model"],
                segments=seg_dicts,
                top_k=seg_top_k,
                threshold=seg_threshold,
            )
            if chunks:
                seg_body = "\n\n".join(chunks)
                header_label = "channel knowledge base" if not cw_segments else "channel knowledge base and indexed directories"
                seg_header = f"Relevant excerpts from the {header_label}:\n\n"
                if "search_channel_knowledge" in bot.local_tools:
                    seg_header += "(Call search_channel_knowledge for targeted lookups beyond these auto-retrieved excerpts.)\n\n"
                elif "search_workspace" in bot.local_tools:
                    seg_header += "(Use search_workspace for targeted searches beyond these auto-retrieved excerpts.)\n\n"
                messages.append({"role": "system", "content": seg_header + seg_body})
                inject_chars["channel_index_segments"] = len(seg_body)
                yield {"type": "channel_index_segments", "count": len(chunks), "similarity": sim}
        except Exception:
            logger.warning("Failed to retrieve channel knowledge-base / index segments for channel %s", ch_row.id, exc_info=True)

    except Exception:
        logger.warning("Failed to inject channel workspace files for channel %s", ch_row.id, exc_info=True)

    # Plan stall detection
    try:
        plans_path = os.path.join(get_channel_workspace_root(ch_id, bot), "plans.md")
        if os.path.isfile(plans_path):
            plans_age = time.time() - os.path.getmtime(plans_path)
            if plans_age > 600:
                plans_content = Path(plans_path).read_text()
                if "[executing]" in plans_content:
                    messages.append({
                        "role": "system",
                        "content": (
                            "Note: plans.md contains an executing plan that may be stalled "
                            "(last modified >10 minutes ago). Check the plan and resume "
                            "the next pending step."
                        ),
                    })
    except Exception:
        pass


async def _inject_conversation_sections(
    messages: list[dict],
    bot: BotConfig,
    ch_row: Any,
    channel_id: uuid.UUID,
    user_message: str,
    inject_chars: dict[str, int],
) -> AsyncGenerator[dict[str, Any], None]:
    """Inject conversation section context (structured mode) or section index (file mode)."""
    from app.db.engine import async_session
    from app.db.models import ConversationSection
    from app.services.compaction import _get_history_mode
    from sqlalchemy import func, select
    from sqlalchemy.orm import defer

    hist_mode = _get_history_mode(bot, ch_row)

    if hist_mode == "structured" and user_message:
        from app.agent.embeddings import embed_text
        from app.agent.vector_ops import halfvec_cosine_distance
        query_vec = await embed_text(user_message)
        async with async_session() as db:
            rows = (await db.execute(
                select(ConversationSection)
                .where(ConversationSection.channel_id == channel_id, ConversationSection.embedding.is_not(None))
                .order_by(halfvec_cosine_distance(ConversationSection.embedding, query_vec))
                .limit(3)
            )).scalars().all()
        if rows:
            texts = [r.transcript if r.transcript else f"## {r.title}\n{r.summary}" for r in rows]
            chars = sum(len(t) for t in texts)
            inject_chars["conversation_sections"] = chars
            messages.append({
                "role": "system",
                "content": "Relevant conversation history sections:\n\n" + "\n\n---\n\n".join(texts),
            })
            yield {"type": "section_context", "count": len(rows), "chars": chars}

    elif hist_mode == "file":
        si_count = getattr(ch_row, "section_index_count", None)
        si_count = si_count if si_count is not None else settings.SECTION_INDEX_COUNT
        if si_count > 0:
            si_verbosity = getattr(ch_row, "section_index_verbosity", None) or settings.SECTION_INDEX_VERBOSITY
            async with async_session() as db:
                rows = (await db.execute(
                    select(ConversationSection)
                    .where(ConversationSection.channel_id == channel_id)
                    .order_by(ConversationSection.sequence.desc())
                    .limit(si_count)
                    .options(defer(ConversationSection.transcript), defer(ConversationSection.embedding))
                )).scalars().all()
                total = (await db.execute(
                    select(func.count())
                    .select_from(ConversationSection)
                    .where(ConversationSection.channel_id == channel_id)
                )).scalar() or 0
                all_tags: list[str] | None = None
                if rows and total > len(rows):
                    tag_rows = (await db.execute(
                        select(ConversationSection.tags)
                        .where(ConversationSection.channel_id == channel_id)
                    )).scalars().all()
                    all_tags = [tag for tags in tag_rows if tags for tag in tags]
            if rows:
                from app.services.compaction import format_section_index
                text = format_section_index(rows, verbosity=si_verbosity, total_sections=total, all_tags=all_tags)
                inject_chars["section_index"] = len(text)
                messages.append({"role": "system", "content": text})
                yield {"type": "section_index_context", "count": len(rows), "chars": len(text)}


async def _inject_workspace_rag(
    messages: list[dict],
    bot: BotConfig,
    ch_row: Any | None,
    channel_id: uuid.UUID | None,
    user_message: str,
    correlation_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    client_id: str | None,
    inject_chars: dict[str, int],
    budget_consume: Any,
    budget_can_afford: Any,
    budget: Any,
    memory_scheme_injected_paths: set[str],
) -> AsyncGenerator[dict[str, Any], None]:
    """Inject workspace filesystem RAG context (current and legacy paths)."""
    from app.agent.fs_indexer import retrieve_filesystem_context

    do_rag = False
    if bot.workspace.enabled and bot.workspace.indexing.enabled:
        channel_rag = True
        if ch_row is not None and not getattr(ch_row, "workspace_rag", True):
            channel_rag = False
        do_rag = channel_rag

    if do_rag:
        from app.services.workspace_indexing import resolve_indexing, get_all_roots
        resolved = resolve_indexing(bot.workspace.indexing, bot._workspace_raw, bot._ws_indexing_config)
        fs_chunks, fs_sim = await retrieve_filesystem_context(
            user_message, bot.id, roots=get_all_roots(bot),
            threshold=resolved["similarity_threshold"], top_k=resolved["top_k"],
            embedding_model=resolved["embedding_model"],
            segments=resolved.get("segments"),
            channel_id=str(channel_id) if channel_id else None,
        )
        if memory_scheme_injected_paths:
            fs_chunks = [c for c in fs_chunks if not any(p in c for p in memory_scheme_injected_paths)]
        if fs_chunks:
            body = (
                "Relevant workspace file excerpts (partial segments — "
                "use the file tool with operation=\"read\" to read full file contents):\n\n"
                + "\n\n---\n\n".join(fs_chunks)
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
            else:
                logger.info("Budget: skipping workspace fs RAG (%d chunks, budget remaining: %d)",
                           len(fs_chunks), budget.remaining if budget else 0)

    elif bot.filesystem_indexes:
        fs_threshold = min(
            (cfg.similarity_threshold for cfg in bot.filesystem_indexes if cfg.similarity_threshold is not None),
            default=None,
        )
        fs_chunks, fs_sim = await retrieve_filesystem_context(user_message, bot.id, threshold=fs_threshold)
        if fs_chunks:
            yield {"type": "fs_context", "count": len(fs_chunks)}
            if correlation_id is not None:
                asyncio.create_task(_record_trace_event(
                    correlation_id=correlation_id, session_id=session_id,
                    bot_id=bot.id, client_id=client_id,
                    event_type="fs_context", count=len(fs_chunks),
                    data={"preview": fs_chunks[0][:200], "best_similarity": _safe_sim(fs_sim)},
                ))
            messages.append({
                "role": "system",
                "content": (
                    "Relevant file excerpts from indexed directories (partial segments — "
                    "use the file tool with operation=\"read\" to read full file contents):\n\n"
                    + "\n\n---\n\n".join(fs_chunks)
                ),
            })


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

    _inject_chars: dict[str, int] = {}

    def _budget_consume(category: str, text: str) -> None:
        """Record consumption in the budget if one is active."""
        if budget is not None:
            from app.agent.context_budget import estimate_tokens
            budget.consume(category, estimate_tokens(text))

    def _budget_can_afford(text: str) -> bool:
        """Check if the budget can accommodate this content."""
        if budget is None:
            return True
        from app.agent.context_budget import estimate_tokens
        return budget.can_afford(estimate_tokens(text))

    # --- account for pre-existing messages (system prompt + conversation history) ---
    if budget is not None:
        from app.agent.context_budget import estimate_tokens
        _existing_tokens = sum(
            estimate_tokens(m.get("content", "") if isinstance(m.get("content"), str) else str(m.get("content", "")))
            for m in messages
        )
        budget.consume("conversation_history", _existing_tokens)

    # --- channel-level tool/skill overrides ---
    _ch_row = None
    if channel_id is not None:
        try:
            from sqlalchemy import select as _sa_select
            from sqlalchemy.orm import selectinload as _selectinload
            from app.db.engine import async_session
            from app.db.models import Channel, ChannelIntegration
            async with async_session() as _ch_db:
                _ch_result = await _ch_db.execute(
                    _sa_select(Channel)
                    .where(Channel.id == channel_id)
                    .options(_selectinload(Channel.integrations))
                )
                _ch_row = _ch_result.scalar_one_or_none()
        except Exception:
            logger.warning("Failed to load channel %s for context assembly, continuing without overrides", channel_id, exc_info=True)

    # --- context pruning (trim stale tool results) ---
    _pruning_enabled = settings.CONTEXT_PRUNING_ENABLED
    _pruning_min_len = settings.CONTEXT_PRUNING_MIN_LENGTH
    # Bot-level override
    if bot.context_pruning is not None:
        _pruning_enabled = bot.context_pruning
    # Channel-level override (highest priority)
    if _ch_row is not None:
        if getattr(_ch_row, "context_pruning", None) is not None:
            _pruning_enabled = _ch_row.context_pruning

    if _pruning_enabled:
        from app.agent.context_pruning import prune_tool_results
        _prune_stats = prune_tool_results(messages, min_content_length=_pruning_min_len)
        if _prune_stats["pruned_count"] > 0:
            _inject_chars["context_pruning_saved"] = -_prune_stats["chars_saved"]
            # Reduce budget to reflect actual post-pruning content
            # (inlined estimate_tokens formula to avoid allocating huge temp string)
            if budget is not None:
                budget.consume("context_pruning_savings", -max(1, int(_prune_stats["chars_saved"] / 3.5)))
            yield {
                "type": "context_pruning",
                "scope": "turn_boundary",
                "pruned_count": _prune_stats["pruned_count"],
                "chars_saved": _prune_stats["chars_saved"],
                "turns_pruned": _prune_stats["turns_pruned"],
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
                        "min_length": _pruning_min_len,
                    },
                ))

    if _ch_row is not None:
        _eff = resolve_effective_tools(bot, _ch_row)
        _eff = apply_auto_injections(_eff, bot)
        # Member bots keep their own carapaces — channel-level
        # carapaces_extra are for the primary bot's role.
        _is_member_bot = (
            _ch_row is not None
            and getattr(_ch_row, "bot_id", None)
            and bot.id != _ch_row.bot_id
        )
        _eff_carapaces = list(bot.carapaces or []) if _is_member_bot else _eff.carapaces
        bot = _dc_replace(
            bot,
            local_tools=_eff.local_tools,
            mcp_servers=_eff.mcp_servers,
            client_tools=_eff.client_tools,
            pinned_tools=_eff.pinned_tools,
            skills=_eff.skills,
            carapaces=_eff_carapaces,
        )
        if _ch_row.model_override:
            result.channel_model_override = _ch_row.model_override
            result.channel_provider_id_override = _ch_row.model_provider_id_override
        if _ch_row.max_iterations is not None:
            result.channel_max_iterations = _ch_row.max_iterations
        if _ch_row.fallback_models:
            result.channel_fallback_models = _ch_row.fallback_models
        if _ch_row.model_tier_overrides:
            result.channel_model_tier_overrides = _ch_row.model_tier_overrides
    else:
        # No channel — still apply auto-injections to bot defaults
        _eff = EffectiveTools(
            local_tools=list(bot.local_tools),
            mcp_servers=list(bot.mcp_servers),
            client_tools=list(bot.client_tools),
            pinned_tools=list(bot.pinned_tools),
            skills=list(bot.skills),
            carapaces=list(bot.carapaces or []),
        )
        _eff = apply_auto_injections(_eff, bot)
        bot = _dc_replace(
            bot,
            local_tools=_eff.local_tools,
            pinned_tools=_eff.pinned_tools,
        )

    # --- auto-inject carapaces from activated integrations ---
    if _ch_row is not None:
        _ch_carapaces_disabled = set(getattr(_ch_row, "carapaces_disabled", None) or [])
        try:
            from integrations import get_activation_manifests
            _manifests = get_activation_manifests()
            from app.services.integration_settings import is_active as _intg_active
            for _ci in (getattr(_ch_row, "integrations", None) or []):
                if not _ci.activated:
                    continue
                if not _intg_active(_ci.integration_type):
                    continue
                _manifest = _manifests.get(_ci.integration_type)
                if not _manifest:
                    continue
                for _cap_id in _manifest.get("carapaces", []):
                    if _cap_id not in (bot.carapaces or []) and _cap_id not in _ch_carapaces_disabled:
                        bot = _dc_replace(bot, carapaces=list(bot.carapaces or []) + [_cap_id])
        except Exception:
            logger.warning("Failed to inject activation carapaces", exc_info=True)

    # --- merge session-activated capabilities into bot's carapace list ---
    _session_cap_ids: set[str] = set()
    if correlation_id is not None:
        from app.agent.capability_session import get_activated as _get_cap_activated
        _session_cap_ids = _get_cap_activated(str(correlation_id))
        if _session_cap_ids:
            _existing_caps = set(bot.carapaces or [])
            _ch_caps_disabled = set(getattr(_ch_row, "carapaces_disabled", None) or []) if _ch_row else set()
            _new_session_caps = [
                cid for cid in _session_cap_ids
                if cid not in _existing_caps and cid not in _ch_caps_disabled
            ]
            if _new_session_caps:
                bot = _dc_replace(bot, carapaces=list(bot.carapaces or []) + _new_session_caps)
                yield {"type": "session_capabilities_merged", "count": len(_new_session_caps), "ids": _new_session_caps}

    # --- carapace resolution ---
    _carapace_ids = list(bot.carapaces or [])
    if _carapace_ids:
        from app.agent.carapaces import resolve_carapaces as _resolve_carapaces
        _resolved_c = _resolve_carapaces(_carapace_ids)
        # Merge tools (deduplicate). Carapaces no longer carry skills — skills
        # live in the per-bot working set; carapace fragments surface them via
        # get_skill() pointers in their Deep Knowledge tables.
        _existing_tools = set(bot.local_tools)
        _new_local = [t for t in _resolved_c.local_tools if t not in _existing_tools]
        _existing_mcp = set(bot.mcp_servers)
        _new_mcp = [t for t in _resolved_c.mcp_tools if t not in _existing_mcp]
        # Inject MCP servers from activated integrations
        try:
            from app.services.integration_manifests import collect_integration_mcp_servers
            _int_mcp = collect_integration_mcp_servers(
                getattr(_ch_row, "integrations", None),
                exclude=_existing_mcp | set(_new_mcp),
            )
            _new_mcp.extend(_int_mcp)
        except ImportError:
            pass
        _existing_pinned = set(bot.pinned_tools)
        _new_pinned = [t for t in _resolved_c.pinned_tools if t not in _existing_pinned]
        # Re-apply channel disabled lists so carapaces can't bypass channel restrictions
        if _ch_row is not None:
            _ch_tools_disabled = set(getattr(_ch_row, "local_tools_disabled", None) or [])
            _ch_mcp_disabled = set(getattr(_ch_row, "mcp_servers_disabled", None) or [])
            if _ch_tools_disabled:
                _new_local = [t for t in _new_local if t not in _ch_tools_disabled]
            if _ch_mcp_disabled:
                _new_mcp = [t for t in _new_mcp if t not in _ch_mcp_disabled]
        bot = _dc_replace(
            bot,
            local_tools=list(bot.local_tools) + _new_local,
            mcp_servers=list(bot.mcp_servers) + _new_mcp,
            pinned_tools=list(bot.pinned_tools) + _new_pinned,
        )

        # Inject system prompt fragments
        if _resolved_c.system_prompt_fragments:
            _carapace_prompt = "\n\n".join(_resolved_c.system_prompt_fragments)
            _inject_chars["carapace_prompts"] = len(_carapace_prompt)
            messages.append({
                "role": "system",
                "content": _carapace_prompt,
            })
            _budget_consume("carapace_prompts", _carapace_prompt)
            yield {"type": "carapace_context", "count": len(_carapace_ids), "chars": len(_carapace_prompt)}

    # --- capability auto-discovery index (RAG-based) ---
    # Retrieve semantically relevant capabilities for the user's message,
    # excluding already-active and disabled ones.
    _cap_index_ids: list[str] = []
    try:
        _active_cap_ids = set(_carapace_ids) if _carapace_ids else set()
        _globally_disabled_raw = getattr(settings, "CAPABILITIES_DISABLED", "") or ""
        _globally_disabled = {s.strip() for s in _globally_disabled_raw.split(",") if s.strip()}
        _ch_caps_disabled_set = set(getattr(_ch_row, "carapaces_disabled", None) or []) if _ch_row else set()
        _cap_excluded = _active_cap_ids | _globally_disabled | _ch_caps_disabled_set

        from app.agent.capability_rag import retrieve_capabilities as _retrieve_caps
        _cap_query = (user_message or "").strip()
        _cap_results: list[dict] = []
        if _cap_query:
            _cap_results, _cap_best_sim = await _retrieve_caps(
                _cap_query, excluded_ids=_cap_excluded,
            )

        if _cap_results:
            _cap_lines: list[str] = []
            for _cr in _cap_results:
                _cid = _cr["id"]
                _cname = _cr["name"]
                _cdesc = _cr.get("description") or ""
                _cap_lines.append(f"- {_cid}: {_cname}" + (f" — {_cdesc}" if _cdesc else ""))
                _cap_index_ids.append(_cid)

            _cap_index_content = (
                "Available capabilities (not yet active). "
                "Call activate_capability(id=\"<id>\", reason=\"...\") to load one for this session:\n"
                + "\n".join(_cap_lines)
            )
            if _budget_can_afford(_cap_index_content):
                messages.append({"role": "system", "content": _cap_index_content})
                _budget_consume("capability_index", _cap_index_content)
                _inject_chars["capability_index"] = len(_cap_index_content)
                yield {"type": "capability_index", "count": len(_cap_lines)}

                # activate_capability tool already injected by apply_auto_injections()
    except Exception:
        logger.warning("Failed to build capability index", exc_info=True)

    # --- skill enrollment loading (Phase 3 working set model) ---
    #
    # Replaces three former per-turn blocks (bot-authored discovery, core
    # auto-enrollment, integration auto-enrollment) with a single load from
    # `bot_skill_enrollment`. The table is the source of truth for "what
    # skills does this bot know about".
    #
    # Bot-authored skills are still discovered every turn (they appear/dis-
    # appear with file edits) but the discovery now writes a persistent
    # enrollment row instead of merging into the per-turn bot.skills list
    # directly. The merge happens via the enrolled-list load below.
    if bot.id:
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
        _source_map: dict[str, str] = {}
        try:
            _enrolled_ids = await _get_enrolled_skill_ids(bot.id)
            _source_map = await _get_enrolled_source_map(bot.id)
            if _enrolled_ids:
                _prev = len(bot.skills)
                bot = _merge_skills(bot, _enrolled_ids)
                if len(bot.skills) > _prev:
                    yield {"type": "enrolled_skills", "count": len(bot.skills) - _prev}
        except Exception:
            logger.warning("Failed to load enrolled skills for %s", bot.id, exc_info=True)

    # --- memory scheme: file injection ---
    # NOTE: memory-scheme TOOL injection (search_memory, file, etc.) is handled
    # by apply_auto_injections() above. This section only does file/context injection.
    _memory_scheme_injected_paths: set[str] = set()
    if bot.memory_scheme == "workspace-files":
        async for evt in _inject_memory_scheme(
            messages, bot, _inject_chars, _budget_consume, _memory_scheme_injected_paths,
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
            messages, bot, _ch_row, user_message, _inject_chars, _budget_consume,
        ):
            yield evt

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
    _tagged_tool_names = [t.name for t in _tagged if t.tag_type == "tool"]
    _tagged_bot_names = [t.name for t in _tagged if t.tag_type == "bot"]
    result.tagged_tool_names = _tagged_tool_names
    result.tagged_bot_names = _tagged_bot_names
    if _tagged_bot_names:
        set_ephemeral_delegates(_tagged_bot_names)
    if _tagged_skill_names:
        # Merge with any pre-set ephemeral skills (e.g. from execution_config)
        from app.agent.context import current_ephemeral_skills
        _existing_skills = list(current_ephemeral_skills.get() or [])
        _merged = list(dict.fromkeys(_existing_skills + _tagged_skill_names))
        set_ephemeral_skills(_merged)

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

    # --- execution_config ephemeral skills (not already @-tagged or in bot.skills) ---
    from app.agent.context import current_ephemeral_skills
    _ephemeral_skill_ids = list(current_ephemeral_skills.get() or [])
    _bot_skill_ids = {s.id for s in bot.skills}
    _untagged_ephemeral = [
        s for s in _ephemeral_skill_ids
        if s not in _tagged_skill_names and s not in _bot_skill_ids
    ]
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

    # --- skills (Phase 3 working set + semantic discovery layer + ranking) ---
    #
    # Three layers, each gated independently:
    #   1. Working set — relevance-ranked list of enrolled skills. When ranking
    #      is enabled and there's a user_message, skills are sorted by semantic
    #      similarity and the top matches are marked as relevant.
    #   2. Auto-inject — highest-confidence enrolled skill has its content
    #      pre-loaded into context (eliminates get_skill round-trip).
    #   3. Discovery — semantic retrieval over UNENROLLED catalog skills.
    #
    # Each section runs in its own try/except so a failure in one doesn't
    # kill the other or hang the event loop on teardown.
    _enrolled_rows: list = []
    _suggestion_rows: list = []
    _enrolled_ids: list[str] = []
    _ranked_relevant: list[str] = []
    _auto_injected: list[str] = []
    _auto_injected_similarities: dict[str, float] = {}
    _history_fetched_skills: set[str] = set()
    _skipped_in_history: list[str] = []
    _tool_discovery_info: dict[str, Any] = {"tool_retrieval_enabled": False}
    _skipped_budget: list[str] = []

    if bot.id:
        from app.agent.rag import (
            retrieve_skill_index as _retrieve_skill_index,
            rank_enrolled_skills as _rank_enrolled_skills,
            fetch_skill_chunks_by_id as _fetch_skill_chunks,
        )
        from sqlalchemy import select as _sa_select
        from app.db.engine import async_session as _async_session
        from app.db.models import Skill as _SkillRow

        # Scan conversation history for skills already fetched via get_skill().
        # Unconditional — the set drives auto-inject dedup below AND the UI
        # "skills still in context" orb via result.active_skills. Runs even for
        # bots with no enrolled skills (catalog skills can still be fetched).
        for _hmsg in messages:
            if _hmsg.get("role") == "assistant" and _hmsg.get("tool_calls"):
                for _htc in _hmsg["tool_calls"]:
                    _hfn = _htc.get("function") or {}
                    if _hfn.get("name") == "get_skill":
                        try:
                            _hargs = json.loads(_hfn.get("arguments", "{}"))
                            if _hargs.get("skill_id"):
                                _history_fetched_skills.add(_hargs["skill_id"])
                        except (json.JSONDecodeError, TypeError):
                            pass

        def _fmt_skill_line(r, *, relevant: bool = False) -> str:
            prefix = "↑" if relevant else "-"
            parts = [f"{prefix} {r.id}: {r.name}"]
            if r.description:
                parts.append(f" — {r.description}")
            if r.triggers:
                parts.append(f" [{', '.join(r.triggers)}]")
            return "".join(parts)

        # Working set: load metadata for already-enrolled skills.
        if bot.skills:
            _enrolled_ids = [s.id for s in bot.skills]
            try:
                async with _async_session() as _db:
                    _enrolled_rows = (await _db.execute(
                        _sa_select(_SkillRow.id, _SkillRow.name, _SkillRow.description, _SkillRow.triggers)
                        .where(_SkillRow.id.in_(_enrolled_ids))
                    )).all()
            except Exception:
                logger.warning("Skill working-set load failed", exc_info=True)
                _enrolled_rows = []

            if _enrolled_rows:
                # Rank enrolled skills by relevance when enabled and we have a query.
                # Use recent conversation context (last 3 user/assistant messages) for
                # the ranking query so multi-turn topic continuity is preserved — "what
                # about timing?" in a sourdough conversation still matches sourdough skills.
                _ranking: list[dict] = []
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
                    # Build a map for ordering + relevance flag
                    _rank_map = {r["skill_id"]: r for r in _ranking}
                    _ranked_relevant = [r["skill_id"] for r in _ranking if r["relevant"]]
                    # Sort rows by similarity (highest first)
                    _row_map = {r.id: r for r in _enrolled_rows}
                    _sorted_ids = [r["skill_id"] for r in _ranking if r["skill_id"] in _row_map]
                    # Append any rows not in ranking results (shouldn't happen, but safe)
                    for r in _enrolled_rows:
                        if r.id not in _rank_map:
                            _sorted_ids.append(r.id)

                    _has_relevant = bool(_ranked_relevant)
                    _working_lines = "\n".join(
                        _fmt_skill_line(_row_map[sid], relevant=sid in _ranked_relevant)
                        for sid in _sorted_ids if sid in _row_map
                    )
                    _header = (
                        "BEFORE answering, scan your enrolled skills below. If any plausibly applies, "
                        "call get_skill(skill_id=\"<id>\") FIRST — these lines are an index, NOT content. "
                        "Answering from the description alone is the primary source of bad replies.\n"
                        "Skills marked ↑ are semantically relevant to this message — load them before responding.\n"
                        if _has_relevant else
                        "BEFORE answering, scan your enrolled skills below. If any plausibly applies, "
                        "call get_skill(skill_id=\"<id>\") FIRST — these lines are an index, NOT content:\n"
                    )
                else:
                    # No ranking (disabled, no user_message, or failure) — flat list
                    _working_lines = "\n".join(
                        _fmt_skill_line(r) for r in _enrolled_rows
                    )
                    _header = (
                        "BEFORE answering, scan your enrolled skills below. If any plausibly applies, "
                        "call get_skill(skill_id=\"<id>\") FIRST — these lines are an index, NOT content:\n"
                    )

                messages.append({
                    "role": "system",
                    "content": _header + _working_lines,
                })

                # Auto-inject: record top relevant enrolled skills for synthetic
                # get_skill() injection by the loop (persists in conversation history).
                # Only considers skills that passed the relevance threshold AND
                # aren't already in context from @-tags, ephemeral injection, or
                # prior get_skill() calls in conversation history.
                # Budget-gated: if the skill content doesn't fit, stop.
                if _ranking and settings.SKILL_ENROLLED_AUTO_INJECT_MAX > 0 and not skip_skill_inject:
                    _already_injected = (
                        set(_tagged_skill_names) | set(_untagged_ephemeral) | _history_fetched_skills
                    )
                    _injected_count = 0
                    _inject_threshold = settings.SKILL_ENROLLED_AUTO_INJECT_THRESHOLD
                    for _ri in _ranking:
                        if _injected_count >= settings.SKILL_ENROLLED_AUTO_INJECT_MAX:
                            break
                        if _ri["similarity"] < _inject_threshold:
                            break  # sorted descending — all below are lower
                        # Only authored/fetched/manual skills are injection-eligible;
                        # starter/migration skills are generic utility docs.
                        if _source_map.get(_ri["skill_id"], "starter") not in _INJECT_ELIGIBLE_SOURCES:
                            continue
                        if _ri["skill_id"] in _already_injected:
                            _skipped_in_history.append(_ri["skill_id"])
                            continue
                        try:
                            _ai_chunks = await _fetch_skill_chunks(_ri["skill_id"])
                            if _ai_chunks:
                                _ai_content = "\n\n---\n\n".join(_ai_chunks)
                                # Format to match get_skill() output: "# Name\n\ncontent"
                                _ai_row = _row_map.get(_ri["skill_id"])
                                _ai_name = _ai_row.name if _ai_row else _ri["skill_id"]
                                _ai_formatted = f"# {_ai_name}\n\n{_ai_content}"
                                if not _budget_can_afford(_ai_formatted):
                                    _skipped_budget.append(_ri["skill_id"])
                                    break
                                _budget_consume("auto_inject_skill", _ai_formatted)
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

                    # Emit an event for each auto-injected skill so the UI can display it
                    for _ai in _auto_injected:
                        _ai_row = _row_map.get(_ai)
                        _ai_sim = next((r["similarity"] for r in _ranking if r["skill_id"] == _ai), 0.0)
                        yield {
                            "type": "auto_inject",
                            "skill_id": _ai,
                            "skill_name": _ai_row.name if _ai_row else _ai,
                            "similarity": _safe_sim(_ai_sim),
                            "source": _source_map.get(_ai, "unknown"),
                        }

        # Discovery layer: semantic retrieval over UNENROLLED catalog skills.
        # Runs even when bot.skills is empty so a fresh / unbackfilled bot can
        # still find skills. Whole block is wrapped so a missing-table error
        # in test environments degrades gracefully without leaking the session.
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

            if _suggestion_rows:
                _disc_lines = "\n".join(
                    _fmt_skill_line(r) for r in _suggestion_rows
                )
                # Label depends on whether the bot has any enrollments yet.
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
                # Thresholds frozen with the trace so the hygiene job can
                # reproduce "ranked relevant" classification without re-reading
                # config (which may drift over the audit window).
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

    # --- API access tools (for bots with scoped API keys) ---
    if bot.api_permissions:
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
        yield {"type": "api_access_tools", "scopes": bot.api_permissions}

    # --- multi-bot channel awareness + member bot injection ---
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

    if _member_bot_ids:
        from app.agent.bots import get_bot as _get_bot_mb
        _participant_lines: list[str] = []

        # Determine the actual primary bot from the channel row
        _primary_bot_id = getattr(_ch_row, "bot_id", None) if _ch_row else None
        _primary_bot_id = _primary_bot_id or bot.id  # fallback if no channel row

        # Build participant list with correct primary/member labels
        _all_bot_ids = [_primary_bot_id] + [mid for mid in _member_bot_ids if mid != _primary_bot_id]
        # If current bot is a member (not the primary), ensure it's in the list
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
        # Primary bots can @-mention other bots; member bots should just respond.
        # system_preamble is set for non-primary bots (routed, mentioned, invoked).
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

    # --- delegate bot index ---
    _all_delegate_ids = list(dict.fromkeys(bot.delegate_bots + _tagged_bot_names + _member_bot_ids))
    _delegate_lines: list[str] = []
    _seen_delegate_ids: set[str] = set()
    if _all_delegate_ids:
        from app.agent.bots import get_bot as _get_bot
        for _did in _all_delegate_ids:
            _seen_delegate_ids.add(_did)
            try:
                _db = _get_bot(_did)
                _desc = (_db.system_prompt or "").strip().splitlines()[0][:120] if _db.system_prompt else ""
                _delegate_lines.append(f"  [bot] {_did} — {_db.name}" + (f": {_desc}" if _desc else ""))
            except Exception:
                _delegate_lines.append(f"  [bot] {_did}")

    # Carapace delegates from resolved carapaces (bot delegates take precedence on conflict)
    if _carapace_ids:
        for _cd in _resolved_c.delegates:
            if _cd.id not in _seen_delegate_ids:
                _seen_delegate_ids.add(_cd.id)
                _label = f"  [{_cd.type}] {_cd.id}"
                if _cd.description:
                    _label += f" — {_cd.description}"
                if _cd.model_tier:
                    _label += f" (tier: {_cd.model_tier})"
                _delegate_lines.append(_label)

    if _delegate_lines:
        _delegate_content = (
            "Available delegates for delegate_to_agent:\n"
            + "\n".join(_delegate_lines)
        )
        if "spawn_subagents" in (bot.local_tools or []):
            _delegate_content += (
                "\n\nFor anonymous parallel grunt work (file scanning, research, summarizing), "
                "use spawn_subagents instead — results return to you without posting to the channel."
            )
        messages.append({
            "role": "system",
            "content": _delegate_content,
        })
        yield {"type": "delegate_index", "count": len(_delegate_lines)}

    # --- DB memory injection REMOVED (deprecated — use memory_scheme='workspace-files') ---
    # --- DB RAG knowledge injection REMOVED (deprecated — use skills/carapaces instead) ---

    # --- conversation section retrieval (structured mode) + section index (file mode) ---
    if channel_id is not None and _ch_row is not None:
        async for evt in _inject_conversation_sections(
            messages, bot, _ch_row, channel_id, user_message, _inject_chars,
        ):
            yield evt

    # --- workspace filesystem context ---
    async for evt in _inject_workspace_rag(
        messages, bot, _ch_row, channel_id, user_message,
        correlation_id, session_id, client_id,
        _inject_chars, _budget_consume, _budget_can_afford, budget,
        _memory_scheme_injected_paths,
    ):
        yield evt

    # --- tool retrieval (tool RAG) ---
    pre_selected_tools: list[dict[str, Any]] | None = None
    _authorized_names: set[str] | None = None
    if bot.tool_retrieval:
        by_name = await _all_tool_schemas_by_name(bot) if (
            bot.local_tools or bot.mcp_servers or bot.client_tools or bot.pinned_tools
        ) else {}
        # Always include get_tool_info when tool retrieval is on (inspect named tools).
        if "get_tool_info" not in by_name:
            for _gti in get_local_tool_schemas(["get_tool_info"]):
                by_name[_gti["function"]["name"]] = _gti
        # search_tools only makes sense when auto-discovery is on — it searches the
        # FULL pool, not just declared tools. Without discovery, all of the bot's
        # tools are already known; adding search_tools is noise.
        if bot.tool_discovery and "search_tools" not in by_name:
            for _st in get_local_tool_schemas(["search_tools"]):
                by_name[_st["function"]["name"]] = _st
        # Auto-inject get_skill + get_skill_list — skills are shared documents any bot can access
        for _sk_name in ("get_skill", "get_skill_list"):
            if _sk_name not in by_name:
                for _sk_schema in get_local_tool_schemas([_sk_name]):
                    by_name[_sk_schema["function"]["name"]] = _sk_schema
        _authorized_names = set(by_name.keys())
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
        # Filter discovered tools against channel disabled list
        _ch_disabled_tools = set(getattr(_ch_row, "local_tools_disabled", None) or []) if _ch_row else set()
        if _ch_disabled_tools:
            retrieved = [t for t in retrieved if t.get("function", {}).get("name") not in _ch_disabled_tools]
        # Pre-filter discovered tools against unconditional deny policies
        if settings.TOOL_POLICY_ENABLED and retrieved:
            from app.db.engine import async_session as _policy_session_factory
            from app.services.tool_policies import evaluate_tool_policy
            async with _policy_session_factory() as _pol_db:
                _policy_allowed = []
                for _rt in retrieved:
                    _rn = _rt.get("function", {}).get("name")
                    if _rn and _rn not in _authorized_names:
                        # Discovered (not declared) — check deny policy with empty args
                        _decision = await evaluate_tool_policy(_pol_db, bot.id, _rn, {})
                        if _decision.action == "deny":
                            continue
                    _policy_allowed.append(_rt)
                retrieved = _policy_allowed
        # Add discovered tool names to authorized set
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
        # Load enrolled tools (persistent working set) and merge into pinned
        _enrolled_tool_names: list[str] = []
        if bot.id:
            try:
                from app.services.tool_enrollment import get_enrolled_tool_names as _get_enrolled_tools
                _enrolled_tool_names = await _get_enrolled_tools(bot.id)
            except Exception:
                logger.warning("Failed to load enrolled tools for %s", bot.id, exc_info=True)

        if by_name:
            _effective_pinned = list(bot.pinned_tools or []) + _tagged_tool_names + ["get_tool_info"]
            if bot.tool_discovery:
                _effective_pinned.append("search_tools")
            if _enrolled_tool_names:
                _effective_pinned += _enrolled_tool_names
            if bot.skills:
                _effective_pinned += ["get_skill", "get_skill_list"]
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

            # Inject compact usage index for unretrieved tools from bot's declared set
            _retrieved_names = {t["function"]["name"] for t in pre_selected_tools}
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
                # P4: expendable — skip if budget is tight
                if _budget_can_afford(_tool_idx_content):
                    messages.append({"role": "system", "content": _tool_idx_content})
                    _budget_consume("tool_index", _tool_idx_content)
                    yield {"type": "tool_index", "unretrieved_count": len(_unretrieved)}
                else:
                    logger.info("Budget: skipping tool index hints (%d tools)", len(_unretrieved))

            # Capture tool discovery info for discovery_summary event (emitted at end).
            _tool_discovery_info = {
                "tool_retrieval_enabled": True,
                "tool_discovery_enabled": bool(bot.tool_discovery),
                "threshold": th,
                "pool_total": len(by_name),
                "pinned": list(bot.pinned_tools or []),
                "included": sorted(by_name.keys()),
                "enrolled_working_set": list(_enrolled_tool_names),
                "retrieved": [t["function"]["name"] for t in retrieved],
                "retrieved_count": len(retrieved),
                "top_candidates": tool_candidates[:5] if tool_candidates else [],
                "best_similarity": _safe_sim(tool_sim),
                "unretrieved_count": len(_unretrieved) if _unretrieved else 0,
            }
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
    if _injected and _authorized_names is not None:
        _authorized_names.update(t["function"]["name"] for t in _injected)

    # --- capability-gated tool exposure ---
    # Drop tools whose required_capabilities / required_integrations the
    # current channel's bindings can't satisfy. Keeps respond_privately,
    # open_modal, and slack_* surface tools out of the LLM's tool list
    # on channels that can't honor them — rather than letting the agent
    # call the tool and hit a runtime "unsupported" error. Structural
    # fix for the Phase 3/4 Slack-depth bug documented in vault/
    # Architecture Decisions (Channel binding model).
    if _ch_row is not None:
        try:
            from app.agent.capability_gate import build_view
            from app.integrations import renderer_registry as _rreg
            from app.services.dispatch_resolution import resolve_targets as _resolve_targets
            from app.tools.registry import get_tool_capability_requirements

            _targets = await _resolve_targets(_ch_row)
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

            if _authorized_names is not None:
                _dropped = {n for n in _authorized_names if not _tool_is_exposable(n)}
                if _dropped:
                    _authorized_names -= _dropped
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

    result.pre_selected_tools = pre_selected_tools
    result.authorized_tool_names = _authorized_names
    result.effective_local_tools = list(bot.local_tools)

    # --- datetime + conversation-gap framing (injected late to avoid busting prompt cache prefix) ---
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
                # The incoming user message was pre-persisted to the DB by the
                # turn worker before this function runs (see turn_worker.py:
                # _persist_and_publish_user_message). Exclude it from the "most
                # recent" / scan view so we surface the PRIOR turn, which is
                # what conveys the gap.
                _cutoff = _now_utc - timedelta(seconds=5)
                async with _async_session_t() as _tdb:
                    # Pull the recent message window once: content + role + metadata + created_at.
                    # We derive last_human_dt, last_non_human_dt, AND the scan window
                    # from this single query (~15 rows, indexed by session_id).
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
                        # "Non-user activity" = anything the user didn't send: any
                        # assistant/tool message, plus bot-mirrored user-role
                        # messages in multi-bot channels.
                        if not _is_human and _last_non_human_dt is None:
                            _last_non_human_dt = _r.created_at
                        if _is_human and _last_human_dt is None:
                            _last_human_dt = _r.created_at
                        # Feed the scan window.
                        _content = _r.content if isinstance(_r.content, str) else ""
                        if _content:
                            # is_self: True when the assistant turn was authored
                            # by the bot currently running; drives "you" vs
                            # "another bot" attribution in multi-bot sessions.
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
        messages.append({"role": "system", "content": _time_block})
    except Exception:
        pass  # non-fatal if timezone lookup fails

    # --- pinned widget state (stale-but-OK, same cache-safety band as temporal) ---
    try:
        if _ch_row is not None:
            from app.db.engine import async_session as _pw_session
            from app.services.widget_context import (
                build_widget_context_block, fetch_channel_pin_dicts,
            )
            async with _pw_session() as _pw_db:
                _pins = await fetch_channel_pin_dicts(_pw_db, _ch_row.id)
            if _pins:
                _widget_block = build_widget_context_block(_pins, bot_id=bot.id)
                if _widget_block:
                    messages.append({"role": "system", "content": _widget_block})
                    _inject_chars["pinned_widgets"] = len(_widget_block)
    except Exception:
        logger.debug("pinned_widgets: injection failed", exc_info=True)

    # --- tool refusal guard (counters history poisoning from prior "I can't" turns) ---
    # Scans recent assistant turns for refusal phrases. If any are found, injects a
    # corrective system message; if the refusal named a tool that IS now authorized,
    # the message names it specifically. Same cache-safety band as temporal/widgets.
    try:
        if _authorized_names:
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
            _refusal = scan_assistant_refusals(_assistant_contents, set(_authorized_names))
            _guard_block = build_tool_authority_block(_refusal)
            if _guard_block:
                messages.append({"role": "system", "content": _guard_block})
                _inject_chars["tool_refusal_guard"] = len(_guard_block)
                if _refusal.stale_refused:
                    logger.info(
                        "tool_refusal_guard: correcting stale refusals for %s on channel %s",
                        _refusal.stale_refused, channel_id,
                    )
    except Exception:
        logger.debug("tool_refusal_guard: injection failed", exc_info=True)

    # --- channel prompt (injected just before user message) ---
    if channel_id is not None and _ch_row is not None:
        _ch_ws_path = getattr(_ch_row, "channel_prompt_workspace_file_path", None)
        _ch_ws_id = getattr(_ch_row, "channel_prompt_workspace_id", None)
        _ch_inline = getattr(_ch_row, "channel_prompt", None)
        if _ch_ws_path and _ch_ws_id:
            from app.services.prompt_resolution import resolve_workspace_file_prompt
            _ch_prompt = resolve_workspace_file_prompt(str(_ch_ws_id), _ch_ws_path, _ch_inline or "")
        else:
            _ch_prompt = _ch_inline
        if _ch_prompt:
            messages.append({"role": "system", "content": _ch_prompt})
            _inject_chars["channel_prompt"] = len(_ch_prompt)

    # --- system preamble (e.g. heartbeat metadata — injected before user message, after all RAG context) ---
    if system_preamble:
        messages.append({"role": "system", "content": system_preamble})
        _inject_chars["system_preamble"] = len(system_preamble)

    # --- current-turn marker (helps models distinguish injected context from the live message) ---
    if task_mode:
        # Heartbeat or other system-initiated task — frame as executable task, not conversation
        messages.append({
            "role": "system",
            "content": "Everything above is background context. Your TASK PROMPT follows — execute it now.",
        })
    else:
        messages.append({
            "role": "system",
            "content": "Everything above is context and conversation history. The user's CURRENT message follows — respond to it directly.",
        })

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
            _inject_chars["bot_system_prompt_reinforce"] = len(_reinforce)

    # --- user message (audio or text) ---
    if native_audio:
        messages.append({
            "role": "system",
            "content": _AUDIO_TRANSCRIPT_INSTRUCTION,
        })
        user_msg = _build_audio_user_message(audio_data, audio_format)
        messages.append(user_msg)
        result.user_msg_index = len(messages) - 1
    elif user_message:
        from app.security.prompt_sanitize import sanitize_unicode
        user_content = _build_user_message_content(sanitize_unicode(user_message), attachments)
        messages.append({"role": "user", "content": user_content})
        result.user_msg_index = len(messages) - 1
    # When user_message is empty (e.g. member bot replies), no user message is
    # appended — the system_preamble and conversation history are sufficient.

    # --- store budget utilization for downstream (compaction trigger) ---
    if budget is not None:
        result.budget_utilization = budget.utilization

    # --- injection summary trace ---
    if correlation_id is not None and _inject_chars:
        _summary_data: dict[str, Any] = {
            "breakdown": _inject_chars,
            "total_chars": sum(_inject_chars.values()),
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
    if _history_fetched_skills:
        _skill_name_map: dict[str, str] = {r.id: r.name for r in _enrolled_rows}
        _missing_skill_ids = [sid for sid in _history_fetched_skills if sid not in _skill_name_map]
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
        for _sid in sorted(_history_fetched_skills):
            result.active_skills.append({
                "skill_id": _sid,
                "skill_name": _skill_name_map.get(_sid, _sid),
            })

    # --- discovery summary trace (skills + tools, consolidated for at-a-glance) ---
    # Emitted unconditionally so the UI can render a single "what did discovery do
    # this turn" card. Complements the richer skill_index / tool_retrieval events
    # that carry full detail.
    if correlation_id is not None:
        _discovery_data: dict[str, Any] = {
            "skills": {
                "enrolled_count": len(_enrolled_ids),
                "enrolled_in_context": len(_enrolled_rows),
                "relevant_count": len(_ranked_relevant),
                "auto_injected": [
                    {"skill_id": sid, "similarity": _auto_injected_similarities.get(sid, 0.0)}
                    for sid in _auto_injected
                ],
                "discoverable_unenrolled_count": len(_suggestion_rows),
                "auto_inject_threshold": settings.SKILL_ENROLLED_AUTO_INJECT_THRESHOLD,
                "auto_inject_max": settings.SKILL_ENROLLED_AUTO_INJECT_MAX,
                "ranking_enabled": settings.SKILL_ENROLLED_RANKING_ENABLED,
                "history_fetched": sorted(_history_fetched_skills) if _history_fetched_skills else [],
            },
            "tools": _tool_discovery_info,
        }
        asyncio.create_task(_record_trace_event(
            correlation_id=correlation_id,
            session_id=session_id,
            bot_id=bot.id,
            client_id=client_id,
            event_type="discovery_summary",
            data=_discovery_data,
        ))



