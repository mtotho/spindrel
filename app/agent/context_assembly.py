"""Context injection pipeline — assembles RAG context before the agent tool loop."""

import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dataclasses import replace as _dc_replace

from app.agent.bots import BotConfig
from app.agent.channel_overrides import resolve_effective_tools
from app.agent.context import set_ephemeral_delegates, set_ephemeral_skills
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


async def _inject_workspace_skills(
    messages: list[dict],
    workspace_id: str,
    bot_id: str,
    user_message: str,
    inject_chars: dict[str, int],
) -> AsyncGenerator[dict[str, Any], None]:
    """Inject workspace skills (pinned/rag/on-demand) into messages.

    Extracted for testability — called from assemble_context when workspace
    skills are enabled.
    """
    from app.services.workspace_skills import get_workspace_skills_for_bot, SOURCE_PREFIX

    ws_skills = await get_workspace_skills_for_bot(workspace_id, bot_id)

    # Pinned workspace skills: inject full content
    if ws_skills["pinned"]:
        content = "\n\n---\n\n".join(s.content for s in ws_skills["pinned"])
        chars = len(content)
        inject_chars["ws_skill_pinned"] = chars
        messages.append({
            "role": "system",
            "content": f"Workspace pinned skills:\n\n{content}",
        })
        yield {"type": "ws_skill_pinned_context", "count": len(ws_skills["pinned"]), "chars": chars}

    # RAG workspace skills: query from documents table
    if ws_skills["rag"]:
        rag_sources = [
            f"{SOURCE_PREFIX}:{workspace_id}:{s.source_path}"
            for s in ws_skills["rag"]
        ]
        from app.agent.rag import retrieve_context as _ws_retrieve
        _ws_rag_raw, _ = await _ws_retrieve(user_message, sources=rag_sources)
        rag_chunks = [content for content, _src in _ws_rag_raw]
        if rag_chunks:
            chars = sum(len(c) for c in rag_chunks)
            inject_chars["ws_skill_rag"] = chars
            messages.append({
                "role": "system",
                "content": "Relevant workspace skills:\n\n" + "\n\n---\n\n".join(rag_chunks),
            })
            yield {"type": "ws_skill_rag_context", "count": len(rag_chunks), "chars": chars}

    # On-demand workspace skills: inject index
    if ws_skills["on_demand"]:
        od_lines = "\n".join(
            f"- {s.skill_id}: {s.display_name} ({s.source_path})"
            for s in ws_skills["on_demand"]
        )
        messages.append({
            "role": "system",
            "content": (
                f"Available workspace skills — call get_workspace_skill(skill_path=\"<path>\") to retrieve full content:\n{od_lines}"
            ),
        })
        yield {"type": "ws_skill_index", "count": len(ws_skills["on_demand"])}


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

    # --- channel-level tool/skill overrides ---
    _ch_row = None
    if channel_id is not None:
        try:
            from app.db.engine import async_session
            from app.db.models import Channel
            async with async_session() as _ch_db:
                _ch_row = await _ch_db.get(Channel, channel_id)
        except Exception:
            logger.warning("Failed to load channel %s for context assembly, continuing without overrides", channel_id, exc_info=True)

    # --- context pruning (trim stale tool results) ---
    _pruning_enabled = settings.CONTEXT_PRUNING_ENABLED
    _pruning_keep = settings.CONTEXT_PRUNING_KEEP_TURNS
    _pruning_min_len = settings.CONTEXT_PRUNING_MIN_LENGTH
    # Bot-level override
    if bot.context_pruning is not None:
        _pruning_enabled = bot.context_pruning
    if bot.context_pruning_keep_turns is not None:
        _pruning_keep = bot.context_pruning_keep_turns
    # Channel-level override (highest priority)
    if _ch_row is not None:
        if getattr(_ch_row, "context_pruning", None) is not None:
            _pruning_enabled = _ch_row.context_pruning
        if getattr(_ch_row, "context_pruning_keep_turns", None) is not None:
            _pruning_keep = _ch_row.context_pruning_keep_turns

    if _pruning_enabled:
        from app.agent.context_pruning import prune_tool_results
        _prune_stats = prune_tool_results(messages, keep_full_turns=_pruning_keep, min_content_length=_pruning_min_len)
        if _prune_stats["pruned_count"] > 0:
            _inject_chars["context_pruning_saved"] = -_prune_stats["chars_saved"]
            yield {
                "type": "context_pruning",
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
                        "chars_saved": _prune_stats["chars_saved"],
                        "turns_pruned": _prune_stats["turns_pruned"],
                        "keep_turns": _pruning_keep,
                        "min_length": _pruning_min_len,
                    },
                ))

    # --- merge workspace DB skills into bot.skills ---
    if bot.shared_workspace_id:
        try:
            from app.db.engine import async_session as _ws_session
            from app.db.models import SharedWorkspace as _WsSW
            from app.agent.bots import _parse_skill_entry
            async with _ws_session() as _ws_db:
                _ws_row = await _ws_db.get(_WsSW, uuid.UUID(bot.shared_workspace_id))
            if _ws_row and _ws_row.skills:
                _bot_skill_ids = {s.id for s in bot.skills}
                _ws_skills = [_parse_skill_entry(e) for e in _ws_row.skills if
                              (e["id"] if isinstance(e, dict) else e) not in _bot_skill_ids]
                if _ws_skills:
                    bot = _dc_replace(bot, skills=list(bot.skills) + _ws_skills)
        except Exception:
            logger.warning("Failed to load workspace DB skills for %s", bot.shared_workspace_id)

    if _ch_row is not None:
        _eff = resolve_effective_tools(bot, _ch_row)
        bot = _dc_replace(
            bot,
            local_tools=_eff.local_tools,
            mcp_servers=_eff.mcp_servers,
            client_tools=_eff.client_tools,
            pinned_tools=_eff.pinned_tools,
            skills=_eff.skills,
        )
        if _ch_row.model_override:
            result.channel_model_override = _ch_row.model_override
            result.channel_provider_id_override = _ch_row.model_provider_id_override
        if _ch_row.max_iterations is not None:
            result.channel_max_iterations = _ch_row.max_iterations
        if _ch_row.fallback_models:
            result.channel_fallback_models = _ch_row.fallback_models

    # --- memory scheme: tool hiding + tool injection ---
    _memory_scheme_injected_paths: set[str] = set()  # track injected files for fs RAG dedup
    if bot.memory_scheme == "workspace-files":
        _MEMORY_SCHEME_HIDDEN_TOOLS = {
            "save_memory", "search_memories", "purge_memory",
            "merge_memories", "promote_memories_to_knowledge",
            "upsert_knowledge", "append_to_knowledge", "edit_knowledge",
            "delete_knowledge", "get_knowledge", "list_knowledge_bases",
            "search_knowledge", "pin_knowledge", "unpin_knowledge",
            "set_knowledge_similarity_threshold",
        }
        _MEMORY_SCHEME_INJECT_TOOLS = ["search_memory", "get_memory_file", "file"]
        _filtered_tools = [t for t in bot.local_tools if t not in _MEMORY_SCHEME_HIDDEN_TOOLS]
        # Add memory file tools if not already present
        for _mt in _MEMORY_SCHEME_INJECT_TOOLS:
            if _mt not in _filtered_tools:
                _filtered_tools.append(_mt)
        bot = _dc_replace(
            bot,
            local_tools=_filtered_tools,
            pinned_tools=list(dict.fromkeys((bot.pinned_tools or []) + _MEMORY_SCHEME_INJECT_TOOLS)),
        )

    # --- memory scheme: file injection ---
    if bot.memory_scheme == "workspace-files":
        import os as _mem_os
        from datetime import date as _mem_date
        from app.services.memory_scheme import get_memory_root, get_memory_index_prefix
        try:
            from app.services.workspace import workspace_service as _mem_ws
            _mem_ws_root = _mem_ws.get_workspace_root(bot.id, bot)
            _mem_root = get_memory_root(bot, ws_root=_mem_ws_root)
            _mem_rel = get_memory_index_prefix(bot)  # index-relative prefix for FS_CONTEXT exclusion

            # 1. MEMORY.md — always inject
            _mem_md_path = _mem_os.path.join(_mem_root, "MEMORY.md")
            if _mem_os.path.isfile(_mem_md_path):
                _mem_md_content = Path(_mem_md_path).read_text()
                if _mem_md_content.strip():
                    _inject_chars["memory_bootstrap"] = len(_mem_md_content)
                    messages.append({
                        "role": "system",
                        "content": f"Your persistent memory (MEMORY.md — curated stable facts):\n\n{_mem_md_content}",
                    })
                    _memory_scheme_injected_paths.add(f"{_mem_rel}/MEMORY.md")
                    yield {"type": "memory_scheme_bootstrap", "chars": len(_mem_md_content)}

            # 2. Today's daily log
            _today = _mem_date.today().isoformat()
            _today_path = _mem_os.path.join(_mem_root, "logs", f"{_today}.md")
            if _mem_os.path.isfile(_today_path):
                _today_content = Path(_today_path).read_text()
                if _today_content.strip():
                    _inject_chars["memory_today_log"] = len(_today_content)
                    messages.append({
                        "role": "system",
                        "content": f"Today's daily log ({_mem_rel}/logs/{_today}.md):\n\n{_today_content}",
                    })
                    _memory_scheme_injected_paths.add(f"{_mem_rel}/logs/{_today}.md")
                    yield {"type": "memory_scheme_today_log", "chars": len(_today_content)}

            # 3. Yesterday's daily log
            from datetime import timedelta as _mem_td
            _yesterday = (_mem_date.today() - _mem_td(days=1)).isoformat()
            _yesterday_path = _mem_os.path.join(_mem_root, "logs", f"{_yesterday}.md")
            if _mem_os.path.isfile(_yesterday_path):
                _yesterday_content = Path(_yesterday_path).read_text()
                if _yesterday_content.strip():
                    _inject_chars["memory_yesterday_log"] = len(_yesterday_content)
                    messages.append({
                        "role": "system",
                        "content": f"Yesterday's daily log ({_mem_rel}/logs/{_yesterday}.md):\n\n{_yesterday_content}",
                    })
                    _memory_scheme_injected_paths.add(f"{_mem_rel}/logs/{_yesterday}.md")
                    yield {"type": "memory_scheme_yesterday_log", "chars": len(_yesterday_content)}

            # 4. List reference/ files
            _ref_dir = _mem_os.path.join(_mem_root, "reference")
            if _mem_os.path.isdir(_ref_dir):
                _ref_files = sorted(
                    f for f in _mem_os.listdir(_ref_dir)
                    if f.endswith(".md") and _mem_os.path.isfile(_mem_os.path.join(_ref_dir, f))
                )
                if _ref_files:
                    _ref_list = "\n".join(f"  - {f}" for f in _ref_files)
                    messages.append({
                        "role": "system",
                        "content": f"Reference documents in {_mem_rel}/reference/ (use get_memory_file to read):\n{_ref_list}",
                    })
                    yield {"type": "memory_scheme_reference_index", "count": len(_ref_files)}

        except Exception:
            logger.warning("Failed to inject memory scheme files for bot %s", bot.id, exc_info=True)

    # --- channel workspace: file injection + tool injection ---
    if _ch_row is not None and _ch_row.channel_workspace_enabled:
        _CW_TOOLS = ["file", "search_channel_archive", "search_channel_workspace", "list_workspace_channels"]
        # Inject tools
        _cw_filtered = list(bot.local_tools)
        for _cwt in _CW_TOOLS:
            if _cwt not in _cw_filtered:
                _cw_filtered.append(_cwt)
        bot = _dc_replace(
            bot,
            local_tools=_cw_filtered,
            pinned_tools=list(dict.fromkeys((bot.pinned_tools or []) + _CW_TOOLS)),
        )

        # Inject workspace files into context
        try:
            import os as _cw_os
            from app.services.channel_workspace import (
                get_channel_workspace_root,
                ensure_channel_workspace,
            )
            _cw_ch_id = str(_ch_row.id)
            ensure_channel_workspace(_cw_ch_id, bot, display_name=_ch_row.name)
            _cw_root = get_channel_workspace_root(_cw_ch_id, bot)

            _cw_files: list[tuple[str, str]] = []  # (name, content)
            _cw_total_chars = 0
            _CW_BUDGET = 50_000

            if _cw_os.path.isdir(_cw_root):
                for _cw_entry in sorted(_cw_os.scandir(_cw_root), key=lambda e: e.name):
                    if _cw_entry.is_file() and _cw_entry.name.endswith(".md"):
                        try:
                            _cw_content = Path(_cw_entry.path).read_text()
                            if _cw_content.strip():
                                if _cw_total_chars + len(_cw_content) > _CW_BUDGET:
                                    _cw_content = _cw_content[:_CW_BUDGET - _cw_total_chars] + "\n\n[...truncated]"
                                _cw_files.append((_cw_entry.name, _cw_content))
                                _cw_total_chars += len(_cw_content)
                                if _cw_total_chars >= _CW_BUDGET:
                                    break
                        except Exception:
                            pass
            else:
                logger.warning("Channel workspace dir does not exist: %s", _cw_root)

            # List data/ files for awareness
            _cw_data_dir = _cw_os.path.join(_cw_root, "data")
            _cw_data_listing = ""
            if _cw_os.path.isdir(_cw_data_dir):
                _data_entries = sorted(
                    e.name for e in _cw_os.scandir(_cw_data_dir)
                    if e.is_file()
                )
                if _data_entries:
                    _cw_data_listing = "\nData files (data/ — not auto-injected, reference via workspace .md files):\n" + "\n".join(f"  - {n}" for n in _data_entries) + "\n"

            # Resolve workspace schema template (if set)
            _schema_content = ""
            if getattr(_ch_row, "workspace_schema_template_id", None):
                try:
                    from app.services.prompt_resolution import resolve_prompt_template
                    _schema_content = await resolve_prompt_template(
                        str(_ch_row.workspace_schema_template_id), fallback="", db=db,
                    )
                except Exception:
                    logger.warning("Failed to resolve workspace schema template for channel %s", _ch_row.id, exc_info=True)

            # Always inject helper prompt so the agent knows about the workspace
            _cw_abs = f"/workspace/channels/{_cw_ch_id}"
            _cw_helper = _render_channel_workspace_prompt(
                workspace_path=_cw_abs,
                channel_id=_cw_ch_id,
                data_listing=_cw_data_listing,
            )

            if _schema_content:
                _cw_helper = _schema_content + "\n\n" + _cw_helper

            _cw_body = ""
            if _cw_files:
                _cw_sections = []
                for _fname, _fcontent in _cw_files:
                    _cw_sections.append(f"## {_fname}\n\n{_fcontent}")
                _cw_body = "\n\n---\n\n".join(_cw_sections)

            _inject_chars["channel_workspace"] = _cw_total_chars
            messages.append({
                "role": "system",
                "content": _cw_helper + _cw_body,
            })
            yield {"type": "channel_workspace_context", "count": len(_cw_files), "chars": _cw_total_chars}

            # Background re-index (content-hash makes it a no-op if nothing changed)
            from app.services.channel_workspace_indexing import index_channel_workspace as _cw_index
            _cw_segments = getattr(_ch_row, "index_segments", None) or []
            asyncio.create_task(_cw_index(_cw_ch_id, bot, channel_segments=_cw_segments if _cw_segments else None))

            # --- Channel index segment RAG retrieval ---
            if _cw_segments:
                try:
                    from app.agent.fs_indexer import retrieve_filesystem_context as _rfc
                    from app.services.workspace_indexing import resolve_indexing as _ri
                    _sentinel = f"channel:{_ch_row.id}"
                    _ws_res = _ri(bot.workspace.indexing, bot._workspace_raw, bot._ws_indexing_config)
                    _seg_dicts = [{
                        "path_prefix": f"channels/{_cw_ch_id}/{seg['path_prefix'].strip('/')}",
                        "embedding_model": seg.get("embedding_model") or _ws_res["embedding_model"],
                    } for seg in _cw_segments]
                    _seg_top_k = max((seg.get("top_k", 8) for seg in _cw_segments), default=8)
                    _seg_threshold = min((seg.get("similarity_threshold", 0.35) for seg in _cw_segments), default=0.35)
                    _ch_chunks, _ch_sim = await _rfc(
                        user_message,
                        _sentinel,
                        roots=[str(Path(_cw_root).parent.parent)],
                        embedding_model=_ws_res["embedding_model"],
                        segments=_seg_dicts,
                        top_k=_seg_top_k,
                        threshold=_seg_threshold,
                    )
                    if _ch_chunks:
                        _ch_seg_body = "\n\n".join(_ch_chunks)
                        _ch_seg_header = "Relevant code/files from channel indexed directories:\n\n"
                        if "search_workspace" in bot.local_tools:
                            _ch_seg_header += "(Use search_workspace for targeted searches beyond these auto-retrieved excerpts.)\n\n"
                        messages.append({
                            "role": "system",
                            "content": _ch_seg_header + _ch_seg_body,
                        })
                        _inject_chars["channel_index_segments"] = len(_ch_seg_body)
                        yield {"type": "channel_index_segments", "count": len(_ch_chunks), "similarity": _ch_sim}
                except Exception:
                    logger.warning("Failed to retrieve channel index segments for channel %s", _ch_row.id, exc_info=True)

        except Exception:
            logger.warning("Failed to inject channel workspace files for channel %s", _ch_row.id, exc_info=True)

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
    if _tagged_skill_names:
        set_ephemeral_skills(_tagged_skill_names)

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
                _skill_chars = sum(len(c) for c, _ in chunks)
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
                        data={"preview": chunks[0][0][:200], "best_similarity": round(skill_sim, 4), "chars": _skill_chars},
                    ))
                # Format chunks with skill source attribution
                _chunk_texts = []
                for content, source in chunks:
                    _sid = source.removeprefix("skill:")
                    _chunk_texts.append(f"[skill:{_sid}]\n{content}")
                context = "\n\n---\n\n".join(_chunk_texts)
                _skill_ids_in_chunks = list(dict.fromkeys(
                    src.removeprefix("skill:") for _, src in chunks
                ))
                _get_skill_hint = ", ".join(
                    f'get_skill(skill_id="{sid}")' for sid in _skill_ids_in_chunks
                )
                messages.append({
                    "role": "system",
                    "content": (
                        f"Relevant skill context (partial — call {_get_skill_hint} "
                        f"for full content if needed):\n\n{context}"
                    ),
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
                        f"Available skills — call get_skill(skill_id=\"<id>\") to retrieve full content:\n{_index_lines}"
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

    # --- workspace skills ---
    if bot.shared_workspace_id and channel_id is not None:
        from sqlalchemy import select as _ws_select
        from app.db.engine import async_session as _ws_async_session
        from app.db.models import Channel as _WsChannel, SharedWorkspace as _WsSharedWorkspace, SharedWorkspaceBot as _WsSWBot
        _ws_skills_enabled = False
        async with _ws_async_session() as _wsdb:
            _ws_ch = await _wsdb.get(_WsChannel, channel_id)
            if _ws_ch is not None:
                if _ws_ch.workspace_skills_enabled is not None:
                    _ws_skills_enabled = _ws_ch.workspace_skills_enabled
                else:
                    _ws_swb = (await _wsdb.execute(
                        _ws_select(_WsSWBot)
                        .where(_WsSWBot.bot_id == bot.id)
                    )).scalar_one_or_none()
                    if _ws_swb:
                        _ws_row = await _wsdb.get(_WsSharedWorkspace, _ws_swb.workspace_id)
                        if _ws_row:
                            _ws_skills_enabled = _ws_row.workspace_skills_enabled

        if _ws_skills_enabled:
            async for evt in _inject_workspace_skills(
                messages, bot.shared_workspace_id, bot.id, user_message, _inject_chars,
            ):
                yield evt

    # --- dynamic API access docs (for bots with scoped API keys) ---
    if bot.api_permissions and bot.api_docs_mode:
        try:
            _mode = bot.api_docs_mode

            # Always add api_reference to skill index so bot knows it exists
            _api_skill_line = "- api_reference: Agent Server API Reference (auto-generated from your API key scopes)"
            messages.append({
                "role": "system",
                "content": (
                    f"Available skills — call get_skill(skill_id=\"<id>\") to retrieve full content:\n{_api_skill_line}"
                ),
            })

            if _mode == "pinned":
                # Always inject full docs
                from app.services.api_keys import generate_api_docs
                _api_docs = generate_api_docs(bot.api_permissions)
                _api_docs_chars = len(_api_docs)
                _inject_chars["api_docs"] = _api_docs_chars
                messages.append({
                    "role": "system",
                    "content": (
                        "You have a scoped API key for the agent server.\n"
                        "IMPORTANT: `agent-api` is a CLI command — run it via exec_command, "
                        "e.g. exec_command(command=\"agent-api GET /api/v1/channels\"). "
                        "Do NOT try to call `agent_api` as a tool — it does not exist.\n\n"
                        + _api_docs
                    ),
                })
                yield {"type": "api_docs_context", "mode": "pinned", "scopes": bot.api_permissions, "chars": _api_docs_chars}

            elif _mode == "rag":
                # Only inject when the user message is related to API usage
                _api_keywords = {
                    "api", "endpoint", "agent-api", "agent api", "curl", "http",
                    "channel", "channels", "session", "task", "discover",
                    "inject", "message", "server", "request", "post", "get",
                    "delete", "put", "agent docs", "agent discover",
                }
                _user_lower = user_message.lower()
                if any(kw in _user_lower for kw in _api_keywords):
                    from app.services.api_keys import generate_api_docs
                    _api_docs = generate_api_docs(bot.api_permissions)
                    _api_docs_chars = len(_api_docs)
                    _inject_chars["api_docs"] = _api_docs_chars
                    messages.append({
                        "role": "system",
                        "content": (
                            "You have a scoped API key for the agent server.\n"
                            "IMPORTANT: `agent-api` is a CLI command — run it via exec_command, "
                            "e.g. exec_command(command=\"agent-api GET /api/v1/channels\"). "
                            "Do NOT try to call `agent_api` as a tool — it does not exist.\n\n"
                            + _api_docs
                        ),
                    })
                    yield {"type": "api_docs_context", "mode": "rag", "scopes": bot.api_permissions, "chars": _api_docs_chars}
                else:
                    yield {"type": "api_docs_context", "mode": "rag_skipped", "scopes": bot.api_permissions, "chars": 0}

            elif _mode == "on_demand":
                # Just inject a short hint — bot uses get_skill("api_reference") when needed
                _hint = (
                    "You have a scoped API key for the agent server "
                    f"(scopes: {', '.join(bot.api_permissions)}). "
                    "Use `get_skill(\"api_reference\")` to see full API documentation for your permissions. "
                    "IMPORTANT: `agent-api` is a CLI command — run it via exec_command, "
                    "e.g. exec_command(command=\"agent-api GET /path\"). Do NOT call `agent_api` as a tool."
                )
                _inject_chars["api_docs"] = len(_hint)
                messages.append({"role": "system", "content": _hint})
                yield {"type": "api_docs_context", "mode": "on_demand", "scopes": bot.api_permissions, "chars": len(_hint)}

        except Exception:
            logger.warning("Failed to inject API docs for bot %s", bot.id, exc_info=True)

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

    # --- memories (DB-based — skip when using workspace-files scheme) ---
    if bot.memory.enabled and bot.memory_scheme != "workspace-files" and session_id and client_id:
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
                    "Relevant memories (auto-retrieved excerpts — use search_memories for broader recall):\n\n"
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

    # --- RAG knowledge (DB-based — skip when using workspace-files scheme) ---
    if bot.knowledge.enabled and bot.memory_scheme != "workspace-files" and client_id:
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
            messages.append({
                "role": "system",
                "content": (
                    "Relevant knowledge (auto-retrieved excerpts — use get_knowledge(name=\"<name>\") "
                    "for full documents or search_knowledge for broader results):\n\n"
                    + "\n\n---\n\n".join(chunks)
                ),
            })

    # --- conversation section retrieval (structured mode) + tool injection (file mode) ---
    if channel_id is not None:
        from app.db.engine import async_session as _sec_async_session
        from app.db.models import Channel as _SecChannel
        async with _sec_async_session() as _sec_db:
            _sec_ch = await _sec_db.get(_SecChannel, channel_id)
        if _sec_ch is not None:
            from app.services.compaction import _get_history_mode
            _hist_mode = _get_history_mode(bot, _sec_ch)

            if _hist_mode == "structured" and user_message:
                # Semantic retrieval of relevant conversation sections
                from app.agent.embeddings import embed_text as _sec_embed
                from app.db.models import ConversationSection as _CS
                from sqlalchemy import select as _sec_select
                _query_vec = await _sec_embed(user_message)
                async with _sec_async_session() as _sec_db2:
                    _sec_rows = (await _sec_db2.execute(
                        _sec_select(_CS)
                        .where(_CS.channel_id == channel_id, _CS.embedding.is_not(None))
                        .order_by(_CS.embedding.cosine_distance(_query_vec))
                        .limit(3)
                    )).scalars().all()
                if _sec_rows:
                    _sec_texts = []
                    for _sr in _sec_rows:
                        if _sr.transcript_path:
                            import os as _sec_os
                            from app.services.workspace import workspace_service as _ws_svc
                            try:
                                _ws_root = _ws_svc.get_workspace_root(bot.id, bot)
                                _fpath = _sec_os.path.join(_ws_root, _sr.transcript_path)
                                with open(_fpath) as _f:
                                    _sec_texts.append(_f.read())
                            except Exception:
                                _sec_texts.append(f"## {_sr.title}\n{_sr.summary}")
                        else:
                            _sec_texts.append(f"## {_sr.title}\n{_sr.summary}")
                    _sec_chars = sum(len(t) for t in _sec_texts)
                    _inject_chars["conversation_sections"] = _sec_chars
                    messages.append({
                        "role": "system",
                        "content": "Relevant conversation history sections:\n\n" + "\n\n---\n\n".join(_sec_texts),
                    })
                    yield {"type": "section_context", "count": len(_sec_rows), "chars": _sec_chars}

            elif _hist_mode == "file":
                # Inject read_conversation_history tool into bot's tools
                bot = _dc_replace(
                    bot,
                    local_tools=list(dict.fromkeys((bot.local_tools or []) + ["read_conversation_history"])),
                    pinned_tools=list(dict.fromkeys((bot.pinned_tools or []) + ["read_conversation_history"])),
                )

                # Inject section index so the bot knows what's in the archive
                _si_count = getattr(_sec_ch, "section_index_count", None)
                _si_count = _si_count if _si_count is not None else settings.SECTION_INDEX_COUNT
                if _si_count > 0:
                    _si_verbosity = getattr(_sec_ch, "section_index_verbosity", None) or settings.SECTION_INDEX_VERBOSITY
                    from app.db.models import ConversationSection as _SISection
                    from sqlalchemy import select as _si_select
                    async with _sec_async_session() as _si_db:
                        _si_rows = (await _si_db.execute(
                            _si_select(_SISection)
                            .where(_SISection.channel_id == channel_id)
                            .order_by(_SISection.sequence.desc())
                            .limit(_si_count)
                        )).scalars().all()
                        from sqlalchemy import func as _si_func
                        _si_total = (await _si_db.execute(
                            _si_select(_si_func.count())
                            .select_from(_SISection)
                            .where(_SISection.channel_id == channel_id)
                        )).scalar() or 0
                    if _si_rows:
                        from app.services.compaction import format_section_index
                        _si_text = format_section_index(_si_rows, verbosity=_si_verbosity, total_sections=_si_total)
                        _si_chars = len(_si_text)
                        _inject_chars["section_index"] = _si_chars
                        messages.append({"role": "system", "content": _si_text})
                        yield {"type": "section_index_context", "count": len(_si_rows), "chars": _si_chars}

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
        from app.services.workspace_indexing import resolve_indexing, get_all_roots
        _resolved = resolve_indexing(bot.workspace.indexing, bot._workspace_raw, bot._ws_indexing_config)
        _ws_threshold = _resolved["similarity_threshold"]
        _ws_top_k = _resolved["top_k"]
        _ws_roots = get_all_roots(bot)
        fs_chunks, fs_sim = await retrieve_filesystem_context(
            user_message, bot.id, roots=_ws_roots,
            threshold=_ws_threshold, top_k=_ws_top_k,
            embedding_model=_resolved["embedding_model"],
            segments=_resolved.get("segments"),
            channel_id=str(channel_id) if channel_id else None,
        )
        # Filter out chunks already injected by memory scheme
        if _memory_scheme_injected_paths:
            fs_chunks = [
                c for c in fs_chunks
                if not any(p in c for p in _memory_scheme_injected_paths)
            ]
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
                "content": (
                    "Relevant workspace file excerpts (partial segments — "
                    "use exec_command with `cat <filepath>` to read full file contents):\n\n"
                    + "\n\n---\n\n".join(fs_chunks)
                ),
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
                "content": (
                    "Relevant file excerpts from indexed directories (partial segments — "
                    "use exec_command with `cat <filepath>` to read full file contents):\n\n"
                    + "\n\n---\n\n".join(fs_chunks)
                ),
            })

    # --- tool retrieval (tool RAG) ---
    pre_selected_tools: list[dict[str, Any]] | None = None
    _authorized_names: set[str] | None = None
    if bot.tool_retrieval and (bot.local_tools or bot.mcp_servers or bot.client_tools):
        by_name = await _all_tool_schemas_by_name(bot)
        _authorized_names = set(by_name.keys())
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

            # Inject compact usage index for unretrieved tools
            _retrieved_names = {t["function"]["name"] for t in pre_selected_tools}
            _unretrieved = [
                (n, s["function"])
                for n, s in by_name.items()
                if n not in _retrieved_names and n != "get_tool_info"
            ]
            if _unretrieved:
                _index_lines = "\n".join(
                    f"  • {_compact_tool_usage(n, fn)}" for n, fn in _unretrieved
                )
                messages.append({
                    "role": "system",
                    "content": (
                        "Available tools not yet loaded — call get_tool_info(tool_name=\"<name>\") for full schema:\n"
                        + _index_lines
                    ),
                })
                yield {"type": "tool_index", "unretrieved_count": len(_unretrieved)}
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
    result.pre_selected_tools = pre_selected_tools
    result.authorized_tool_names = _authorized_names

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
    if system_preamble:
        # Heartbeat or other system-initiated task — don't frame as "user message"
        messages.append({
            "role": "system",
            "content": "Everything above is background context. Your TASK PROMPT follows — execute it now.",
        })
    else:
        messages.append({
            "role": "system",
            "content": "Everything above is context and conversation history. The user's CURRENT message follows — respond to it directly.",
        })

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
