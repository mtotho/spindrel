"""Admin tool: system status overview for the orchestrator bot."""
import json
import logging

from sqlalchemy import func, select

from app.db.engine import async_session
from app.db.models import Bot as BotRow, Channel
from app.tools.registry import register

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "get_system_status",
        "description": (
            "Get an overview of the system: bots, channels, integrations, "
            "providers, and whether this is a fresh install. Use this on your "
            "first message to decide whether to run the setup flow or offer "
            "ongoing management."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}, safety_tier="control_plane")
async def get_system_status() -> str:
    from app.agent.bots import list_bots
    from app.services.providers import list_providers

    # Bots (exclude system bots from user-facing list)
    _SYSTEM_BOT_IDS = {"orchestrator", "default"}
    bots = [
        {"id": b.id, "name": b.name, "model": b.model}
        for b in list_bots()
        if b.id not in _SYSTEM_BOT_IDS
    ]

    # Channels (exclude orchestrator landing)
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
        if ch.client_id != "orchestrator:home"
    ]

    # Integrations
    try:
        from integrations import discover_setup_status
        integrations_raw = discover_setup_status()
        integrations = [
            {
                "id": i["id"],
                "status": i.get("status", "unknown"),
                "has_process": i.get("has_process", False),
                "process_running": (
                    i.get("process_status", {}).get("status") == "running"
                    if i.get("process_status") else False
                ),
            }
            for i in integrations_raw
        ]
    except Exception:
        integrations = []

    # Providers
    providers = [
        {"id": str(p.id), "name": p.display_name}
        for p in list_providers()
    ]

    # Config
    from app.config import settings
    config = {
        "workspace_base_dir": settings.WORKSPACE_BASE_DIR or None,
        "timezone": settings.TIMEZONE,
        "embedding_model": settings.EMBEDDING_MODEL,
    }

    # Fresh install = no non-orchestrator bots AND no non-landing channels
    is_fresh_install = len(bots) == 0 and len(channels) == 0

    return json.dumps({
        "bots": bots,
        "channels": channels,
        "integrations": integrations,
        "providers": providers,
        "config": config,
        "is_fresh_install": is_fresh_install,
    }, ensure_ascii=False)
