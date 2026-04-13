"""Wyoming integration router -- serves config and binding suggestions."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.db.engine import async_session
from app.db.models import Bot as BotRow, Channel, ChannelIntegration

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/config")
async def wyoming_config(request: Request):
    """Returns device->bot mapping for the Wyoming pipeline orchestrator.

    Merges legacy Channel-level bindings and modern ChannelIntegration bindings.
    Each device entry includes satellite_uri so the orchestrator knows where to connect.
    """
    from app.config import settings

    api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        api_key = api_key or auth_header[7:]

    expected = getattr(settings, "API_KEY", None)
    authed = bool(expected and api_key == expected)

    if not authed and api_key and api_key.startswith("ask_"):
        from app.services.api_keys import validate_api_key, has_scope
        async with async_session() as key_db:
            key_row = await validate_api_key(key_db, api_key)
            if key_row and has_scope(key_row.scopes or [], "admin"):
                authed = True

    if not authed:
        raise HTTPException(status_code=401, detail="Unauthorized")

    async with async_session() as db:
        # Legacy channels
        channel_rows = (await db.execute(
            select(Channel).where(Channel.integration == "wyoming")
        )).scalars().all()

        # Modern bindings
        binding_rows = (await db.execute(
            select(Channel, ChannelIntegration)
            .join(ChannelIntegration, ChannelIntegration.channel_id == Channel.id)
            .where(ChannelIntegration.integration_type == "wyoming")
        )).tuples().all()

        bot_rows = (await db.execute(select(BotRow))).scalars().all()

    bots = {str(b.id): b for b in bot_rows}
    devices: dict[str, dict] = {}

    # Legacy
    for row in channel_rows:
        if not row.client_id:
            continue
        device_id = row.client_id.removeprefix("wyoming:")
        bot = bots.get(str(row.bot_id))
        devices[device_id] = {
            "bot_id": str(row.bot_id),
            "bot_name": bot.name if bot else "unknown",
            "channel_id": str(row.id),
            "channel_name": row.name,
        }

    # Modern bindings
    for channel, binding in binding_rows:
        device_id = (binding.client_id or "").removeprefix("wyoming:")
        if not device_id:
            continue
        bot = bots.get(str(channel.bot_id))
        # Config values may be in dispatch_config (binding form) or activation_config
        config = {**(binding.dispatch_config or {}), **(binding.activation_config or {})}
        devices[device_id] = {
            "bot_id": str(channel.bot_id),
            "bot_name": bot.name if bot else "unknown",
            "channel_id": str(channel.id),
            "channel_name": channel.name,
            "satellite_uri": config.get("satellite_uri"),
            "voice": config.get("voice"),
            "wake_words": config.get("wake_words"),
            "protocol": config.get("protocol", "wyoming"),
            "esphome_device_name": config.get("esphome_device_name"),
        }

    return {"devices": devices}


@router.get("/binding-suggestions")
async def binding_suggestions():
    """Discover Wyoming satellites on the network via Zeroconf."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    discovered = await asyncio.get_event_loop().run_in_executor(
        ThreadPoolExecutor(max_workers=1), _scan_for_satellites,
    )

    if discovered:
        return discovered

    # Fallback: no satellites found, return placeholder
    return [
        {
            "client_id": "wyoming:satellite",
            "display_name": "Manual Entry",
            "description": "Enter the satellite URI manually in the config field below",
        },
    ]


def _scan_for_satellites(timeout: float = 3.0) -> list[dict]:
    """Scan for Wyoming satellites via Zeroconf (blocking, run in executor)."""
    results: list[dict] = []
    try:
        from zeroconf import ServiceBrowser, Zeroconf, ServiceStateChange

        zc = Zeroconf()
        found: list[tuple[str, str]] = []

        class Handler:
            def add_service(self, zc_inst, type_, name):
                info = zc_inst.get_service_info(type_, name)
                if info:
                    addresses = info.parsed_addresses()
                    port = info.port
                    sat_name = info.get_name() or name.split(".")[0]
                    if addresses:
                        found.append((sat_name, f"tcp://{addresses[0]}:{port}"))

            def remove_service(self, *args):
                pass

            def update_service(self, *args):
                pass

        handler = Handler()
        # Wyoming satellites advertise as _wyoming._tcp.local.
        browser = ServiceBrowser(zc, "_wyoming._tcp.local.", handler)

        import time
        time.sleep(timeout)

        browser.cancel()
        zc.close()

        for sat_name, uri in found:
            device_id = sat_name.replace(" ", "-").lower()
            results.append({
                "client_id": f"wyoming:{device_id}",
                "display_name": sat_name,
                "description": uri,
                "config_values": {"satellite_uri": uri},
            })
    except ImportError:
        logger.debug("zeroconf not installed, skipping satellite discovery")
    except Exception:
        logger.debug("Zeroconf scan failed", exc_info=True)

    return results
