"""Config-state snapshot restore service."""
from __future__ import annotations

from datetime import time as dt_time
from typing import Any

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
from app.services.heartbeat_policy import normalize_heartbeat_execution_policy


RestoreSummary = dict[str, dict[str, int]]


def _track(summary: RestoreSummary, section: str, created: int, updated: int) -> None:
    summary[section] = {"created": created, "updated": updated}


def _time_from_snapshot(value: str | None) -> dt_time | None:
    return dt_time.fromisoformat(value) if value else None


def _channel_heartbeat_values(row: dict[str, Any]) -> dict[str, Any]:
    execution_policy = row.get("execution_policy")
    if execution_policy is not None:
        execution_policy = normalize_heartbeat_execution_policy(execution_policy)

    return {
        "channel_id": row["channel_id"],
        "enabled": row.get("enabled", False),
        "interval_minutes": row.get("interval_minutes", 60),
        "model": row.get("model", ""),
        "model_provider_id": row.get("model_provider_id"),
        "fallback_models": row.get("fallback_models", []),
        "prompt": row.get("prompt", ""),
        "dispatch_results": row.get("dispatch_results", True),
        "trigger_response": row.get("trigger_response", False),
        "quiet_start": _time_from_snapshot(row.get("quiet_start")),
        "quiet_end": _time_from_snapshot(row.get("quiet_end")),
        "timezone": row.get("timezone"),
        "prompt_template_id": row.get("prompt_template_id"),
        "workspace_file_path": row.get("workspace_file_path"),
        "workspace_id": row.get("workspace_id"),
        "max_run_seconds": row.get("max_run_seconds"),
        "append_spatial_prompt": row.get("append_spatial_prompt", False),
        "append_spatial_map_overview": row.get("append_spatial_map_overview", False),
        "execution_policy": execution_policy,
    }


async def _restore_channel_heartbeats(
    payload: dict[str, Any],
    db: AsyncSession,
    summary: RestoreSummary,
) -> None:
    if not (hb_list := payload.get("channel_heartbeats")):
        return

    created, updated = 0, 0
    for row in hb_list:
        vals = _channel_heartbeat_values(row)
        stmt = pg_insert(ChannelHeartbeat).values(id=row["id"], **vals)
        stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=vals)
        await db.execute(stmt)
        updated += 1
    _track(summary, "channel_heartbeats", created, updated)


def _provider_values(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "display_name": row["display_name"],
        "provider_type": row["provider_type"],
        "is_enabled": row.get("is_enabled", True),
        "base_url": row.get("base_url"),
        "api_key": row.get("api_key"),
        "tpm_limit": row.get("tpm_limit"),
        "rpm_limit": row.get("rpm_limit"),
        "config": row.get("config", {}),
    }


def _provider_model_values(provider_id: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider_id": provider_id,
        "model_id": row["model_id"],
        "display_name": row.get("display_name"),
        "max_tokens": row.get("max_tokens"),
        "input_cost_per_1m": row.get("input_cost_per_1m"),
        "output_cost_per_1m": row.get("output_cost_per_1m"),
        "no_system_messages": row.get("no_system_messages", False),
        "supports_vision": row.get("supports_vision", True),
    }


async def _restore_providers(
    payload: dict[str, Any],
    db: AsyncSession,
    summary: RestoreSummary,
) -> None:
    if not (providers := payload.get("providers")):
        return

    created, updated = 0, 0
    for row in providers:
        vals = _provider_values(row)
        stmt = pg_insert(ProviderConfig).values(id=row["id"], **vals)
        stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=vals)
        await db.execute(stmt)
        updated += 1

        await db.execute(delete(ProviderModel).where(ProviderModel.provider_id == row["id"]))
        for model in row.get("models", []):
            await db.execute(pg_insert(ProviderModel).values(**_provider_model_values(row["id"], model)))
    _track(summary, "providers", created, updated)


def _bot_values(row: dict[str, Any]) -> dict[str, Any]:
    return {
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
        "avatar_emoji": row.get("avatar_emoji"),
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


async def _restore_bots(
    payload: dict[str, Any],
    db: AsyncSession,
    summary: RestoreSummary,
) -> None:
    if not (bots := payload.get("bots")):
        return

    created, updated = 0, 0
    for row in bots:
        vals = _bot_values(row)
        stmt = pg_insert(Bot).values(id=row["id"], **vals)
        stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=vals)
        await db.execute(stmt)
        updated += 1
    _track(summary, "bots", created, updated)


def _workspace_values(row: dict[str, Any]) -> dict[str, Any]:
    return {
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


async def _restore_workspaces(
    payload: dict[str, Any],
    db: AsyncSession,
    summary: RestoreSummary,
) -> None:
    if not (workspaces := payload.get("workspaces")):
        return

    created, updated = 0, 0
    for row in workspaces:
        vals = _workspace_values(row)
        stmt = pg_insert(SharedWorkspace).values(id=row["id"], **vals)
        stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=vals)
        await db.execute(stmt)
        updated += 1

        await db.execute(delete(SharedWorkspaceBot).where(SharedWorkspaceBot.workspace_id == row["id"]))
        for workspace_bot in row.get("bots", []):
            bot_id = workspace_bot["bot_id"] if isinstance(workspace_bot, dict) else workspace_bot
            role = workspace_bot.get("role", "member") if isinstance(workspace_bot, dict) else "member"
            cwd = workspace_bot.get("cwd_override") if isinstance(workspace_bot, dict) else None
            await db.execute(
                pg_insert(SharedWorkspaceBot).values(
                    workspace_id=row["id"],
                    bot_id=bot_id,
                    role=role,
                    cwd_override=cwd,
                )
            )
    _track(summary, "workspaces", created, updated)


def _channel_values(row: dict[str, Any]) -> dict[str, Any]:
    return {
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


async def _restore_channels(
    payload: dict[str, Any],
    db: AsyncSession,
    summary: RestoreSummary,
) -> None:
    if not (channels := payload.get("channels")):
        return

    created, updated = 0, 0
    for row in channels:
        vals = _channel_values(row)
        stmt = pg_insert(Channel).values(id=row["id"], **vals)
        stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=vals)
        await db.execute(stmt)
        updated += 1
    _track(summary, "channels", created, updated)


async def _restore_users(payload: dict[str, Any], db: AsyncSession, summary: RestoreSummary) -> None:
    if not (users := payload.get("users")):
        return

    created, updated = 0, 0
    for row in users:
        vals = {
            "email": row["email"],
            "display_name": row["display_name"],
            "avatar_url": row.get("avatar_url"),
            "auth_method": row.get("auth_method", "local"),
            "is_admin": row.get("is_admin", False),
            "is_active": row.get("is_active", True),
        }
        stmt = pg_insert(User).values(id=row["id"], **vals)
        stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=vals)
        result = await db.execute(stmt)
        if result.rowcount:
            updated += 1
    _track(summary, "users", created, updated)


async def _restore_server_config(payload: dict[str, Any], db: AsyncSession, summary: RestoreSummary) -> None:
    if not (sc_list := payload.get("server_config")):
        return

    created, updated = 0, 0
    for row in sc_list:
        vals = {"global_fallback_models": row["global_fallback_models"]}
        stmt = pg_insert(ServerConfig).values(id=row.get("id", "default"), **vals)
        stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=vals)
        await db.execute(stmt)
        updated += 1
    _track(summary, "server_config", created, updated)


async def _restore_server_settings(payload: dict[str, Any], db: AsyncSession, summary: RestoreSummary) -> None:
    if not (ss_list := payload.get("server_settings")):
        return

    created, updated = 0, 0
    for row in ss_list:
        vals = {"value": row["value"]}
        stmt = pg_insert(ServerSetting).values(key=row["key"], **vals)
        stmt = stmt.on_conflict_do_update(index_elements=["key"], set_=vals)
        await db.execute(stmt)
        updated += 1
    _track(summary, "server_settings", created, updated)


async def _restore_mcp_servers(payload: dict[str, Any], db: AsyncSession, summary: RestoreSummary) -> None:
    if not (mcp_servers := payload.get("mcp_servers")):
        return

    created, updated = 0, 0
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
        updated += 1
    _track(summary, "mcp_servers", created, updated)


async def _restore_prompt_templates(payload: dict[str, Any], db: AsyncSession, summary: RestoreSummary) -> None:
    if not (templates := payload.get("prompt_templates")):
        return

    created, updated = 0, 0
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
        updated += 1
    _track(summary, "prompt_templates", created, updated)


async def _restore_skills(payload: dict[str, Any], db: AsyncSession, summary: RestoreSummary) -> None:
    if not (skills := payload.get("skills")):
        return

    created, updated = 0, 0
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
        updated += 1
    _track(summary, "skills", created, updated)


async def _restore_sandbox_profiles(payload: dict[str, Any], db: AsyncSession, summary: RestoreSummary) -> None:
    if not (profiles := payload.get("sandbox_profiles")):
        return

    created, updated = 0, 0
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
        updated += 1
    _track(summary, "sandbox_profiles", created, updated)


async def _restore_bot_personas(payload: dict[str, Any], db: AsyncSession, summary: RestoreSummary) -> None:
    if not (personas := payload.get("bot_personas")):
        return

    created, updated = 0, 0
    for row in personas:
        vals = {"persona_layer": row.get("persona_layer")}
        stmt = pg_insert(BotPersona).values(bot_id=row["bot_id"], **vals)
        stmt = stmt.on_conflict_do_update(index_elements=["bot_id"], set_=vals)
        await db.execute(stmt)
        updated += 1
    _track(summary, "bot_personas", created, updated)


async def _restore_sandbox_bot_access(payload: dict[str, Any], db: AsyncSession, summary: RestoreSummary) -> None:
    if not (sba_list := payload.get("sandbox_bot_access")):
        return

    created, updated = 0, 0
    for row in sba_list:
        stmt = pg_insert(SandboxBotAccess).values(
            bot_id=row["bot_id"],
            profile_id=row["profile_id"],
        )
        stmt = stmt.on_conflict_do_nothing()
        await db.execute(stmt)
        updated += 1
    _track(summary, "sandbox_bot_access", created, updated)


async def _restore_channel_integrations(payload: dict[str, Any], db: AsyncSession, summary: RestoreSummary) -> None:
    if not (ci_list := payload.get("channel_integrations")):
        return

    created, updated = 0, 0
    for row in ci_list:
        vals = {
            "channel_id": row["channel_id"],
            "integration_type": row["integration_type"],
            "client_id": row["client_id"],
            "dispatch_config": row.get("dispatch_config"),
            "display_name": row.get("display_name"),
        }
        metadata = row.get("metadata", {})
        stmt = pg_insert(ChannelIntegration).values(id=row["id"], **vals, **{"metadata": metadata})
        stmt = stmt.on_conflict_do_update(index_elements=["id"], set_={**vals, "metadata": metadata})
        await db.execute(stmt)
        updated += 1
    _track(summary, "channel_integrations", created, updated)


async def _restore_tasks(payload: dict[str, Any], db: AsyncSession, summary: RestoreSummary) -> None:
    if not (tasks := payload.get("tasks")):
        return

    created, updated = 0, 0
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
        updated += 1
    _track(summary, "tasks", created, updated)


async def _restore_backup_config(payload: dict[str, Any], db: AsyncSession, summary: RestoreSummary) -> None:
    if not (backup_cfg := payload.get("backup_config")):
        return

    created, updated = 0, 0
    for short_key, value in backup_cfg.items():
        full_key = f"backup.{short_key}"
        vals = {"value": str(value)}
        stmt = pg_insert(ServerSetting).values(key=full_key, **vals)
        stmt = stmt.on_conflict_do_update(index_elements=["key"], set_=vals)
        await db.execute(stmt)
        updated += 1
    _track(summary, "backup_config", created, updated)


async def _restore_tool_policy_rules(payload: dict[str, Any], db: AsyncSession, summary: RestoreSummary) -> None:
    if not (rules := payload.get("tool_policy_rules")):
        return

    created, updated = 0, 0
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
        updated += 1
    _track(summary, "tool_policy_rules", created, updated)


async def restore_config_state_snapshot(payload: dict[str, Any], db: AsyncSession) -> RestoreSummary:
    """Upsert all records from a config-state snapshot in FK-dependency order.

    Returns a summary of created/updated counts per section. The caller owns
    transaction commit/rollback.
    """
    summary: RestoreSummary = {}
    await _restore_users(payload, db, summary)
    await _restore_server_config(payload, db, summary)
    await _restore_server_settings(payload, db, summary)
    await _restore_providers(payload, db, summary)
    await _restore_mcp_servers(payload, db, summary)
    await _restore_prompt_templates(payload, db, summary)
    await _restore_skills(payload, db, summary)
    await _restore_sandbox_profiles(payload, db, summary)
    await _restore_bots(payload, db, summary)
    await _restore_bot_personas(payload, db, summary)
    await _restore_sandbox_bot_access(payload, db, summary)
    await _restore_workspaces(payload, db, summary)
    await _restore_channels(payload, db, summary)
    await _restore_channel_integrations(payload, db, summary)
    await _restore_channel_heartbeats(payload, db, summary)
    await _restore_tasks(payload, db, summary)
    await _restore_backup_config(payload, db, summary)
    await _restore_tool_policy_rules(payload, db, summary)
    return summary
