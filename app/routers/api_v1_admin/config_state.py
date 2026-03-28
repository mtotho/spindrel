"""Config state: GET /config-state (full backup), POST /config-state/restore (upsert)."""
from __future__ import annotations

import logging
from datetime import time as dt_time

from fastapi import APIRouter, Depends
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings as app_settings
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
from app.dependencies import get_db, verify_auth_or_user

log = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _str(v):
    """Stringify UUIDs / None-safe."""
    return str(v) if v is not None else None


def _time_str(v: dt_time | None) -> str | None:
    return v.isoformat() if v is not None else None


# ---------------------------------------------------------------------------
# GET  /config-state  —  full config backup
# ---------------------------------------------------------------------------

@router.get("/config-state")
async def get_config_state(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    from app.services.server_config import get_global_fallback_models
    from app.services.server_settings import get_all_settings

    # --- System ---
    system = {
        "paused": getattr(app_settings, "SYSTEM_PAUSED", False),
        "pause_behavior": getattr(app_settings, "SYSTEM_PAUSE_BEHAVIOR", "queue"),
    }

    # --- Global fallback models (from server_config table) ---
    global_fallback_models = get_global_fallback_models()

    # --- Settings (grouped) ---
    settings_groups = await get_all_settings()
    settings_flat: dict[str, dict] = {}
    for group in settings_groups:
        settings_flat[group["group"]] = {
            s["key"]: s["value"] for s in group["settings"]
        }

    # --- Server settings raw (for restore) ---
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

    # --- Bots (from DB directly, not in-memory registry) ---
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

    # --- Channels (full fields) ---
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
        }
        for ch in channel_rows
    ]

    # --- Workspaces (full fields + bot roles) ---
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

    # --- Skills (full fields) ---
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

    # --- Tasks (recurring only — full fields) ---
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

    # --- Channel heartbeats (skip runtime: last_result, last_error, run_count) ---
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
    }


# ---------------------------------------------------------------------------
# POST /config-state/restore  —  upsert from backup JSON
# ---------------------------------------------------------------------------

@router.post("/config-state/restore")
async def restore_config_state(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """Restore config from a backup JSON snapshot.

    Upserts all records in FK-dependency order inside a single transaction.
    Returns a summary of created/updated counts per section.
    """
    summary: dict[str, dict[str, int]] = {}

    def _track(section: str, created: int, updated: int):
        summary[section] = {"created": created, "updated": updated}

    # 1. Users (skip password_hash — existing users keep passwords)
    if users := payload.get("users"):
        c, u = 0, 0
        for row in users:
            uid = row["id"]
            vals = {
                "email": row["email"],
                "display_name": row["display_name"],
                "avatar_url": row.get("avatar_url"),
                "auth_method": row.get("auth_method", "local"),
                "is_admin": row.get("is_admin", False),
                "is_active": row.get("is_active", True),
            }
            stmt = pg_insert(User).values(id=uid, **vals)
            stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=vals)
            r = await db.execute(stmt)
            if r.rowcount:
                # Can't distinguish create vs update with on_conflict, count all as upserted
                u += 1
        _track("users", c, u)

    # 2. Server config
    if sc_list := payload.get("server_config"):
        c, u = 0, 0
        for row in sc_list:
            vals = {"global_fallback_models": row["global_fallback_models"]}
            stmt = pg_insert(ServerConfig).values(id=row.get("id", "default"), **vals)
            stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=vals)
            await db.execute(stmt)
            u += 1
        _track("server_config", c, u)

    # 3. Server settings
    if ss_list := payload.get("server_settings"):
        c, u = 0, 0
        for row in ss_list:
            vals = {"value": row["value"]}
            stmt = pg_insert(ServerSetting).values(key=row["key"], **vals)
            stmt = stmt.on_conflict_do_update(index_elements=["key"], set_=vals)
            await db.execute(stmt)
            u += 1
        _track("server_settings", c, u)

    # 4. Providers + models
    if providers := payload.get("providers"):
        c, u = 0, 0
        for row in providers:
            vals = {
                "display_name": row["display_name"],
                "provider_type": row["provider_type"],
                "is_enabled": row.get("is_enabled", True),
                "base_url": row.get("base_url"),
                "api_key": row.get("api_key"),
                "tpm_limit": row.get("tpm_limit"),
                "rpm_limit": row.get("rpm_limit"),
                "config": row.get("config", {}),
            }
            stmt = pg_insert(ProviderConfig).values(id=row["id"], **vals)
            stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=vals)
            await db.execute(stmt)
            u += 1

            # Models: delete existing for this provider, then insert fresh
            await db.execute(
                delete(ProviderModel).where(ProviderModel.provider_id == row["id"])
            )
            for m in row.get("models", []):
                m_vals = {
                    "provider_id": row["id"],
                    "model_id": m["model_id"],
                    "display_name": m.get("display_name"),
                    "max_tokens": m.get("max_tokens"),
                    "input_cost_per_1m": m.get("input_cost_per_1m"),
                    "output_cost_per_1m": m.get("output_cost_per_1m"),
                    "no_system_messages": m.get("no_system_messages", False),
                }
                await db.execute(pg_insert(ProviderModel).values(**m_vals))
        _track("providers", c, u)

    # 5. Prompt templates
    if templates := payload.get("prompt_templates"):
        c, u = 0, 0
        for row in templates:
            vals = {
                "name": row["name"],
                "description": row.get("description"),
                "content": row["content"],
                "category": row.get("category"),
                "tags": row.get("tags", []),
                "workspace_id": row.get("workspace_id"),
                "source_type": row.get("source_type", "manual"),
                "source_path": row.get("source_path"),
                "content_hash": row.get("content_hash"),
            }
            stmt = pg_insert(PromptTemplate).values(id=row["id"], **vals)
            stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=vals)
            await db.execute(stmt)
            u += 1
        _track("prompt_templates", c, u)

    # 6. Skills
    if skills := payload.get("skills"):
        c, u = 0, 0
        for row in skills:
            vals = {
                "name": row["name"],
                "content": row.get("content", ""),
                "content_hash": row.get("content_hash", ""),
                "source_path": row.get("source_path"),
                "source_type": row.get("source_type", "manual"),
            }
            stmt = pg_insert(Skill).values(id=row["id"], **vals)
            stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=vals)
            await db.execute(stmt)
            u += 1
        _track("skills", c, u)

    # 7. Sandbox profiles
    if profiles := payload.get("sandbox_profiles"):
        c, u = 0, 0
        for row in profiles:
            vals = {
                "name": row["name"],
                "description": row.get("description"),
                "image": row["image"],
                "scope_mode": row.get("scope_mode", "session"),
                "network_mode": row.get("network_mode", "none"),
                "read_only_root": row.get("read_only_root", False),
                "create_options": row.get("create_options", {}),
                "mount_specs": row.get("mount_specs", []),
                "env": row.get("env", {}),
                "labels": row.get("labels", {}),
                "port_mappings": row.get("port_mappings", []),
                "idle_ttl_seconds": row.get("idle_ttl_seconds"),
                "enabled": row.get("enabled", True),
            }
            stmt = pg_insert(SandboxProfile).values(id=row["id"], **vals)
            stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=vals)
            await db.execute(stmt)
            u += 1
        _track("sandbox_profiles", c, u)

    # 8. Bots + personas
    if bots := payload.get("bots"):
        c, u = 0, 0
        for row in bots:
            vals = {
                "name": row["name"],
                "model": row["model"],
                "model_provider_id": row.get("model_provider_id"),
                "system_prompt": row.get("system_prompt", ""),
                "local_tools": row.get("local_tools", []),
                "mcp_servers": row.get("mcp_servers", []),
                "client_tools": row.get("client_tools", []),
                "pinned_tools": row.get("pinned_tools", []),
                "skills": row.get("skills", []),
                "docker_sandbox_profiles": row.get("docker_sandbox_profiles", []),
                "tool_retrieval": row.get("tool_retrieval", True),
                "tool_similarity_threshold": row.get("tool_similarity_threshold"),
                "persona": row.get("persona", False),
                "base_prompt": row.get("base_prompt", True),
                "context_compaction": row.get("context_compaction", True),
                "compaction_interval": row.get("compaction_interval"),
                "compaction_keep_turns": row.get("compaction_keep_turns"),
                "compaction_model": row.get("compaction_model"),
                "memory_knowledge_compaction_prompt": row.get("memory_knowledge_compaction_prompt"),
                "compaction_prompt_template_id": row.get("compaction_prompt_template_id"),
                "audio_input": row.get("audio_input", "transcribe"),
                "memory_config": row.get("memory_config", {}),
                "knowledge_config": row.get("knowledge_config", {}),
                "filesystem_indexes": row.get("filesystem_indexes", []),
                "host_exec_config": row.get("host_exec_config", {"enabled": False}),
                "filesystem_access": row.get("filesystem_access", []),
                "display_name": row.get("display_name"),
                "avatar_url": row.get("avatar_url"),
                "integration_config": row.get("integration_config", {}),
                "tool_result_config": row.get("tool_result_config", {}),
                "knowledge_max_inject_chars": row.get("knowledge_max_inject_chars"),
                "memory_max_inject_chars": row.get("memory_max_inject_chars"),
                "delegation_config": row.get("delegation_config", {}),
                "model_params": row.get("model_params", {}),
                "bot_sandbox": row.get("bot_sandbox", {}),
                "workspace": row.get("workspace", {"enabled": False}),
                "elevation_enabled": row.get("elevation_enabled"),
                "elevation_threshold": row.get("elevation_threshold"),
                "elevated_model": row.get("elevated_model"),
                "attachment_summarization_enabled": row.get("attachment_summarization_enabled"),
                "attachment_summary_model": row.get("attachment_summary_model"),
                "attachment_text_max_chars": row.get("attachment_text_max_chars"),
                "attachment_vision_concurrency": row.get("attachment_vision_concurrency"),
                "fallback_models": row.get("fallback_models", []),
                "user_id": row.get("user_id"),
                "api_key_id": row.get("api_key_id"),
                "api_docs_mode": row.get("api_docs_mode"),
                "memory_scheme": row.get("memory_scheme"),
                "history_mode": row.get("history_mode"),
                "context_pruning": row.get("context_pruning"),
                "context_pruning_keep_turns": row.get("context_pruning_keep_turns"),
            }
            stmt = pg_insert(Bot).values(id=row["id"], **vals)
            stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=vals)
            await db.execute(stmt)
            u += 1
        _track("bots", c, u)

    if personas := payload.get("bot_personas"):
        c, u = 0, 0
        for row in personas:
            vals = {"persona_layer": row.get("persona_layer")}
            stmt = pg_insert(BotPersona).values(bot_id=row["bot_id"], **vals)
            stmt = stmt.on_conflict_do_update(index_elements=["bot_id"], set_=vals)
            await db.execute(stmt)
            u += 1
        _track("bot_personas", c, u)

    # 9. Sandbox bot access
    if sba_list := payload.get("sandbox_bot_access"):
        c, u = 0, 0
        for row in sba_list:
            stmt = pg_insert(SandboxBotAccess).values(
                bot_id=row["bot_id"], profile_id=row["profile_id"]
            )
            stmt = stmt.on_conflict_do_nothing()
            await db.execute(stmt)
            u += 1
        _track("sandbox_bot_access", c, u)

    # 10. Workspaces + workspace bots
    if workspaces := payload.get("workspaces"):
        c, u = 0, 0
        for row in workspaces:
            vals = {
                "name": row["name"],
                "description": row.get("description"),
                "image": row.get("image", "python:3.12-slim"),
                "network": row.get("network", "none"),
                "env": row.get("env", {}),
                "ports": row.get("ports", []),
                "mounts": row.get("mounts", []),
                "cpus": row.get("cpus"),
                "memory_limit": row.get("memory_limit"),
                "docker_user": row.get("docker_user"),
                "read_only_root": row.get("read_only_root", False),
                "startup_script": row.get("startup_script"),
                "workspace_skills_enabled": row.get("workspace_skills_enabled", True),
                "workspace_base_prompt_enabled": row.get("workspace_base_prompt_enabled", True),
                "indexing_config": row.get("indexing_config"),
            }
            stmt = pg_insert(SharedWorkspace).values(id=row["id"], **vals)
            stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=vals)
            await db.execute(stmt)
            u += 1

            # Workspace bots: delete + re-insert
            await db.execute(
                delete(SharedWorkspaceBot).where(SharedWorkspaceBot.workspace_id == row["id"])
            )
            for wb in row.get("bots", []):
                bot_id = wb["bot_id"] if isinstance(wb, dict) else wb
                role = wb.get("role", "member") if isinstance(wb, dict) else "member"
                cwd = wb.get("cwd_override") if isinstance(wb, dict) else None
                await db.execute(
                    pg_insert(SharedWorkspaceBot).values(
                        workspace_id=row["id"], bot_id=bot_id, role=role, cwd_override=cwd,
                    )
                )
        _track("workspaces", c, u)

    # 11. Channels
    if channels := payload.get("channels"):
        c, u = 0, 0
        for row in channels:
            vals = {
                "name": row["name"],
                "bot_id": row["bot_id"],
                "client_id": row.get("client_id"),
                "integration": row.get("integration"),
                "dispatch_config": row.get("dispatch_config"),
                "require_mention": row.get("require_mention", True),
                "passive_memory": row.get("passive_memory", True),
                "context_compaction": row.get("context_compaction", True),
                "compaction_interval": row.get("compaction_interval"),
                "compaction_keep_turns": row.get("compaction_keep_turns"),
                "compaction_model": row.get("compaction_model"),
                "memory_knowledge_compaction_prompt": row.get("memory_knowledge_compaction_prompt"),
                "compaction_prompt_template_id": row.get("compaction_prompt_template_id"),
                "compaction_workspace_file_path": row.get("compaction_workspace_file_path"),
                "compaction_workspace_id": row.get("compaction_workspace_id"),
                "elevation_enabled": row.get("elevation_enabled"),
                "elevation_threshold": row.get("elevation_threshold"),
                "elevated_model": row.get("elevated_model"),
                "model_override": row.get("model_override"),
                "model_provider_id_override": row.get("model_provider_id_override"),
                "fallback_models": row.get("fallback_models", []),
                "allow_bot_messages": row.get("allow_bot_messages", False),
                "workspace_rag": row.get("workspace_rag", True),
                "max_iterations": row.get("max_iterations"),
                "task_max_run_seconds": row.get("task_max_run_seconds"),
                "attachment_retention_days": row.get("attachment_retention_days"),
                "attachment_max_size_bytes": row.get("attachment_max_size_bytes"),
                "attachment_types_allowed": row.get("attachment_types_allowed"),
                "private": row.get("private", False),
                "user_id": row.get("user_id"),
                "local_tools_override": row.get("local_tools_override"),
                "local_tools_disabled": row.get("local_tools_disabled"),
                "mcp_servers_override": row.get("mcp_servers_override"),
                "mcp_servers_disabled": row.get("mcp_servers_disabled"),
                "client_tools_override": row.get("client_tools_override"),
                "client_tools_disabled": row.get("client_tools_disabled"),
                "pinned_tools_override": row.get("pinned_tools_override"),
                "skills_override": row.get("skills_override"),
                "skills_disabled": row.get("skills_disabled"),
                "workspace_skills_enabled": row.get("workspace_skills_enabled"),
                "workspace_base_prompt_enabled": row.get("workspace_base_prompt_enabled"),
                "history_mode": row.get("history_mode"),
                "trigger_heartbeat_before_compaction": row.get("trigger_heartbeat_before_compaction"),
                "memory_flush_enabled": row.get("memory_flush_enabled"),
                "memory_flush_model": row.get("memory_flush_model"),
                "memory_flush_model_provider_id": row.get("memory_flush_model_provider_id"),
                "memory_flush_prompt": row.get("memory_flush_prompt"),
                "memory_flush_prompt_template_id": row.get("memory_flush_prompt_template_id"),
                "memory_flush_workspace_file_path": row.get("memory_flush_workspace_file_path"),
                "memory_flush_workspace_id": row.get("memory_flush_workspace_id"),
                "channel_prompt": row.get("channel_prompt"),
                "section_index_count": row.get("section_index_count"),
                "section_index_verbosity": row.get("section_index_verbosity"),
                "context_pruning": row.get("context_pruning"),
                "context_pruning_keep_turns": row.get("context_pruning_keep_turns"),
            }
            stmt = pg_insert(Channel).values(id=row["id"], **vals)
            stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=vals)
            await db.execute(stmt)
            u += 1
        _track("channels", c, u)

    # 12. Channel integrations
    if ci_list := payload.get("channel_integrations"):
        c, u = 0, 0
        for row in ci_list:
            vals = {
                "channel_id": row["channel_id"],
                "integration_type": row["integration_type"],
                "client_id": row["client_id"],
                "dispatch_config": row.get("dispatch_config"),
                "display_name": row.get("display_name"),
            }
            # metadata needs special handling — DB column is "metadata"
            meta = row.get("metadata", {})
            stmt = pg_insert(ChannelIntegration).values(id=row["id"], **vals, **{"metadata": meta})
            update_vals = {**vals, "metadata": meta}
            stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=update_vals)
            await db.execute(stmt)
            u += 1
        _track("channel_integrations", c, u)

    # 13. Channel heartbeats
    if hb_list := payload.get("channel_heartbeats"):
        c, u = 0, 0
        for row in hb_list:
            # Parse time strings back to time objects
            quiet_start = None
            if row.get("quiet_start"):
                quiet_start = dt_time.fromisoformat(row["quiet_start"])
            quiet_end = None
            if row.get("quiet_end"):
                quiet_end = dt_time.fromisoformat(row["quiet_end"])

            vals = {
                "channel_id": row["channel_id"],
                "enabled": row.get("enabled", False),
                "interval_minutes": row.get("interval_minutes", 60),
                "model": row.get("model", ""),
                "model_provider_id": row.get("model_provider_id"),
                "fallback_models": row.get("fallback_models", []),
                "prompt": row.get("prompt", ""),
                "dispatch_results": row.get("dispatch_results", True),
                "trigger_response": row.get("trigger_response", False),
                "quiet_start": quiet_start,
                "quiet_end": quiet_end,
                "timezone": row.get("timezone"),
                "prompt_template_id": row.get("prompt_template_id"),
                "workspace_file_path": row.get("workspace_file_path"),
                "workspace_id": row.get("workspace_id"),
                "max_run_seconds": row.get("max_run_seconds"),
            }
            stmt = pg_insert(ChannelHeartbeat).values(id=row["id"], **vals)
            stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=vals)
            await db.execute(stmt)
            u += 1
        _track("channel_heartbeats", c, u)

    # 14. Tasks (recurring only)
    if tasks := payload.get("tasks"):
        c, u = 0, 0
        for row in tasks:
            if not row.get("recurrence"):
                continue
            vals = {
                "bot_id": row["bot_id"],
                "client_id": row.get("client_id"),
                "channel_id": row.get("channel_id"),
                "status": row.get("status", "pending"),
                "task_type": row.get("task_type", "agent"),
                "recurrence": row["recurrence"],
                "title": row.get("title"),
                "prompt": row.get("prompt", ""),
                "dispatch_type": row.get("dispatch_type", "none"),
                "dispatch_config": row.get("dispatch_config"),
                "callback_config": row.get("callback_config"),
                "execution_config": row.get("execution_config"),
                "prompt_template_id": row.get("prompt_template_id"),
                "workspace_file_path": row.get("workspace_file_path"),
                "workspace_id": row.get("workspace_id"),
                "max_run_seconds": row.get("max_run_seconds"),
            }
            stmt = pg_insert(Task).values(id=row["id"], **vals)
            stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=vals)
            await db.execute(stmt)
            u += 1
        _track("tasks", c, u)

    # 15. Tool policy rules
    if rules := payload.get("tool_policy_rules"):
        c, u = 0, 0
        for row in rules:
            vals = {
                "bot_id": row.get("bot_id"),
                "tool_name": row["tool_name"],
                "action": row["action"],
                "conditions": row.get("conditions", {}),
                "priority": row.get("priority", 100),
                "approval_timeout": row.get("approval_timeout", 300),
                "reason": row.get("reason"),
                "enabled": row.get("enabled", True),
            }
            stmt = pg_insert(ToolPolicyRule).values(id=row["id"], **vals)
            stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=vals)
            await db.execute(stmt)
            u += 1
        _track("tool_policy_rules", c, u)

    await db.commit()

    # Reload in-memory registries
    try:
        from app.agent.bots import load_bots
        from app.services.providers import load_providers
        await load_bots()
        await load_providers()
    except Exception as e:
        log.warning("Post-restore reload failed: %s", e)

    return {"status": "ok", "summary": summary}
