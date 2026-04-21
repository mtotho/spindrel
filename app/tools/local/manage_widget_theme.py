"""Control-plane widget theme library management for bots."""
import json
import logging

from app.db.engine import async_session
from app.services import server_settings
from app.services.widget_themes import (
    create_widget_theme,
    delete_widget_theme,
    fork_widget_theme,
    list_widget_themes,
    normalize_widget_theme_ref,
    resolve_widget_theme,
    update_widget_theme,
)
from app.tools.registry import register

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "manage_widget_theme",
        "description": (
            "Manage the shared HTML widget SDK theme library. "
            "Actions: list, get, create, fork, update, delete, apply_channel."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "create", "fork", "update", "delete", "apply_channel"],
                },
                "ref": {"type": "string", "description": "Theme ref, e.g. builtin/default or custom/my-theme."},
                "name": {"type": "string", "description": "Theme name for create/fork/update."},
                "slug": {"type": "string", "description": "Optional theme slug for create/fork."},
                "light_tokens": {"type": "object"},
                "dark_tokens": {"type": "object"},
                "custom_css": {"type": "string"},
                "channel_id": {"type": "string", "description": "Channel UUID for apply_channel."},
            },
            "required": ["action"],
        },
    },
}, safety_tier="control_plane")
async def manage_widget_theme(
    action: str,
    ref: str | None = None,
    name: str | None = None,
    slug: str | None = None,
    light_tokens: dict | None = None,
    dark_tokens: dict | None = None,
    custom_css: str | None = None,
    channel_id: str | None = None,
) -> str:
    from app.db.models import Channel
    from sqlalchemy.orm.attributes import flag_modified

    async with async_session() as db:
        try:
            if action == "list":
                return json.dumps(await list_widget_themes(db), ensure_ascii=False, default=str)

            if action == "get":
                if not ref:
                    return json.dumps({"error": "ref is required for get"}, ensure_ascii=False)
                return json.dumps(await resolve_widget_theme(db, ref), ensure_ascii=False, default=str)

            if action == "create":
                if not name:
                    return json.dumps({"error": "name is required for create"}, ensure_ascii=False)
                theme = await create_widget_theme(
                    db,
                    name=name,
                    slug=slug,
                    light_tokens=light_tokens,
                    dark_tokens=dark_tokens,
                    custom_css=custom_css,
                )
                return json.dumps(theme, ensure_ascii=False, default=str)

            if action == "fork":
                if not ref or not name:
                    return json.dumps({"error": "ref and name are required for fork"}, ensure_ascii=False)
                theme = await fork_widget_theme(db, source_ref=ref, name=name, slug=slug)
                return json.dumps(theme, ensure_ascii=False, default=str)

            if action == "update":
                if not ref:
                    return json.dumps({"error": "ref is required for update"}, ensure_ascii=False)
                theme = await update_widget_theme(
                    db,
                    ref,
                    name=name,
                    light_tokens=light_tokens,
                    dark_tokens=dark_tokens,
                    custom_css=custom_css,
                )
                return json.dumps(theme, ensure_ascii=False, default=str)

            if action == "delete":
                if not ref:
                    return json.dumps({"error": "ref is required for delete"}, ensure_ascii=False)
                await delete_widget_theme(db, ref)
                return json.dumps({"ok": True, "deleted": normalize_widget_theme_ref(ref)}, ensure_ascii=False)

            if action == "apply_channel":
                if not channel_id or not ref:
                    return json.dumps({"error": "channel_id and ref are required for apply_channel"}, ensure_ascii=False)
                theme = await resolve_widget_theme(db, ref)
                channel = await db.get(Channel, channel_id)
                if channel is None:
                    return json.dumps({"error": f"Channel '{channel_id}' not found"}, ensure_ascii=False)
                cfg = dict(channel.config or {})
                if theme["ref"] == "builtin/default":
                    cfg.pop("widget_theme_ref", None)
                else:
                    cfg["widget_theme_ref"] = theme["ref"]
                channel.config = cfg
                flag_modified(channel, "config")
                await db.commit()
                return json.dumps({
                    "ok": True,
                    "channel_id": channel_id,
                    "widget_theme_ref": cfg.get("widget_theme_ref"),
                    "global_default_ref": server_settings.settings.WIDGET_THEME_DEFAULT_REF,
                }, ensure_ascii=False)
        except Exception as exc:
            logger.exception("manage_widget_theme failed")
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    return json.dumps({"error": f"Unknown action: {action}"}, ensure_ascii=False)
