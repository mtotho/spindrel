"""qBittorrent tools — torrent listing and management."""

import json
import logging
from contextlib import asynccontextmanager

import httpx

from integrations.arr.config import settings
from integrations._register import register

from integrations.arr.tools._helpers import error, sanitize

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _qbit_client():
    """Authenticated qBittorrent client (cookie-based login)."""
    async with httpx.AsyncClient(base_url=settings.QBIT_URL.rstrip("/")) as client:
        resp = await client.post(
            "/api/v2/auth/login",
            data={"username": settings.QBIT_USERNAME, "password": settings.QBIT_PASSWORD},
        )
        if resp.text.strip() != "Ok.":
            raise RuntimeError(f"qBittorrent login failed: {resp.text.strip()}")
        yield client


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@register({
    "type": "function",
    "function": {
        "name": "qbit_torrents",
        "description": (
            "List torrents in qBittorrent with global transfer speeds. "
            "Filters: all, downloading, seeding, completed, paused, active, stalled."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "enum": ["all", "downloading", "seeding", "completed", "paused", "active", "stalled"],
                    "description": "Filter torrents by state (default 'all').",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max torrents to return (default 50).",
                },
            },
        },
    },
})
async def qbit_torrents(filter: str = "all", limit: int = 50) -> str:
    if not settings.QBIT_URL:
        return error("QBIT_URL is not configured")
    try:
        async with _qbit_client() as client:
            params: dict = {"filter": filter, "limit": limit, "sort": "added_on", "reverse": "true"}
            resp = await client.get("/api/v2/torrents/info", params=params, timeout=15.0)
            resp.raise_for_status()
            torrents_data = resp.json()

            transfer_resp = await client.get("/api/v2/transfer/info", timeout=10.0)
            transfer_resp.raise_for_status()
            transfer = transfer_resp.json()

            torrents = []
            for t in torrents_data:
                size_mb = round((t.get("size", 0) or 0) / 1_048_576, 1)
                dl_speed = t.get("dlspeed", 0) or 0
                up_speed = t.get("upspeed", 0) or 0
                progress = round((t.get("progress", 0) or 0) * 100, 1)
                torrents.append({
                    "name": sanitize(t.get("name", "Unknown")),
                    "hash": t.get("hash", ""),
                    "state": t.get("state", ""),
                    "size_mb": size_mb,
                    "progress_pct": progress,
                    "dl_speed_kb": round(dl_speed / 1024, 1),
                    "up_speed_kb": round(up_speed / 1024, 1),
                    "eta_seconds": t.get("eta", 0),
                    "category": t.get("category", ""),
                })

            return json.dumps({
                "count": len(torrents),
                "global_dl_speed_kb": round((transfer.get("dl_info_speed", 0) or 0) / 1024, 1),
                "global_up_speed_kb": round((transfer.get("up_info_speed", 0) or 0) / 1024, 1),
                "torrents": torrents,
            })
    except httpx.HTTPStatusError as e:
        return error(f"qBittorrent API error: HTTP {e.response.status_code}")
    except httpx.ConnectError:
        return error(f"Cannot connect to qBittorrent at {settings.QBIT_URL}")
    except RuntimeError as e:
        return error(str(e))
    except Exception as e:
        logger.exception("qbit_torrents failed")
        return error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "qbit_manage",
        "description": (
            "Manage qBittorrent torrents: pause, resume, delete, or delete with files. "
            "Pass torrent hashes (from qbit_torrents results)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "hashes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Torrent hashes to act on.",
                },
                "action": {
                    "type": "string",
                    "enum": ["pause", "resume", "delete", "delete_with_files"],
                    "description": "Action to perform.",
                },
            },
            "required": ["hashes", "action"],
        },
    },
})
async def qbit_manage(hashes: list[str], action: str) -> str:
    if not settings.QBIT_URL:
        return error("QBIT_URL is not configured")
    if not hashes:
        return error("hashes list is empty")
    try:
        async with _qbit_client() as client:
            hash_str = "|".join(hashes)

            if action == "pause":
                endpoint = "/api/v2/torrents/pause"
            elif action == "resume":
                endpoint = "/api/v2/torrents/resume"
            elif action == "delete":
                endpoint = "/api/v2/torrents/delete"
            elif action == "delete_with_files":
                endpoint = "/api/v2/torrents/delete"
            else:
                return error(f"Unknown action: {action}")

            data: dict = {"hashes": hash_str}
            if action == "delete_with_files":
                data["deleteFiles"] = "true"
            elif action == "delete":
                data["deleteFiles"] = "false"

            resp = await client.post(endpoint, data=data, timeout=15.0)
            resp.raise_for_status()

            return json.dumps({
                "status": "ok",
                "action": action,
                "hashes": hashes,
                "message": f"{action} applied to {len(hashes)} torrent(s)",
            })
    except httpx.HTTPStatusError as e:
        return error(f"qBittorrent API error: HTTP {e.response.status_code}")
    except httpx.ConnectError:
        return error(f"Cannot connect to qBittorrent at {settings.QBIT_URL}")
    except RuntimeError as e:
        return error(str(e))
    except Exception as e:
        logger.exception("qbit_manage failed")
        return error(str(e))
