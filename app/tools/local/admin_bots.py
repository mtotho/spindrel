"""Admin tool: bot management for the orchestrator bot."""
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.engine import async_session
from app.db.models import Bot as BotRow
from app.tools.registry import register

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "manage_bot",
        "description": (
            "Create, update, delete, list, or get bot configuration. "
            "Actions: list, get, create, update, delete. "
            "For create/update, pass config with keys like: name, model, "
            "system_prompt, skills, local_tools, workspace, memory_scheme, "
            "delegate_bots, context_compaction, tool_retrieval, etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "create", "update", "delete"],
                    "description": "The action to perform.",
                },
                "bot_id": {
                    "type": "string",
                    "description": "Bot ID (required for get, create, update).",
                },
                "config": {
                    "type": "object",
                    "description": (
                        "Bot configuration for create/update. Keys: name, model, "
                        "system_prompt, local_tools (list), skills (list of {id, mode}), "
                        "workspace ({enabled: bool}), memory_scheme ('workspace-files' or null), "
                        "context_compaction (bool), tool_retrieval (bool), "
                        "delegate_bots (list), "
                        "pinned_tools (list), mcp_servers (list), client_tools (list)."
                    ),
                },
            },
            "required": ["action"],
        },
    },
}, safety_tier="control_plane", returns={
    "oneOf": [
        {
            "type": "array",
            "description": "list action — array of bot summaries",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "model": {"type": "string"},
                },
                "required": ["id"],
            },
        },
        {
            "type": "object",
            "description": "get action — full bot config",
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
                "model": {"type": "string"},
                "system_prompt": {"type": "string"},
                "local_tools": {"type": "array", "items": {"type": "string"}},
                "skills": {"type": "array"},
                "workspace_enabled": {"type": "boolean"},
                "memory_scheme": {"type": ["string", "null"]},
                "tool_retrieval": {"type": "boolean"},
                "context_compaction": {"type": "boolean"},
                "delegate_bots": {"type": "array"},
                "error": {"type": "string"},
            },
        },
        {
            "type": "object",
            "description": "create/update/delete action",
            "properties": {
                "ok": {"type": "boolean"},
                "bot_id": {"type": "string"},
                "message": {"type": "string"},
                "error": {"type": "string"},
            },
        },
    ],
}, tool_metadata={
    "domains": ["system_admin"],
    "intent_tags": ["bot configuration", "admin settings", "agent setup"],
    "exposure": "explicit",
})
async def manage_bot(
    action: str,
    bot_id: str | None = None,
    config: dict | None = None,
) -> str:
    from app.agent.bots import load_bots, list_bots, get_bot, _yaml_data_to_row_dict

    if action == "list":
        bots = list_bots()
        return json.dumps([
            {"id": b.id, "name": b.name, "model": b.model}
            for b in bots
        ], ensure_ascii=False)

    if action == "get":
        if not bot_id:
            return json.dumps({"error": "bot_id is required for get"}, ensure_ascii=False)
        try:
            bot = get_bot(bot_id)
        except Exception:
            return json.dumps({"error": f"Bot '{bot_id}' not found"}, ensure_ascii=False)
        return json.dumps({
            "id": bot.id,
            "name": bot.name,
            "model": bot.model,
            "system_prompt": bot.system_prompt[:200] + "..." if len(bot.system_prompt) > 200 else bot.system_prompt,
            "local_tools": bot.local_tools,
            "skills": [{"id": s.id, "mode": s.mode} for s in bot.skills],
            "workspace_enabled": bot.workspace.enabled,
            "memory_scheme": bot.memory_scheme,
            "tool_retrieval": bot.tool_retrieval,
            "context_compaction": bot.context_compaction,
            "delegate_bots": bot.delegate_bots,
        }, ensure_ascii=False)

    if action == "create":
        if not bot_id:
            return json.dumps({"error": "bot_id is required for create"}, ensure_ascii=False)
        if not config:
            return json.dumps({"error": "config is required for create"}, ensure_ascii=False)

        # Check if bot already exists
        try:
            get_bot(bot_id)
            return json.dumps({"error": f"Bot '{bot_id}' already exists"}, ensure_ascii=False)
        except Exception:
            pass

        # Build row dict from config
        data = {"id": bot_id, **config}
        if "model" not in data:
            return json.dumps({"error": "config.model is required for create"}, ensure_ascii=False)
        row_dict = _yaml_data_to_row_dict(data)

        async with async_session() as db:
            stmt = pg_insert(BotRow).values(**row_dict)
            await db.execute(stmt)
            await db.commit()

        await load_bots()
        return json.dumps({"ok": True, "bot_id": bot_id, "message": f"Bot '{bot_id}' created"}, ensure_ascii=False)

    if action == "update":
        if not bot_id:
            return json.dumps({"error": "bot_id is required for update"}, ensure_ascii=False)
        if not config:
            return json.dumps({"error": "config is required for update"}, ensure_ascii=False)

        async with async_session() as db:
            row = await db.get(BotRow, bot_id)
            if not row:
                return json.dumps({"error": f"Bot '{bot_id}' not found"}, ensure_ascii=False)

            # Apply updates
            simple_fields = [
                "name", "model", "system_prompt", "local_tools", "mcp_servers",
                "client_tools", "pinned_tools", "tool_retrieval",
                "tool_similarity_threshold", "persona", "context_compaction",
                "compaction_interval", "compaction_keep_turns", "compaction_model",
                "audio_input", "memory_scheme", "history_mode",
            ]
            for field in simple_fields:
                if field in config:
                    setattr(row, field, config[field])

            if "skills" in config:
                from app.agent.bots import _normalize_skill_entry
                row.skills = [_normalize_skill_entry(e) for e in config["skills"]]

            if "workspace" in config:
                row.workspace = {**(row.workspace or {}), **config["workspace"]}

            if config.get("cross_workspace_access"):
                return json.dumps({
                    "error": (
                        "cross_workspace_access is deprecated. Add the bot as a channel "
                        "member to grant channel WorkSurface access."
                    )
                }, ensure_ascii=False)

            if "delegate_bots" in config or "cross_workspace_access" in config:
                dc = dict(row.delegation_config or {})
                if "delegate_bots" in config:
                    dc["delegate_bots"] = config["delegate_bots"]
                if "cross_workspace_access" in config:
                    dc.pop("cross_workspace_access", None)
                row.delegation_config = dc

            if "fallback_models" in config:
                row.fallback_models = config["fallback_models"]

            row.updated_at = datetime.now(timezone.utc)
            await db.commit()

        await load_bots()
        return json.dumps({"ok": True, "bot_id": bot_id, "message": f"Bot '{bot_id}' updated"}, ensure_ascii=False)

    if action == "delete":
        if not bot_id:
            return json.dumps({"error": "bot_id is required for delete"}, ensure_ascii=False)

        async with async_session() as db:
            row = await db.get(BotRow, bot_id)
            if not row:
                return json.dumps({"error": f"Bot '{bot_id}' not found"}, ensure_ascii=False)

            if getattr(row, "source_type", "manual") == "system":
                return json.dumps({"error": "Cannot delete system bot"}, ensure_ascii=False)

            # Check for active channels
            from app.db.models import Channel
            from sqlalchemy import func
            channel_count = (await db.execute(
                select(func.count()).select_from(Channel).where(Channel.bot_id == bot_id)
            )).scalar() or 0

            if channel_count > 0:
                return json.dumps({
                    "error": f"Bot '{bot_id}' has {channel_count} active channel(s). "
                    "Delete or reassign them first, or use the admin API with ?force=true."
                }, ensure_ascii=False)

            # Delete associated data
            from app.db.models import (
                BotPersona, FilesystemChunk, SandboxBotAccess,
                SharedWorkspaceBot, Task, ToolPolicyRule,
            )
            await db.execute(Task.__table__.delete().where(Task.bot_id == bot_id))
            await db.execute(BotPersona.__table__.delete().where(BotPersona.bot_id == bot_id))
            await db.execute(ToolPolicyRule.__table__.delete().where(ToolPolicyRule.bot_id == bot_id))
            await db.execute(SandboxBotAccess.__table__.delete().where(SandboxBotAccess.bot_id == bot_id))
            await db.execute(SharedWorkspaceBot.__table__.delete().where(SharedWorkspaceBot.bot_id == bot_id))
            await db.execute(FilesystemChunk.__table__.delete().where(FilesystemChunk.bot_id == bot_id))

            await db.delete(row)
            await db.commit()

        await load_bots()
        return json.dumps({"ok": True, "bot_id": bot_id, "message": f"Bot '{bot_id}' deleted"}, ensure_ascii=False)

    return json.dumps({"error": f"Unknown action: {action}"}, ensure_ascii=False)
