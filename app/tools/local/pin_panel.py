"""Bot tools for pinning/unpinning workspace files to a channel's side rail."""
import copy
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.agent.context import current_bot_id, current_channel_id
from app.db.engine import async_session
from app.db.models import Channel
from app.tools.registry import register

_PIN_PANEL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "pin_panel",
        "description": (
            "Pin a workspace file to the channel's side rail so the user "
            "can see its content live. The panel auto-updates when the file "
            "changes. Use this for dashboards, reports, or any file the user "
            "should monitor alongside the conversation."
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

        cfg = copy.deepcopy(ch.config or {})
        panels = cfg.setdefault("pinned_panels", [])
        panels = [p for p in panels if p["path"] != path]
        now_iso = datetime.now(timezone.utc).isoformat()
        panels.append({
            "path": path,
            "position": position,
            "pinned_at": now_iso,
            "pinned_by": bot_id,
        })
        cfg["pinned_panels"] = panels
        ch.config = cfg
        flag_modified(ch, "config")
        await db.commit()

    from app.services.pinned_panels import invalidate_channel
    await invalidate_channel(channel_id)

    return json.dumps({
        "_envelope": {
            "content_type": "text/markdown",
            "body": f"**Pinned** `{path}` to {position} rail",
            "plain_body": f"Pinned {path} to {position} rail",
            "display": "panel",
        },
        "llm": f"Pinned {path} to the channel's {position} panel.",
    }, ensure_ascii=False)


_UNPIN_PANEL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "unpin_panel",
        "description": "Remove a pinned file panel from the channel's side rail.",
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

        cfg = copy.deepcopy(ch.config or {})
        panels = cfg.get("pinned_panels", [])
        new_panels = [p for p in panels if p["path"] != path]
        if len(new_panels) == len(panels):
            return json.dumps({"error": f"{path} is not pinned in this channel."}, ensure_ascii=False)
        cfg["pinned_panels"] = new_panels
        ch.config = cfg
        flag_modified(ch, "config")
        await db.commit()

    from app.services.pinned_panels import invalidate_channel
    await invalidate_channel(channel_id)

    return json.dumps({
        "_envelope": {
            "content_type": "text/markdown",
            "body": f"**Unpinned** `{path}`",
            "plain_body": f"Unpinned {path}",
            "display": "panel",
        },
        "llm": f"Unpinned {path} from the channel.",
    }, ensure_ascii=False)
