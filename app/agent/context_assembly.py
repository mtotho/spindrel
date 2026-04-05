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
    """Clear auto-enrollment caches after file sync."""
    global _core_skill_cache
    _core_skill_cache = None
    _integration_skill_cache.clear()


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
    channel_model_tier_overrides: dict | None = None
    budget_utilization: float | None = None


async def _inject_workspace_skills(
    messages: list[dict],
    workspace_id: str,
    bot_id: str,
    user_message: str,
    inject_chars: dict[str, int],
) -> AsyncGenerator[dict[str, Any], None]:
    """Inject workspace skills (pinned/on-demand) into messages.

    Extracted for testability — called from assemble_context when workspace
    skills are enabled.
    """
    from app.services.workspace_skills import get_workspace_skills_for_bot

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
    budget: "ContextBudget | None" = None,
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
    _surfaced_skill_ids: set[str] = set()

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
            carapaces=_eff.carapaces,
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

    # --- auto-inject carapaces from activated integrations ---
    if _ch_row is not None:
        _ch_carapaces_disabled = set(getattr(_ch_row, "carapaces_disabled", None) or [])
        try:
            from integrations import get_activation_manifests
            _manifests = get_activation_manifests()
            from app.services.integration_settings import is_disabled as _is_intg_disabled
            for _ci in (getattr(_ch_row, "integrations", None) or []):
                if not _ci.activated:
                    continue
                if _is_intg_disabled(_ci.integration_type):
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
        # Merge skills (deduplicate by id)
        _existing_skill_ids = {s.id for s in bot.skills}
        _new_skills = [s for s in _resolved_c.skills if s.id not in _existing_skill_ids]
        # Merge tools (deduplicate)
        _existing_tools = set(bot.local_tools)
        _new_local = [t for t in _resolved_c.local_tools if t not in _existing_tools]
        _existing_mcp = set(bot.mcp_servers)
        _new_mcp = [t for t in _resolved_c.mcp_tools if t not in _existing_mcp]
        _existing_pinned = set(bot.pinned_tools)
        _new_pinned = [t for t in _resolved_c.pinned_tools if t not in _existing_pinned]
        # Re-apply channel disabled lists so carapaces can't bypass channel restrictions
        if _ch_row is not None:
            _ch_tools_disabled = set(getattr(_ch_row, "local_tools_disabled", None) or [])
            _ch_mcp_disabled = set(getattr(_ch_row, "mcp_servers_disabled", None) or [])
            _ch_skills_disabled = set(getattr(_ch_row, "skills_disabled", None) or [])
            if _ch_tools_disabled:
                _new_local = [t for t in _new_local if t not in _ch_tools_disabled]
            if _ch_mcp_disabled:
                _new_mcp = [t for t in _new_mcp if t not in _ch_mcp_disabled]
            if _ch_skills_disabled:
                _new_skills = [s for s in _new_skills if s.id not in _ch_skills_disabled]
        bot = _dc_replace(
            bot,
            skills=list(bot.skills) + _new_skills,
            local_tools=list(bot.local_tools) + _new_local,
            mcp_servers=list(bot.mcp_servers) + _new_mcp,
            pinned_tools=list(bot.pinned_tools) + _new_pinned,
        )
        # Publish resolved skill IDs so get_skill can authorize carapace-injected skills
        from app.agent.context import current_resolved_skill_ids
        current_resolved_skill_ids.set({s.id for s in bot.skills})

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

    # --- capability auto-discovery index ---
    # Build a compact index of available-but-not-active carapaces for the LLM.
    # The LLM can call activate_capability(id) to load one for the session.
    _cap_index_ids: list[str] = []
    try:
        from app.agent.carapaces import list_carapaces as _list_all_carapaces
        _all_caps = _list_all_carapaces()
        _active_cap_ids = set(_carapace_ids) if _carapace_ids else set()
        _globally_disabled_raw = getattr(settings, "CAPABILITIES_DISABLED", "") or ""
        _globally_disabled = {s.strip() for s in _globally_disabled_raw.split(",") if s.strip()}
        _ch_caps_disabled_set = set(getattr(_ch_row, "carapaces_disabled", None) or []) if _ch_row else set()
        _cap_excluded = _active_cap_ids | _globally_disabled | _ch_caps_disabled_set

        _cap_lines: list[str] = []
        for _c in _all_caps:
            _cid = _c["id"]
            if _cid in _cap_excluded:
                continue
            _cname = _c.get("name", _cid)
            _cdesc = _c.get("description") or ""
            _cap_lines.append(f"- {_cid}: {_cname}" + (f" — {_cdesc}" if _cdesc else ""))
            _cap_index_ids.append(_cid)

        if _cap_lines:
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

                # Inject activate_capability tool into bot's available tools
                if "activate_capability" not in (bot.local_tools or []):
                    bot = _dc_replace(
                        bot,
                        local_tools=list(bot.local_tools or []) + ["activate_capability"],
                        pinned_tools=list(dict.fromkeys((bot.pinned_tools or []) + ["activate_capability"])),
                    )
    except Exception:
        logger.warning("Failed to build capability index", exc_info=True)

    # --- auto-discover bot-authored skills (source_type="tool") ---
    if bot.id:
        try:
            from app.agent.bots import SkillConfig
            _bot_skill_ids = await _get_bot_authored_skill_ids(bot.id)
            if _bot_skill_ids:
                _existing_skill_ids = {s.id for s in bot.skills}
                _bot_new_skills = [
                    SkillConfig(id=sid, mode="on_demand")
                    for sid in _bot_skill_ids
                    if sid not in _existing_skill_ids
                ]
                if _bot_new_skills:
                    bot = _dc_replace(bot, skills=list(bot.skills) + _bot_new_skills)
                    from app.agent.context import current_resolved_skill_ids
                    current_resolved_skill_ids.set({s.id for s in bot.skills})
                    yield {"type": "bot_authored_skills", "count": len(_bot_new_skills)}
        except Exception:
            logger.warning("Failed to auto-discover bot-authored skills for %s", bot.id, exc_info=True)

    # --- auto-enroll core skills (on_demand for all bots) ---
    try:
        from app.agent.bots import SkillConfig as _SkillConfig
        _core_ids = await _get_core_skill_ids()
        if _core_ids:
            _existing = {s.id for s in bot.skills}
            # Respect channel skills_disabled
            _disabled = set()
            if _ch_row is not None:
                _disabled = set(getattr(_ch_row, "skills_disabled", None) or [])
            _auto_skills = [
                _SkillConfig(id=sid, mode="on_demand")
                for sid in _core_ids
                if sid not in _existing and sid not in _disabled
            ]
            if _auto_skills:
                bot = _dc_replace(bot, skills=list(bot.skills) + _auto_skills)
                from app.agent.context import current_resolved_skill_ids
                current_resolved_skill_ids.set({s.id for s in bot.skills})
                yield {"type": "core_skills_enrolled", "count": len(_auto_skills)}
    except Exception:
        logger.warning("Failed to auto-enroll core skills", exc_info=True)

    # --- auto-enroll integration skills from activated integrations ---
    if _ch_row is not None:
        try:
            from app.agent.bots import SkillConfig as _ISC
            _activated_types: list[str] = []
            for _ci in (getattr(_ch_row, "integrations", None) or []):
                if getattr(_ci, "activated", False):
                    _activated_types.append(_ci.integration_type)
            if _activated_types:
                _existing = {s.id for s in bot.skills}
                _disabled = set(getattr(_ch_row, "skills_disabled", None) or [])
                _int_auto: list = []
                for _itype in _activated_types:
                    _int_ids = await _get_integration_skill_ids(_itype)
                    for sid in _int_ids:
                        if sid not in _existing and sid not in _disabled:
                            _int_auto.append(_ISC(id=sid, mode="on_demand"))
                            _existing.add(sid)
                if _int_auto:
                    bot = _dc_replace(bot, skills=list(bot.skills) + _int_auto)
                    from app.agent.context import current_resolved_skill_ids
                    current_resolved_skill_ids.set({s.id for s in bot.skills})
                    yield {"type": "integration_skills_enrolled", "count": len(_int_auto)}
        except Exception:
            logger.warning("Failed to auto-enroll integration skills", exc_info=True)

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
        _MEMORY_SCHEME_INJECT_TOOLS = ["search_memory", "get_memory_file", "file", "manage_bot_skill"]
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
        from app.services.memory_scheme import get_memory_root, get_memory_index_prefix, get_memory_rel_path
        try:
            from app.services.workspace import workspace_service as _mem_ws
            _mem_ws_root = _mem_ws.get_workspace_root(bot.id, bot)
            _mem_root = get_memory_root(bot, ws_root=_mem_ws_root)
            _mem_rel = get_memory_index_prefix(bot)  # index-relative prefix for FS_CONTEXT exclusion
            _mem_file_rel = get_memory_rel_path(bot)  # file-tool-relative prefix (e.g. "memory")

            # 1. MEMORY.md — always inject
            _mem_md_path = _mem_os.path.join(_mem_root, "MEMORY.md")
            if _mem_os.path.isfile(_mem_md_path):
                _mem_md_content = Path(_mem_md_path).read_text()
                if _mem_md_content.strip():
                    _inject_chars["memory_bootstrap"] = len(_mem_md_content)
                    _mem_full = f"Your persistent memory ({_mem_file_rel}/MEMORY.md — curated stable facts):\n\n{_mem_md_content}"
                    messages.append({"role": "system", "content": _mem_full})
                    _budget_consume("memory_bootstrap", _mem_full)
                    _memory_scheme_injected_paths.add(f"{_mem_rel}/MEMORY.md")
                    yield {"type": "memory_scheme_bootstrap", "chars": len(_mem_md_content)}

                    # Nudge if MEMORY.md is getting too long
                    _mem_line_count = _mem_md_content.count("\n") + 1
                    if settings.MEMORY_MD_NUDGE_THRESHOLD > 0 and _mem_line_count > settings.MEMORY_MD_NUDGE_THRESHOLD:
                        messages.append({
                            "role": "system",
                            "content": (
                                f"[Memory housekeeping] Your MEMORY.md is {_mem_line_count} lines "
                                f"(threshold: {settings.MEMORY_MD_NUDGE_THRESHOLD}). "
                                "Consider pruning stale entries, merging duplicates, or moving detailed "
                                "notes to reference/ files to keep MEMORY.md concise and fast to scan."
                            ),
                        })

            # 2. Today's daily log
            _today = _mem_date.today().isoformat()
            _today_path = _mem_os.path.join(_mem_root, "logs", f"{_today}.md")
            if _mem_os.path.isfile(_today_path):
                _today_content = Path(_today_path).read_text()
                if _today_content.strip():
                    _inject_chars["memory_today_log"] = len(_today_content)
                    messages.append({
                        "role": "system",
                        "content": f"Today's daily log ({_mem_file_rel}/logs/{_today}.md):\n\n{_today_content}",
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
                        "content": f"Yesterday's daily log ({_mem_file_rel}/logs/{_yesterday}.md):\n\n{_yesterday_content}",
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
                    from datetime import datetime as _ref_dt
                    _ref_entries = []
                    for _rf in _ref_files:
                        try:
                            _rf_mtime = _mem_os.path.getmtime(_mem_os.path.join(_ref_dir, _rf))
                            _rf_date = _ref_dt.fromtimestamp(_rf_mtime).strftime("%Y-%m-%d")
                            _ref_entries.append(f"  - {_rf} (modified {_rf_date})")
                        except Exception:
                            _ref_entries.append(f"  - {_rf}")
                    _ref_list = "\n".join(_ref_entries)
                    messages.append({
                        "role": "system",
                        "content": f"Reference documents in {_mem_file_rel}/reference/ (use get_memory_file to read):\n{_ref_list}",
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

            # Resolve workspace schema: per-channel override takes precedence over template
            _schema_content = ""
            _ch_schema_override = getattr(_ch_row, "workspace_schema_content", None)
            if _ch_schema_override:
                _schema_content = _ch_schema_override
            elif getattr(_ch_row, "workspace_schema_template_id", None):
                try:
                    from app.db.engine import async_session as _schema_session_factory
                    from app.services.prompt_resolution import resolve_prompt_template
                    async with _schema_session_factory() as _schema_db:
                        _schema_content = await resolve_prompt_template(
                            str(_ch_row.workspace_schema_template_id), fallback="", db=_schema_db,
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
            else:
                _cw_helper = (
                    "Organize workspace files by purpose: use descriptive .md filenames, "
                    "keep active documents at the root, and archive completed work to archive/.\n\n"
                ) + _cw_helper

            _cw_body = ""
            if _cw_files:
                _cw_sections = []
                for _fname, _fcontent in _cw_files:
                    _cw_sections.append(f"## {_fname}\n\n{_fcontent}")
                _cw_body = "\n\n---\n\n".join(_cw_sections)

            _inject_chars["channel_workspace"] = _cw_total_chars
            _cw_full = _cw_helper + _cw_body
            messages.append({"role": "system", "content": _cw_full})
            _budget_consume("channel_workspace", _cw_full)
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

        # --- plan stall detection: annotate if plans.md has an executing plan with stale mtime ---
        try:
            import time as _time_mod
            _plans_path = _cw_os.path.join(_cw_root, "plans.md")
            if _cw_os.path.isfile(_plans_path):
                _plans_mtime = _cw_os.path.getmtime(_plans_path)
                _plans_age = _time_mod.time() - _plans_mtime
                if _plans_age > 600:  # 10 minutes
                    _plans_content = Path(_plans_path).read_text()
                    if "[executing]" in _plans_content:
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

    # --- skills ---
    if bot.skills:
        _pinned_skills = [s for s in bot.skills if s.mode == "pinned"]
        _on_demand_skills = [s for s in bot.skills if s.mode != "pinned"]

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
                _surfaced_skill_ids.update(s.id for s in _pinned_skills)

        # On-demand skills: inject index, agent uses get_skill()
        if _on_demand_skills:
            from sqlalchemy import select as _sa_select
            from app.db.engine import async_session as _async_session
            from app.db.models import Skill as _SkillRow
            _od_ids = [s.id for s in _on_demand_skills]
            async with _async_session() as _db:
                _rows = (await _db.execute(
                    _sa_select(_SkillRow.id, _SkillRow.name, _SkillRow.description, _SkillRow.triggers)
                    .where(_SkillRow.id.in_(_od_ids))
                )).all()
            if _rows:
                def _fmt_od(r) -> str:
                    parts = [f"- {r.id}: {r.name}"]
                    if r.description:
                        parts.append(f" — {r.description}")
                    if r.triggers:
                        parts.append(f" [{', '.join(r.triggers)}]")
                    return "".join(parts)
                _index_lines = "\n".join(_fmt_od(r) for r in _rows)
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
                _surfaced_skill_ids.update(r.id for r in _rows)

    # --- workspace skills ---
    if channel_id is not None:
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
                _participant_lines.append(f"  - {_bid} ({_role_label}): {_mb.name}{_cfg_suffix}{_you_marker}")
            except Exception:
                _participant_lines.append(f"  - {_bid} ({_role_label}){_you_marker}")

        _awareness_msg = (
            f"You are {bot.name} (bot_id: {bot.id}).\n\n"
            "This channel has multiple bot participants:\n"
            + "\n".join(_participant_lines)
            + "\nYou can @-mention other bots in your response to bring them into the conversation. They will see the full channel context and reply automatically."
            + "\nDo not @-mention yourself."
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
        messages.append({
            "role": "system",
            "content": (
                "Available sub-agents (delegate via delegate_to_agent):\n"
                + "\n".join(_delegate_lines)
            ),
        })
        yield {"type": "delegate_index", "count": len(_delegate_lines)}

    # --- DB memory injection REMOVED (deprecated — use memory_scheme='workspace-files') ---

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

    # --- DB RAG knowledge injection REMOVED (deprecated — use skills/carapaces instead) ---

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
                from app.agent.vector_ops import halfvec_cosine_distance as _hv_dist
                from app.db.models import ConversationSection as _CS
                from sqlalchemy import select as _sec_select
                _query_vec = await _sec_embed(user_message)
                async with _sec_async_session() as _sec_db2:
                    _sec_rows = (await _sec_db2.execute(
                        _sec_select(_CS)
                        .where(_CS.channel_id == channel_id, _CS.embedding.is_not(None))
                        .order_by(_hv_dist(_CS.embedding, _query_vec))
                        .limit(3)
                    )).scalars().all()
                if _sec_rows:
                    _sec_texts = []
                    for _sr in _sec_rows:
                        if _sr.transcript:
                            _sec_texts.append(_sr.transcript)
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
                    from sqlalchemy.orm import defer as _si_defer
                    async with _sec_async_session() as _si_db:
                        _si_rows = (await _si_db.execute(
                            _si_select(_SISection)
                            .where(_SISection.channel_id == channel_id)
                            .order_by(_SISection.sequence.desc())
                            .limit(_si_count)
                            .options(_si_defer(_SISection.transcript), _si_defer(_SISection.embedding))
                        )).scalars().all()
                        from sqlalchemy import func as _si_func
                        _si_total = (await _si_db.execute(
                            _si_select(_si_func.count())
                            .select_from(_SISection)
                            .where(_SISection.channel_id == channel_id)
                        )).scalar() or 0
                        # Query all section tags in the same session when needed
                        _si_all_tags: list[str] | None = None
                        if _si_rows and _si_total > len(_si_rows):
                            _si_tag_rows = (await _si_db.execute(
                                _si_select(_SISection.tags)
                                .where(_SISection.channel_id == channel_id)
                            )).scalars().all()
                            _si_all_tags = [
                                tag for tags in _si_tag_rows if tags for tag in tags
                            ]
                    if _si_rows:
                        from app.services.compaction import format_section_index
                        _si_text = format_section_index(
                            _si_rows, verbosity=_si_verbosity,
                            total_sections=_si_total, all_tags=_si_all_tags,
                        )
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
            _fs_body = (
                "Relevant workspace file excerpts (partial segments — "
                "use exec_command with `cat <filepath>` to read full file contents):\n\n"
                + "\n\n---\n\n".join(fs_chunks)
            )
            # P3: skip if budget is too tight
            if _budget_can_afford(_fs_body):
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
                messages.append({"role": "system", "content": _fs_body})
                _budget_consume("fs_context", _fs_body)
            else:
                logger.info("Budget: skipping workspace fs RAG (%d chunks, budget remaining: %d)",
                           len(fs_chunks), budget.remaining if budget else 0)
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
    if bot.tool_retrieval:
        by_name = await _all_tool_schemas_by_name(bot) if (bot.local_tools or bot.mcp_servers or bot.client_tools) else {}
        # Always include get_tool_info when tool retrieval is on (allows LLM to inspect discovered tools)
        if "get_tool_info" not in by_name:
            for _gti in get_local_tool_schemas(["get_tool_info"]):
                by_name[_gti["function"]["name"]] = _gti
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
                data={"best_similarity": tool_sim, "threshold": th,
                      "selected": [t["function"]["name"] for t in retrieved],
                      "top_candidates": tool_candidates},
            ))
        if by_name:
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

            # Inject compact usage index for unretrieved tools from bot's declared set
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
                _tool_idx_content = (
                    "Available tools not yet loaded — call get_tool_info(tool_name=\"<name>\") for full schema:\n"
                    + _index_lines
                )
                # P4: expendable — skip if budget is tight
                if _budget_can_afford(_tool_idx_content):
                    messages.append({"role": "system", "content": _tool_idx_content})
                    _budget_consume("tool_index", _tool_idx_content)
                    yield {"type": "tool_index", "unretrieved_count": len(_unretrieved)}
                else:
                    logger.info("Budget: skipping tool index hints (%d tools)", len(_unretrieved))
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

    # --- store budget utilization for downstream (compaction trigger) ---
    if budget is not None:
        result.budget_utilization = budget.utilization

    # --- skill surfacing tracking ---
    if _surfaced_skill_ids:
        asyncio.create_task(_update_skill_surfacing(_surfaced_skill_ids))

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



async def _update_skill_surfacing(skill_ids: set[str]) -> None:
    """Bulk-update last_surfaced_at and surface_count for surfaced skills (fire-and-forget)."""
    try:
        from sqlalchemy import update
        from app.db.engine import async_session
        from app.db.models import Skill as SkillRow

        now = datetime.now(timezone.utc)
        async with async_session() as db:
            await db.execute(
                update(SkillRow)
                .where(SkillRow.id.in_(list(skill_ids)))
                .values(
                    last_surfaced_at=now,
                    surface_count=SkillRow.surface_count + 1,
                )
            )
            await db.commit()
    except Exception:
        logger.debug("Failed to update skill surfacing stats", exc_info=True)
