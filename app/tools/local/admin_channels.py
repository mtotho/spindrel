"""Admin tool: channel management for the orchestrator bot."""
import json
import logging

from sqlalchemy import select

from app.db.engine import async_session
from app.db.models import Channel
from app.tools.registry import register

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "manage_channel",
        "description": (
            "Create, list, or configure channels. "
            "Actions: list, create, configure. "
            "For create, provide name and bot_id. "
            "For configure, provide channel_id and config."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "create", "configure"],
                    "description": "The action to perform.",
                },
                "name": {
                    "type": "string",
                    "description": "Channel display name (for create).",
                },
                "bot_id": {
                    "type": "string",
                    "description": "Bot ID to assign to the channel (for create).",
                },
                "channel_id": {
                    "type": "string",
                    "description": "Channel UUID (for configure).",
                },
                "config": {
                    "type": "object",
                    "description": (
                        "Channel configuration for configure. Keys: "
                        "workspace_schema_template_id, heartbeat_enabled, "
                        "context_compaction, "
                        "model_override, display_name, channel_prompt, "
                        "workspace_id (UUID string or null to assign/clear workspace), "
                        "carapaces_extra (list of carapace IDs to add), "
                        "carapaces_disabled (list of carapace IDs to suppress)."
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
            "description": "list action — array of channel summaries",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "bot_id": {"type": "string"},
                    "client_id": {"type": "string"},
                },
                "required": ["id"],
            },
        },
        {
            "type": "object",
            "description": "create action",
            "properties": {
                "ok": {"type": "boolean"},
                "channel_id": {"type": "string"},
                "name": {"type": "string"},
                "bot_id": {"type": "string"},
                "client_id": {"type": "string"},
                "message": {"type": "string"},
                "error": {"type": "string"},
            },
        },
        {
            "type": "object",
            "description": "configure action",
            "properties": {
                "ok": {"type": "boolean"},
                "message": {"type": "string"},
                "error": {"type": "string"},
            },
        },
    ],
})
async def manage_channel(
    action: str,
    name: str | None = None,
    bot_id: str | None = None,
    channel_id: str | None = None,
    config: dict | None = None,
) -> str:
    from app.services.channels import get_or_create_channel, ensure_active_session

    if action == "list":
        async with async_session() as db:
            rows = (await db.execute(select(Channel))).scalars().all()
        channels = [
            {
                "id": str(ch.id),
                "name": ch.name or ch.client_id,
                "bot_id": ch.bot_id,
                "client_id": ch.client_id,
            }
            for ch in rows
        ]
        return json.dumps(channels, ensure_ascii=False)

    if action == "create":
        if not bot_id:
            return json.dumps({"error": "bot_id is required for create"}, ensure_ascii=False)

        # Validate bot exists
        from app.agent.bots import get_bot
        try:
            get_bot(bot_id)
        except Exception:
            return json.dumps({"error": f"Bot '{bot_id}' not found"}, ensure_ascii=False)

        # Derive client_id from name
        safe_name = (name or bot_id).lower().replace(" ", "-")
        client_id = f"ui:{safe_name}"

        async with async_session() as db:
            ch = await get_or_create_channel(
                db,
                client_id=client_id,
                bot_id=bot_id,
                name=name or safe_name,
            )
            await ensure_active_session(db, ch)
            await db.commit()

            return json.dumps({
                "ok": True,
                "channel_id": str(ch.id),
                "name": ch.name,
                "bot_id": ch.bot_id,
                "client_id": ch.client_id,
                "message": f"Channel '{ch.name}' created for bot '{bot_id}'",
            }, ensure_ascii=False)

    if action == "configure":
        if not channel_id:
            return json.dumps({"error": "channel_id is required for configure"}, ensure_ascii=False)
        if not config:
            return json.dumps({"error": "config is required for configure"}, ensure_ascii=False)

        import uuid
        from datetime import datetime, timezone

        try:
            ch_uuid = uuid.UUID(channel_id)
        except ValueError:
            return json.dumps({"error": f"Invalid channel_id: {channel_id}"}, ensure_ascii=False)

        async with async_session() as db:
            ch = await db.get(Channel, ch_uuid)
            if not ch:
                return json.dumps({"error": f"Channel '{channel_id}' not found"}, ensure_ascii=False)

            simple_fields = [
                "display_name", "channel_prompt", "model_override",
                "context_compaction", "compaction_interval", "compaction_keep_turns",
                "require_mention",
                "workspace_schema_template_id",
                "carapaces_extra", "carapaces_disabled",
            ]

            # Handle workspace_id separately (needs UUID conversion)
            if "workspace_id" in config:
                import uuid as _uuid
                ws_val = config.pop("workspace_id")
                ch.workspace_id = _uuid.UUID(ws_val) if ws_val else None
            for field in simple_fields:
                if field in config:
                    setattr(ch, field, config[field])

            if "heartbeat_enabled" in config:
                from app.db.models import ChannelHeartbeat
                if config["heartbeat_enabled"]:
                    existing = await db.get(ChannelHeartbeat, ch_uuid)
                    if not existing:
                        db.add(ChannelHeartbeat(channel_id=ch_uuid))
                # Disabling heartbeat: just leave the row, the worker checks enabled flag

            ch.updated_at = datetime.now(timezone.utc)
            await db.commit()

        return json.dumps({"ok": True, "message": f"Channel '{channel_id}' configured"}, ensure_ascii=False)

    return json.dumps({"error": f"Unknown action: {action}"}, ensure_ascii=False)
