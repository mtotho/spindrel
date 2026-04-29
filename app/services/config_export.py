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


def _system_snapshot() -> dict:
    return {
        "paused": getattr(settings, "SYSTEM_PAUSED", False),
        "pause_behavior": getattr(settings, "SYSTEM_PAUSE_BEHAVIOR", "queue"),
    }


def _provider_model_snapshot(model) -> dict:
    return {
        "id": model.id,
        "provider_id": model.provider_id,
        "model_id": model.model_id,
        "display_name": model.display_name,
        "max_tokens": model.max_tokens,
        "context_window": model.context_window,
        "max_output_tokens": model.max_output_tokens,
        "input_cost_per_1m": model.input_cost_per_1m,
        "output_cost_per_1m": model.output_cost_per_1m,
        "cached_input_cost_per_1m": model.cached_input_cost_per_1m,
        "no_system_messages": model.no_system_messages,
        "supports_tools": model.supports_tools,
        "supports_vision": model.supports_vision,
        "supports_reasoning": model.supports_reasoning,
        "supports_prompt_caching": model.supports_prompt_caching,
        "supports_structured_output": model.supports_structured_output,
        "supports_image_generation": model.supports_image_generation,
        "prompt_style": model.prompt_style,
        "extra_body": model.extra_body,
    }


def _provider_snapshot(provider) -> dict:
    return {
        "id": provider.id,
        "display_name": provider.display_name,
        "provider_type": provider.provider_type,
        "is_enabled": provider.is_enabled,
        "base_url": provider.base_url,
        "api_key": provider.api_key,
        "tpm_limit": provider.tpm_limit,
        "rpm_limit": provider.rpm_limit,
        "config": provider.config,
        "billing_type": provider.billing_type,
        "plan_cost": provider.plan_cost,
        "plan_period": provider.plan_period,
        "models": [_provider_model_snapshot(model) for model in provider.models],
    }


def _bot_snapshot(bot) -> dict:
    return {
        "id": bot.id,
        "name": bot.name,
        "model": bot.model,
        "model_provider_id": bot.model_provider_id,
        "system_prompt": bot.system_prompt,
        "local_tools": bot.local_tools,
        "mcp_servers": bot.mcp_servers,
        "client_tools": bot.client_tools,
        "pinned_tools": bot.pinned_tools,
        "skills": bot.skills,
        "docker_sandbox_profiles": bot.docker_sandbox_profiles,
        "tool_retrieval": bot.tool_retrieval,
        "tool_similarity_threshold": bot.tool_similarity_threshold,
        "persona": bot.persona,
        "context_compaction": bot.context_compaction,
        "compaction_interval": bot.compaction_interval,
        "compaction_keep_turns": bot.compaction_keep_turns,
        "compaction_model": bot.compaction_model,
        "compaction_model_provider_id": bot.compaction_model_provider_id,
        "memory_knowledge_compaction_prompt": bot.memory_knowledge_compaction_prompt,
        "compaction_prompt_template_id": _str(bot.compaction_prompt_template_id),
        "audio_input": bot.audio_input,
        "memory_config": bot.memory_config,
        "filesystem_indexes": bot.filesystem_indexes,
        "host_exec_config": bot.host_exec_config,
        "filesystem_access": bot.filesystem_access,
        "display_name": bot.display_name,
        "avatar_url": bot.avatar_url,
        "avatar_emoji": getattr(bot, "avatar_emoji", None),
        "integration_config": bot.integration_config,
        "tool_result_config": bot.tool_result_config,
        "memory_max_inject_chars": bot.memory_max_inject_chars,
        "delegation_config": bot.delegation_config,
        "model_params": bot.model_params,
        "bot_sandbox": bot.bot_sandbox,
        "workspace": bot.workspace,
        "attachment_summarization_enabled": bot.attachment_summarization_enabled,
        "attachment_summary_model": bot.attachment_summary_model,
        "attachment_summary_model_provider_id": bot.attachment_summary_model_provider_id,
        "attachment_text_max_chars": bot.attachment_text_max_chars,
        "attachment_vision_concurrency": bot.attachment_vision_concurrency,
        "fallback_models": bot.fallback_models,
        "user_id": _str(bot.user_id),
        "api_key_id": _str(bot.api_key_id),
        "memory_scheme": bot.memory_scheme,
        "history_mode": bot.history_mode,
        "context_pruning": bot.context_pruning,
    }


def _channel_snapshot(channel) -> dict:
    return {
        "id": str(channel.id),
        "name": channel.name,
        "bot_id": channel.bot_id,
        "client_id": channel.client_id,
        "integration": channel.integration,
        "dispatch_config": channel.dispatch_config,
        "require_mention": channel.require_mention,
        "passive_memory": channel.passive_memory,
        "context_compaction": channel.context_compaction,
        "compaction_interval": channel.compaction_interval,
        "compaction_keep_turns": channel.compaction_keep_turns,
        "compaction_model": channel.compaction_model,
        "compaction_model_provider_id": channel.compaction_model_provider_id,
        "memory_knowledge_compaction_prompt": channel.memory_knowledge_compaction_prompt,
        "compaction_prompt_template_id": _str(channel.compaction_prompt_template_id),
        "compaction_workspace_file_path": channel.compaction_workspace_file_path,
        "compaction_workspace_id": _str(channel.compaction_workspace_id),
        "model_override": channel.model_override,
        "model_provider_id_override": channel.model_provider_id_override,
        "fallback_models": channel.fallback_models,
        "allow_bot_messages": channel.allow_bot_messages,
        "workspace_rag": channel.workspace_rag,
        "thinking_display": channel.thinking_display,
        "tool_output_display": channel.tool_output_display,
        "max_iterations": channel.max_iterations,
        "task_max_run_seconds": channel.task_max_run_seconds,
        "attachment_retention_days": channel.attachment_retention_days,
        "attachment_max_size_bytes": channel.attachment_max_size_bytes,
        "attachment_types_allowed": channel.attachment_types_allowed,
        "private": channel.private,
        "user_id": _str(channel.user_id),
        "local_tools_disabled": channel.local_tools_disabled,
        "mcp_servers_disabled": channel.mcp_servers_disabled,
        "client_tools_disabled": channel.client_tools_disabled,
        "model_tier_overrides": channel.model_tier_overrides,
        "workspace_base_prompt_enabled": channel.workspace_base_prompt_enabled,
        "history_mode": channel.history_mode,
        "trigger_heartbeat_before_compaction": channel.trigger_heartbeat_before_compaction,
        "memory_flush_enabled": channel.memory_flush_enabled,
        "memory_flush_model": channel.memory_flush_model,
        "memory_flush_model_provider_id": channel.memory_flush_model_provider_id,
        "memory_flush_prompt": channel.memory_flush_prompt,
        "memory_flush_prompt_template_id": _str(channel.memory_flush_prompt_template_id),
        "memory_flush_workspace_file_path": channel.memory_flush_workspace_file_path,
        "memory_flush_workspace_id": _str(channel.memory_flush_workspace_id),
        "channel_prompt": channel.channel_prompt,
        "channel_prompt_workspace_file_path": channel.channel_prompt_workspace_file_path,
        "channel_prompt_workspace_id": _str(channel.channel_prompt_workspace_id),
        "section_index_count": channel.section_index_count,
        "section_index_verbosity": channel.section_index_verbosity,
        "context_pruning": channel.context_pruning,
        "workspace_id": _str(channel.workspace_id),
        "protected": channel.protected,
        "config": channel.config,
        "metadata": channel.metadata_,
    }


def _workspace_snapshot(workspace) -> dict:
    return {
        "id": str(workspace.id),
        "name": workspace.name,
        "description": workspace.description,
        "env": workspace.env,
        "workspace_base_prompt_enabled": workspace.workspace_base_prompt_enabled,
        "indexing_config": workspace.indexing_config,
        "write_protected_paths": workspace.write_protected_paths,
        "bots": [
            {"bot_id": wb.bot_id, "role": wb.role, "cwd_override": wb.cwd_override}
            for wb in workspace.bots
        ],
    }


def _channel_heartbeat_snapshot(heartbeat) -> dict:
    return {
        "id": str(heartbeat.id),
        "channel_id": str(heartbeat.channel_id),
        "enabled": heartbeat.enabled,
        "interval_minutes": heartbeat.interval_minutes,
        "model": heartbeat.model,
        "model_provider_id": heartbeat.model_provider_id,
        "fallback_models": heartbeat.fallback_models,
        "prompt": heartbeat.prompt,
        "dispatch_results": heartbeat.dispatch_results,
        "trigger_response": heartbeat.trigger_response,
        "quiet_start": _time_str(heartbeat.quiet_start),
        "quiet_end": _time_str(heartbeat.quiet_end),
        "timezone": heartbeat.timezone,
        "prompt_template_id": _str(heartbeat.prompt_template_id),
        "workspace_file_path": heartbeat.workspace_file_path,
        "workspace_id": _str(heartbeat.workspace_id),
        "max_run_seconds": heartbeat.max_run_seconds,
        "append_spatial_prompt": heartbeat.append_spatial_prompt,
        "append_spatial_map_overview": heartbeat.append_spatial_map_overview,
        "execution_policy": heartbeat.execution_policy,
    }


async def _settings_snapshot() -> dict[str, dict]:
    from app.services.server_settings import get_all_settings

    settings_groups = await get_all_settings()
    return {
        group["group"]: {setting["key"]: setting["value"] for setting in group["settings"]}
        for group in settings_groups
    }


async def _server_settings_snapshots(db) -> tuple[list[dict], dict]:
    from sqlalchemy import select

    from app.db.models import ServerSetting

    rows = (await db.execute(select(ServerSetting))).scalars().all()
    server_settings = [{"key": row.key, "value": row.value} for row in rows]
    backup_config = {
        row.key[len("backup."):]: row.value
        for row in rows
        if row.key.startswith("backup.")
    }
    return server_settings, backup_config


async def _server_config_snapshots(db) -> list[dict]:
    from sqlalchemy import select

    from app.db.models import ServerConfig

    rows = (await db.execute(select(ServerConfig))).scalars().all()
    return [
        {"id": row.id, "global_fallback_models": row.global_fallback_models}
        for row in rows
    ]


async def _provider_snapshots(db) -> list[dict]:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.db.models import ProviderConfig

    rows = (
        await db.execute(
            select(ProviderConfig).options(selectinload(ProviderConfig.models))
        )
    ).scalars().all()
    return [_provider_snapshot(row) for row in rows]


async def _mcp_server_snapshots(db) -> list[dict]:
    from sqlalchemy import select

    from app.db.models import MCPServer

    rows = (await db.execute(select(MCPServer))).scalars().all()
    return [
        {
            "id": row.id,
            "display_name": row.display_name,
            "url": row.url,
            "api_key": row.api_key,
            "is_enabled": row.is_enabled,
            "config": row.config,
            "source": row.source,
            "source_path": row.source_path,
        }
        for row in rows
    ]


async def _bot_snapshots(db) -> list[dict]:
    from sqlalchemy import select

    from app.db.models import Bot

    rows = (await db.execute(select(Bot))).scalars().all()
    return [_bot_snapshot(row) for row in rows]


async def _channel_snapshots(db) -> list[dict]:
    from sqlalchemy import select

    from app.db.models import Channel

    rows = (await db.execute(select(Channel))).scalars().all()
    return [_channel_snapshot(row) for row in rows]


async def _workspace_snapshots(db) -> list[dict]:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.db.models import SharedWorkspace

    rows = (
        await db.execute(
            select(SharedWorkspace).options(selectinload(SharedWorkspace.bots))
        )
    ).scalars().all()
    return [_workspace_snapshot(row) for row in rows]


async def _skill_snapshots(db) -> list[dict]:
    from sqlalchemy import func, select

    from app.db.models import Document, Skill

    rows = (await db.execute(select(Skill))).scalars().all()
    chunk_counts = (
        await db.execute(
            select(Document.source, func.count()).group_by(Document.source)
        )
    )
    chunk_map = {row[0]: row[1] for row in chunk_counts.all()}
    return [
        {
            "id": row.id,
            "name": row.name,
            "content": row.content,
            "scripts": row.scripts,
            "content_hash": row.content_hash,
            "source_path": row.source_path,
            "source_type": row.source_type,
            "chunk_count": chunk_map.get(row.id, 0),
        }
        for row in rows
    ]


async def _task_snapshots(db) -> list[dict]:
    from sqlalchemy import select

    from app.db.models import Task

    rows = (
        await db.execute(
            select(Task).where(Task.recurrence.isnot(None))
        )
    ).scalars().all()
    return [
        {
            "id": str(row.id),
            "bot_id": row.bot_id,
            "client_id": row.client_id,
            "channel_id": _str(row.channel_id),
            "status": row.status,
            "task_type": row.task_type,
            "recurrence": row.recurrence,
            "title": row.title,
            "prompt": row.prompt,
            "dispatch_type": row.dispatch_type,
            "dispatch_config": row.dispatch_config,
            "callback_config": row.callback_config,
            "execution_config": row.execution_config,
            "prompt_template_id": _str(row.prompt_template_id),
            "workspace_file_path": row.workspace_file_path,
            "workspace_id": _str(row.workspace_id),
            "max_run_seconds": row.max_run_seconds,
        }
        for row in rows
    ]


async def _user_snapshots(db) -> list[dict]:
    from sqlalchemy import select

    from app.db.models import User

    rows = (await db.execute(select(User))).scalars().all()
    return [
        {
            "id": str(row.id),
            "email": row.email,
            "display_name": row.display_name,
            "avatar_url": row.avatar_url,
            "auth_method": row.auth_method,
            "is_admin": row.is_admin,
            "is_active": row.is_active,
        }
        for row in rows
    ]


async def _sandbox_profile_snapshots(db) -> list[dict]:
    from sqlalchemy import select

    from app.db.models import SandboxProfile

    rows = (await db.execute(select(SandboxProfile))).scalars().all()
    return [
        {
            "id": str(row.id),
            "name": row.name,
            "description": row.description,
            "image": row.image,
            "scope_mode": row.scope_mode,
            "network_mode": row.network_mode,
            "read_only_root": row.read_only_root,
            "create_options": row.create_options,
            "mount_specs": row.mount_specs,
            "env": row.env,
            "labels": row.labels,
            "port_mappings": row.port_mappings,
            "idle_ttl_seconds": row.idle_ttl_seconds,
            "enabled": row.enabled,
        }
        for row in rows
    ]


async def _sandbox_bot_access_snapshots(db) -> list[dict]:
    from sqlalchemy import select

    from app.db.models import SandboxBotAccess

    rows = (await db.execute(select(SandboxBotAccess))).scalars().all()
    return [
        {"bot_id": row.bot_id, "profile_id": str(row.profile_id)}
        for row in rows
    ]


async def _tool_policy_rule_snapshots(db) -> list[dict]:
    from sqlalchemy import select

    from app.db.models import ToolPolicyRule

    rows = (await db.execute(select(ToolPolicyRule))).scalars().all()
    return [
        {
            "id": str(row.id),
            "bot_id": row.bot_id,
            "tool_name": row.tool_name,
            "action": row.action,
            "conditions": row.conditions,
            "priority": row.priority,
            "approval_timeout": row.approval_timeout,
            "reason": row.reason,
            "enabled": row.enabled,
        }
        for row in rows
    ]


async def _prompt_template_snapshots(db) -> list[dict]:
    from sqlalchemy import select

    from app.db.models import PromptTemplate

    rows = (await db.execute(select(PromptTemplate))).scalars().all()
    return [
        {
            "id": str(row.id),
            "name": row.name,
            "description": row.description,
            "content": row.content,
            "category": row.category,
            "tags": row.tags,
            "workspace_id": _str(row.workspace_id),
            "source_type": row.source_type,
            "source_path": row.source_path,
            "content_hash": row.content_hash,
        }
        for row in rows
    ]


async def _bot_persona_snapshots(db) -> list[dict]:
    from sqlalchemy import select

    from app.db.models import BotPersona

    rows = (await db.execute(select(BotPersona))).scalars().all()
    return [
        {"bot_id": row.bot_id, "persona_layer": row.persona_layer}
        for row in rows
    ]


async def _channel_integration_snapshots(db) -> list[dict]:
    from sqlalchemy import select

    from app.db.models import ChannelIntegration

    rows = (await db.execute(select(ChannelIntegration))).scalars().all()
    return [
        {
            "id": str(row.id),
            "channel_id": str(row.channel_id),
            "integration_type": row.integration_type,
            "client_id": row.client_id,
            "dispatch_config": row.dispatch_config,
            "display_name": row.display_name,
            "metadata": row.metadata_,
        }
        for row in rows
    ]


async def _channel_heartbeat_snapshots(db) -> list[dict]:
    from sqlalchemy import select

    from app.db.models import ChannelHeartbeat

    rows = (await db.execute(select(ChannelHeartbeat))).scalars().all()
    return [_channel_heartbeat_snapshot(row) for row in rows]


# ---------------------------------------------------------------------------
# Assemble full config state dict
# ---------------------------------------------------------------------------

async def assemble_config_state(db) -> dict:
    """Build the full config-state dict from DB. Shared by GET endpoint and file export."""
    from app.services.server_config import get_global_fallback_models

    server_settings, backup_config = await _server_settings_snapshots(db)

    return {
        "system": _system_snapshot(),
        "global_fallback_models": get_global_fallback_models(),
        "settings": await _settings_snapshot(),
        "server_settings": server_settings,
        "server_config": await _server_config_snapshots(db),
        "providers": await _provider_snapshots(db),
        "mcp_servers": await _mcp_server_snapshots(db),
        "bots": await _bot_snapshots(db),
        "channels": await _channel_snapshots(db),
        "workspaces": await _workspace_snapshots(db),
        "skills": await _skill_snapshots(db),
        "tasks": await _task_snapshots(db),
        "users": await _user_snapshots(db),
        "sandbox_profiles": await _sandbox_profile_snapshots(db),
        "sandbox_bot_access": await _sandbox_bot_access_snapshots(db),
        "tool_policy_rules": await _tool_policy_rule_snapshots(db),
        "prompt_templates": await _prompt_template_snapshots(db),
        "bot_personas": await _bot_persona_snapshots(db),
        "channel_integrations": await _channel_integration_snapshots(db),
        "channel_heartbeats": await _channel_heartbeat_snapshots(db),
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
        from app.services.config_state_restore import restore_config_state_snapshot

        summary = await restore_config_state_snapshot(payload, db)
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
