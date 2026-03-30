"""Auto-export config state to JSON after admin mutations, auto-restore on first boot."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from datetime import time as dt_time
from pathlib import Path

from app.config import settings

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dirty-flag state (module-level)
# ---------------------------------------------------------------------------

_dirty = False
_dirty_since: float = 0.0  # monotonic timestamp of first dirty mark
_DEBOUNCE_SECONDS = 5.0
_POLL_SECONDS = 2.0


def mark_config_dirty() -> None:
    """Signal that a config mutation occurred. Debounced export follows."""
    global _dirty, _dirty_since
    if not settings.CONFIG_STATE_FILE:
        return
    now = time.monotonic()
    if not _dirty:
        _dirty_since = now
    _dirty = True


# ---------------------------------------------------------------------------
# Helpers (shared with config_state.py GET endpoint)
# ---------------------------------------------------------------------------

def _str(v):
    """Stringify UUIDs / None-safe."""
    return str(v) if v is not None else None


def _time_str(v: dt_time | None) -> str | None:
    return v.isoformat() if v is not None else None


# ---------------------------------------------------------------------------
# Assemble full config state dict
# ---------------------------------------------------------------------------

async def assemble_config_state(db) -> dict:
    """Build the full config-state dict from DB. Shared by GET endpoint and file export."""
    from sqlalchemy import func, select
    from sqlalchemy.orm import selectinload

    from app.db.models import (
        Bot,
        BotPersona,
        Channel,
        ChannelHeartbeat,
        ChannelIntegration,
        Document,
        PromptTemplate,
        ProviderConfig,
        ProviderModel,
        SandboxBotAccess,
        SandboxProfile,
        ServerConfig,
        ServerSetting,
        SharedWorkspace,
        SharedWorkspaceBot,
        Skill,
        Task,
        ToolPolicyRule,
        User,
    )
    from app.services.server_config import get_global_fallback_models
    from app.services.server_settings import get_all_settings

    # --- System ---
    system = {
        "paused": getattr(settings, "SYSTEM_PAUSED", False),
        "pause_behavior": getattr(settings, "SYSTEM_PAUSE_BEHAVIOR", "queue"),
    }

    # --- Global fallback models ---
    global_fallback_models = get_global_fallback_models()

    # --- Settings (grouped) ---
    settings_groups = await get_all_settings()
    settings_flat: dict[str, dict] = {}
    for group in settings_groups:
        settings_flat[group["group"]] = {
            s["key"]: s["value"] for s in group["settings"]
        }

    # --- Server settings raw ---
    ss_rows = (await db.execute(select(ServerSetting))).scalars().all()
    server_settings = [{"key": s.key, "value": s.value} for s in ss_rows]

    # --- Server config ---
    sc_rows = (await db.execute(select(ServerConfig))).scalars().all()
    server_config = [
        {"id": s.id, "global_fallback_models": s.global_fallback_models}
        for s in sc_rows
    ]

    # --- Providers with full model data ---
    provider_rows = (
        await db.execute(
            select(ProviderConfig).options(selectinload(ProviderConfig.models))
        )
    ).scalars().all()
    providers = [
        {
            "id": p.id,
            "display_name": p.display_name,
            "provider_type": p.provider_type,
            "is_enabled": p.is_enabled,
            "base_url": p.base_url,
            "api_key": p.api_key,
            "tpm_limit": p.tpm_limit,
            "rpm_limit": p.rpm_limit,
            "config": p.config,
            "models": [
                {
                    "id": m.id,
                    "provider_id": m.provider_id,
                    "model_id": m.model_id,
                    "display_name": m.display_name,
                    "max_tokens": m.max_tokens,
                    "input_cost_per_1m": m.input_cost_per_1m,
                    "output_cost_per_1m": m.output_cost_per_1m,
                    "no_system_messages": m.no_system_messages,
                }
                for m in p.models
            ],
        }
        for p in provider_rows
    ]

    # --- Bots ---
    bot_rows = (await db.execute(select(Bot))).scalars().all()
    bots = [
        {
            "id": b.id,
            "name": b.name,
            "model": b.model,
            "model_provider_id": b.model_provider_id,
            "system_prompt": b.system_prompt,
            "local_tools": b.local_tools,
            "mcp_servers": b.mcp_servers,
            "client_tools": b.client_tools,
            "pinned_tools": b.pinned_tools,
            "skills": b.skills,
            "docker_sandbox_profiles": b.docker_sandbox_profiles,
            "tool_retrieval": b.tool_retrieval,
            "tool_similarity_threshold": b.tool_similarity_threshold,
            "persona": b.persona,
            "base_prompt": b.base_prompt,
            "context_compaction": b.context_compaction,
            "compaction_interval": b.compaction_interval,
            "compaction_keep_turns": b.compaction_keep_turns,
            "compaction_model": b.compaction_model,
            "memory_knowledge_compaction_prompt": b.memory_knowledge_compaction_prompt,
            "compaction_prompt_template_id": _str(b.compaction_prompt_template_id),
            "audio_input": b.audio_input,
            "memory_config": b.memory_config,
            "knowledge_config": b.knowledge_config,
            "filesystem_indexes": b.filesystem_indexes,
            "host_exec_config": b.host_exec_config,
            "filesystem_access": b.filesystem_access,
            "display_name": b.display_name,
            "avatar_url": b.avatar_url,
            "integration_config": b.integration_config,
            "tool_result_config": b.tool_result_config,
            "knowledge_max_inject_chars": b.knowledge_max_inject_chars,
            "memory_max_inject_chars": b.memory_max_inject_chars,
            "delegation_config": b.delegation_config,
            "model_params": b.model_params,
            "bot_sandbox": b.bot_sandbox,
            "workspace": b.workspace,
            "elevation_enabled": b.elevation_enabled,
            "elevation_threshold": b.elevation_threshold,
            "elevated_model": b.elevated_model,
            "attachment_summarization_enabled": b.attachment_summarization_enabled,
            "attachment_summary_model": b.attachment_summary_model,
            "attachment_text_max_chars": b.attachment_text_max_chars,
            "attachment_vision_concurrency": b.attachment_vision_concurrency,
            "fallback_models": b.fallback_models,
            "user_id": _str(b.user_id),
            "api_key_id": _str(b.api_key_id),
            "api_docs_mode": b.api_docs_mode,
            "memory_scheme": b.memory_scheme,
            "history_mode": b.history_mode,
            "context_pruning": b.context_pruning,
            "context_pruning_keep_turns": b.context_pruning_keep_turns,
        }
        for b in bot_rows
    ]

    # --- Channels ---
    channel_rows = (await db.execute(select(Channel))).scalars().all()
    channels = [
        {
            "id": str(ch.id),
            "name": ch.name,
            "bot_id": ch.bot_id,
            "client_id": ch.client_id,
            "integration": ch.integration,
            "dispatch_config": ch.dispatch_config,
            "require_mention": ch.require_mention,
            "passive_memory": ch.passive_memory,
            "context_compaction": ch.context_compaction,
            "compaction_interval": ch.compaction_interval,
            "compaction_keep_turns": ch.compaction_keep_turns,
            "compaction_model": ch.compaction_model,
            "memory_knowledge_compaction_prompt": ch.memory_knowledge_compaction_prompt,
            "compaction_prompt_template_id": _str(ch.compaction_prompt_template_id),
            "compaction_workspace_file_path": ch.compaction_workspace_file_path,
            "compaction_workspace_id": _str(ch.compaction_workspace_id),
            "elevation_enabled": ch.elevation_enabled,
            "elevation_threshold": ch.elevation_threshold,
            "elevated_model": ch.elevated_model,
            "model_override": ch.model_override,
            "model_provider_id_override": ch.model_provider_id_override,
            "fallback_models": ch.fallback_models,
            "allow_bot_messages": ch.allow_bot_messages,
            "workspace_rag": ch.workspace_rag,
            "max_iterations": ch.max_iterations,
            "task_max_run_seconds": ch.task_max_run_seconds,
            "attachment_retention_days": ch.attachment_retention_days,
            "attachment_max_size_bytes": ch.attachment_max_size_bytes,
            "attachment_types_allowed": ch.attachment_types_allowed,
            "private": ch.private,
            "user_id": _str(ch.user_id),
            "local_tools_override": ch.local_tools_override,
            "local_tools_disabled": ch.local_tools_disabled,
            "mcp_servers_override": ch.mcp_servers_override,
            "mcp_servers_disabled": ch.mcp_servers_disabled,
            "client_tools_override": ch.client_tools_override,
            "client_tools_disabled": ch.client_tools_disabled,
            "pinned_tools_override": ch.pinned_tools_override,
            "skills_override": ch.skills_override,
            "skills_disabled": ch.skills_disabled,
            "skills_extra": ch.skills_extra,
            "workspace_skills_enabled": ch.workspace_skills_enabled,
            "workspace_base_prompt_enabled": ch.workspace_base_prompt_enabled,
            "history_mode": ch.history_mode,
            "trigger_heartbeat_before_compaction": ch.trigger_heartbeat_before_compaction,
            "memory_flush_enabled": ch.memory_flush_enabled,
            "memory_flush_model": ch.memory_flush_model,
            "memory_flush_model_provider_id": ch.memory_flush_model_provider_id,
            "memory_flush_prompt": ch.memory_flush_prompt,
            "memory_flush_prompt_template_id": _str(ch.memory_flush_prompt_template_id),
            "memory_flush_workspace_file_path": ch.memory_flush_workspace_file_path,
            "memory_flush_workspace_id": _str(ch.memory_flush_workspace_id),
            "channel_prompt": ch.channel_prompt,
            "section_index_count": ch.section_index_count,
            "section_index_verbosity": ch.section_index_verbosity,
            "context_pruning": ch.context_pruning,
            "context_pruning_keep_turns": ch.context_pruning_keep_turns,
            "channel_workspace_enabled": ch.channel_workspace_enabled,
        }
        for ch in channel_rows
    ]

    # --- Workspaces ---
    ws_rows = (
        await db.execute(
            select(SharedWorkspace).options(selectinload(SharedWorkspace.bots))
        )
    ).scalars().all()
    workspaces = [
        {
            "id": str(ws.id),
            "name": ws.name,
            "description": ws.description,
            "image": ws.image,
            "network": ws.network,
            "env": ws.env,
            "ports": ws.ports,
            "mounts": ws.mounts,
            "cpus": ws.cpus,
            "memory_limit": ws.memory_limit,
            "docker_user": ws.docker_user,
            "read_only_root": ws.read_only_root,
            "status": ws.status,
            "startup_script": ws.startup_script,
            "workspace_skills_enabled": ws.workspace_skills_enabled,
            "workspace_base_prompt_enabled": ws.workspace_base_prompt_enabled,
            "indexing_config": ws.indexing_config,
            "bots": [
                {"bot_id": wb.bot_id, "role": wb.role, "cwd_override": wb.cwd_override}
                for wb in ws.bots
            ],
        }
        for ws in ws_rows
    ]

    # --- Skills ---
    skill_rows = (await db.execute(select(Skill))).scalars().all()
    chunk_counts_q = (
        await db.execute(
            select(Document.source, func.count()).group_by(Document.source)
        )
    )
    chunk_map = {row[0]: row[1] for row in chunk_counts_q.all()}
    skills = [
        {
            "id": s.id,
            "name": s.name,
            "content": s.content,
            "content_hash": s.content_hash,
            "source_path": s.source_path,
            "source_type": s.source_type,
            "chunk_count": chunk_map.get(s.id, 0),
        }
        for s in skill_rows
    ]

    # --- Tasks (recurring only) ---
    task_rows = (
        await db.execute(
            select(Task).where(Task.recurrence.isnot(None))
        )
    ).scalars().all()
    tasks = [
        {
            "id": str(t.id),
            "bot_id": t.bot_id,
            "client_id": t.client_id,
            "channel_id": _str(t.channel_id),
            "status": t.status,
            "task_type": t.task_type,
            "recurrence": t.recurrence,
            "title": t.title,
            "prompt": t.prompt,
            "dispatch_type": t.dispatch_type,
            "dispatch_config": t.dispatch_config,
            "callback_config": t.callback_config,
            "execution_config": t.execution_config,
            "prompt_template_id": _str(t.prompt_template_id),
            "workspace_file_path": t.workspace_file_path,
            "workspace_id": _str(t.workspace_id),
            "max_run_seconds": t.max_run_seconds,
        }
        for t in task_rows
    ]

    # --- Users (skip password_hash) ---
    user_rows = (await db.execute(select(User))).scalars().all()
    users = [
        {
            "id": str(u.id),
            "email": u.email,
            "display_name": u.display_name,
            "avatar_url": u.avatar_url,
            "auth_method": u.auth_method,
            "is_admin": u.is_admin,
            "is_active": u.is_active,
        }
        for u in user_rows
    ]

    # --- Sandbox profiles ---
    sp_rows = (await db.execute(select(SandboxProfile))).scalars().all()
    sandbox_profiles = [
        {
            "id": str(sp.id),
            "name": sp.name,
            "description": sp.description,
            "image": sp.image,
            "scope_mode": sp.scope_mode,
            "network_mode": sp.network_mode,
            "read_only_root": sp.read_only_root,
            "create_options": sp.create_options,
            "mount_specs": sp.mount_specs,
            "env": sp.env,
            "labels": sp.labels,
            "port_mappings": sp.port_mappings,
            "idle_ttl_seconds": sp.idle_ttl_seconds,
            "enabled": sp.enabled,
        }
        for sp in sp_rows
    ]

    # --- Sandbox bot access ---
    sba_rows = (await db.execute(select(SandboxBotAccess))).scalars().all()
    sandbox_bot_access = [
        {"bot_id": sba.bot_id, "profile_id": str(sba.profile_id)}
        for sba in sba_rows
    ]

    # --- Tool policy rules ---
    tpr_rows = (await db.execute(select(ToolPolicyRule))).scalars().all()
    tool_policy_rules = [
        {
            "id": str(r.id),
            "bot_id": r.bot_id,
            "tool_name": r.tool_name,
            "action": r.action,
            "conditions": r.conditions,
            "priority": r.priority,
            "approval_timeout": r.approval_timeout,
            "reason": r.reason,
            "enabled": r.enabled,
        }
        for r in tpr_rows
    ]

    # --- Prompt templates ---
    pt_rows = (await db.execute(select(PromptTemplate))).scalars().all()
    prompt_templates = [
        {
            "id": str(pt.id),
            "name": pt.name,
            "description": pt.description,
            "content": pt.content,
            "category": pt.category,
            "tags": pt.tags,
            "workspace_id": _str(pt.workspace_id),
            "source_type": pt.source_type,
            "source_path": pt.source_path,
            "content_hash": pt.content_hash,
        }
        for pt in pt_rows
    ]

    # --- Bot personas ---
    bp_rows = (await db.execute(select(BotPersona))).scalars().all()
    bot_personas = [
        {"bot_id": bp.bot_id, "persona_layer": bp.persona_layer}
        for bp in bp_rows
    ]

    # --- Channel integrations ---
    ci_rows = (await db.execute(select(ChannelIntegration))).scalars().all()
    channel_integrations = [
        {
            "id": str(ci.id),
            "channel_id": str(ci.channel_id),
            "integration_type": ci.integration_type,
            "client_id": ci.client_id,
            "dispatch_config": ci.dispatch_config,
            "display_name": ci.display_name,
            "metadata": ci.metadata_,
        }
        for ci in ci_rows
    ]

    # --- Channel heartbeats (skip runtime fields) ---
    ch_rows = (await db.execute(select(ChannelHeartbeat))).scalars().all()
    channel_heartbeats = [
        {
            "id": str(h.id),
            "channel_id": str(h.channel_id),
            "enabled": h.enabled,
            "interval_minutes": h.interval_minutes,
            "model": h.model,
            "model_provider_id": h.model_provider_id,
            "fallback_models": h.fallback_models,
            "prompt": h.prompt,
            "dispatch_results": h.dispatch_results,
            "trigger_response": h.trigger_response,
            "quiet_start": _time_str(h.quiet_start),
            "quiet_end": _time_str(h.quiet_end),
            "timezone": h.timezone,
            "prompt_template_id": _str(h.prompt_template_id),
            "workspace_file_path": h.workspace_file_path,
            "workspace_id": _str(h.workspace_id),
            "max_run_seconds": h.max_run_seconds,
        }
        for h in ch_rows
    ]

    # --- Backup config (backup.* keys from server_settings) ---
    backup_config = {}
    for ss in ss_rows:
        if ss.key.startswith("backup."):
            short = ss.key[len("backup."):]
            backup_config[short] = ss.value

    return {
        "system": system,
        "global_fallback_models": global_fallback_models,
        "settings": settings_flat,
        "server_settings": server_settings,
        "server_config": server_config,
        "providers": providers,
        "bots": bots,
        "channels": channels,
        "workspaces": workspaces,
        "skills": skills,
        "tasks": tasks,
        "users": users,
        "sandbox_profiles": sandbox_profiles,
        "sandbox_bot_access": sandbox_bot_access,
        "tool_policy_rules": tool_policy_rules,
        "prompt_templates": prompt_templates,
        "bot_personas": bot_personas,
        "channel_integrations": channel_integrations,
        "channel_heartbeats": channel_heartbeats,
        "backup_config": backup_config,
    }


# ---------------------------------------------------------------------------
# File I/O (atomic write)
# ---------------------------------------------------------------------------

async def write_config_file() -> None:
    """Assemble config state and write it atomically to CONFIG_STATE_FILE."""
    path = settings.CONFIG_STATE_FILE
    if not path:
        return

    from app.db.engine import async_session

    async with async_session() as db:
        state = await assemble_config_state(db)

    # Atomic write: tempfile in same directory, then os.replace
    dest = Path(path)
    fd, tmp_path = tempfile.mkstemp(dir=str(dest.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2, default=str)
            f.write("\n")
        os.replace(tmp_path, str(dest))
        log.info("Config state exported to %s", path)
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Background export worker (debounced)
# ---------------------------------------------------------------------------

async def config_export_worker() -> None:
    """Poll for dirty flag; export after debounce period elapses."""
    global _dirty, _dirty_since
    log.info("Config export worker started (file=%s)", settings.CONFIG_STATE_FILE)
    while True:
        await asyncio.sleep(_POLL_SECONDS)
        if not _dirty:
            continue
        if not settings.CONFIG_STATE_FILE:
            _dirty = False
            continue
        elapsed = time.monotonic() - _dirty_since
        if elapsed < _DEBOUNCE_SECONDS:
            continue
        # Debounce period passed — export
        _dirty = False
        try:
            await write_config_file()
        except Exception:
            # Re-mark dirty so the next poll cycle retries
            _dirty = True
            log.exception("Failed to export config state")


# ---------------------------------------------------------------------------
# Restore from file (startup)
# ---------------------------------------------------------------------------

async def restore_from_file() -> None:
    """Restore config state from JSON file. Called on first boot (empty DB)."""
    path = settings.CONFIG_STATE_FILE
    if not path:
        return

    file_path = Path(path)
    if not file_path.exists():
        log.info("No config state file at %s — skipping restore", path)
        return

    log.info("Restoring config state from %s ...", path)
    try:
        payload = json.loads(file_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        log.error("Failed to read config state file: %s", e)
        return

    from app.db.engine import async_session

    async with async_session() as db:
        # Import restore logic from config_state router
        from app.routers.api_v1_admin.config_state import do_restore
        summary = await do_restore(payload, db)
        await db.commit()

    log.info("Config state restored: %s", summary)


# ---------------------------------------------------------------------------
# Middleware helper: should this request trigger a config export?
# ---------------------------------------------------------------------------

# Paths that are operational, not config mutations
_EXCLUDED_SUFFIXES = (
    "/fire", "/infer", "/reindex", "/test", "/diagnostics",
    "/server-logs", "/config-state", "/download", "/file-sync", "/log-level",
    "/operations/backup", "/operations/pull", "/operations/restart",
)


def is_config_mutation(method: str, path: str) -> bool:
    """Return True if this request looks like an admin config mutation."""
    if method not in ("POST", "PUT", "PATCH", "DELETE"):
        return False
    if not (path.startswith("/api/v1/admin/") or path.startswith("/api/v1/channels/")):
        return False
    for suffix in _EXCLUDED_SUFFIXES:
        if path.endswith(suffix):
            return False
    return True
