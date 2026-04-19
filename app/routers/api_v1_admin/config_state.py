"""Config state: GET /config-state (full backup), POST /config-state/restore (upsert)."""
from __future__ import annotations

import logging
from datetime import time as dt_time

from fastapi import APIRouter, Depends
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Bot,
    BotPersona,
    Channel,
    ChannelHeartbeat,
    ChannelIntegration,
    MCPServer,
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
from app.dependencies import get_db, require_scopes

log = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# GET  /config-state  —  full config backup
# ---------------------------------------------------------------------------

@router.get("/config-state")
async def get_config_state(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("admin")),
):
    from app.services.config_export import assemble_config_state
    return await assemble_config_state(db)


# ---------------------------------------------------------------------------
# Restore logic (shared by POST endpoint and file restore)
# ---------------------------------------------------------------------------

async def do_restore(payload: dict, db: AsyncSession) -> dict:
    """Upsert all records from a config-state snapshot in FK-dependency order.

    Returns a summary of created/updated counts per section.
    Does NOT commit — caller is responsible for committing.
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
                    "supports_vision": m.get("supports_vision", True),
                }
                await db.execute(pg_insert(ProviderModel).values(**m_vals))
        _track("providers", c, u)

    # 4b. MCP Servers
    if mcp_servers := payload.get("mcp_servers"):
        c, u = 0, 0
        for row in mcp_servers:
            vals = {
                "display_name": row["display_name"],
                "url": row["url"],
                "api_key": row.get("api_key"),
                "is_enabled": row.get("is_enabled", True),
                "config": row.get("config", {}),
                "source": row.get("source", "manual"),
                "source_path": row.get("source_path"),
            }
            stmt = pg_insert(MCPServer).values(id=row["id"], **vals)
            stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=vals)
            await db.execute(stmt)
            u += 1
        _track("mcp_servers", c, u)

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
                "filesystem_indexes": row.get("filesystem_indexes", []),
                "host_exec_config": row.get("host_exec_config", {"enabled": False}),
                "filesystem_access": row.get("filesystem_access", []),
                "display_name": row.get("display_name"),
                "avatar_url": row.get("avatar_url"),
                "integration_config": row.get("integration_config", {}),
                "tool_result_config": row.get("tool_result_config", {}),
                "memory_max_inject_chars": row.get("memory_max_inject_chars"),
                "delegation_config": row.get("delegation_config", {}),
                "model_params": row.get("model_params", {}),
                "bot_sandbox": row.get("bot_sandbox", {}),
                "workspace": row.get("workspace", {"enabled": False}),
                "attachment_summarization_enabled": row.get("attachment_summarization_enabled"),
                "attachment_summary_model": row.get("attachment_summary_model"),
                "attachment_text_max_chars": row.get("attachment_text_max_chars"),
                "attachment_vision_concurrency": row.get("attachment_vision_concurrency"),
                "fallback_models": row.get("fallback_models", []),
                "user_id": row.get("user_id"),
                "api_key_id": row.get("api_key_id"),
                "memory_scheme": row.get("memory_scheme"),
                "history_mode": row.get("history_mode"),
                "context_pruning": row.get("context_pruning"),
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
                "local_tools_disabled": row.get("local_tools_disabled"),
                "mcp_servers_disabled": row.get("mcp_servers_disabled"),
                "client_tools_disabled": row.get("client_tools_disabled"),
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

    # 15. Backup config (backup.* keys in server_settings)
    if backup_cfg := payload.get("backup_config"):
        c, u = 0, 0
        for short_key, value in backup_cfg.items():
            full_key = f"backup.{short_key}"
            vals = {"value": str(value)}
            stmt = pg_insert(ServerSetting).values(key=full_key, **vals)
            stmt = stmt.on_conflict_do_update(index_elements=["key"], set_=vals)
            await db.execute(stmt)
            u += 1
        _track("backup_config", c, u)

    # 16. Tool policy rules
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

    return summary


# ---------------------------------------------------------------------------
# POST /config-state/restore  —  upsert from backup JSON
# ---------------------------------------------------------------------------

@router.post("/config-state/restore")
async def restore_config_state(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("admin")),
):
    """Restore config from a backup JSON snapshot."""
    summary = await do_restore(payload, db)
    await db.commit()

    # Reload in-memory registries
    try:
        from app.agent.bots import load_bots
        from app.services.mcp_servers import load_mcp_servers
        from app.services.providers import load_providers
        await load_bots()
        await load_providers()
        await load_mcp_servers()
    except Exception as e:
        log.warning("Post-restore reload failed: %s", e)

    return {"status": "ok", "summary": summary}
