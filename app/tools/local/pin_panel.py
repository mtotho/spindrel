"""Bot tools for pinning/unpinning workspace files to a channel's pinned-files widget."""
import json

from sqlalchemy import select

from app.agent.context import current_bot_id, current_channel_id
from app.db.engine import async_session
from app.db.models import Channel
from app.domain.errors import DomainError
from app.tools.registry import register

_PIN_PANEL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "pin_panel",
        "description": (
            "Pin a workspace file into the channel's pinned-files widget so "
            "the user can preview it live alongside the conversation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path of the workspace file to pin (relative to workspace root).",
                },
                "position": {
                    "type": "string",
                    "enum": ["right", "bottom"],
                    "description": "Where to display the panel. Default: right.",
                },
            },
            "required": ["path"],
        },
    },
}


@register(
    _PIN_PANEL_SCHEMA,
    safety_tier="mutating",
    requires_bot_context=True,
    requires_channel_context=True,
    returns={
        "type": "object",
        "properties": {
            "llm": {"type": "string"},
            "_envelope": {"type": "object"},
            "error": {"type": "string"},
        },
    },
)
async def pin_panel(path: str, position: str = "right") -> str:
    channel_id = current_channel_id.get()
    bot_id = current_bot_id.get() or "unknown"
    if not channel_id:
        return json.dumps({"error": "No channel context — cannot pin panel."}, ensure_ascii=False)

    if position not in ("right", "bottom"):
        return json.dumps({"error": "position must be 'right' or 'bottom'"}, ensure_ascii=False)

    async with async_session() as db:
        ch = (await db.execute(
            select(Channel).where(Channel.id == channel_id)
        )).scalar_one_or_none()
        if not ch:
            return json.dumps({"error": "Channel not found"}, ensure_ascii=False)

        from app.services.pinned_panels import pin_file_for_channel

        await pin_file_for_channel(db, channel_id, path, actor=bot_id)

    return json.dumps({
        "_envelope": {
            "content_type": "text/markdown",
            "body": f"**Pinned** `{path}` to the channel pinned-files widget",
            "plain_body": f"Pinned {path} to the channel pinned-files widget",
            "display": "panel",
        },
        "llm": f"Pinned {path} to the channel's pinned-files widget.",
    }, ensure_ascii=False)


_UNPIN_PANEL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "unpin_panel",
        "description": "Remove a pinned file from the channel's pinned-files widget.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path of the workspace file to unpin.",
                },
            },
            "required": ["path"],
        },
    },
}


@register(
    _UNPIN_PANEL_SCHEMA,
    safety_tier="mutating",
    requires_channel_context=True,
    returns={
        "type": "object",
        "properties": {
            "llm": {"type": "string"},
            "_envelope": {"type": "object"},
            "error": {"type": "string"},
        },
    },
)
async def unpin_panel(path: str) -> str:
    channel_id = current_channel_id.get()
    if not channel_id:
        return json.dumps({"error": "No channel context — cannot unpin panel."}, ensure_ascii=False)

    async with async_session() as db:
        ch = (await db.execute(
            select(Channel).where(Channel.id == channel_id)
        )).scalar_one_or_none()
        if not ch:
            return json.dumps({"error": "Channel not found"}, ensure_ascii=False)

        from app.services.pinned_panels import unpin_file_for_channel

        try:
            await unpin_file_for_channel(db, channel_id, path)
        except DomainError:
            return json.dumps({"error": f"{path} is not pinned in this channel."}, ensure_ascii=False)

    return json.dumps({
        "_envelope": {
            "content_type": "text/markdown",
            "body": f"**Unpinned** `{path}`",
            "plain_body": f"Unpinned {path}",
            "display": "panel",
        },
        "llm": f"Unpinned {path} from the channel.",
    }, ensure_ascii=False)
