"""Jellyfin tools — now playing, library browsing, user management."""

import json
import logging

import httpx

from integrations.arr.config import settings
from integrations.sdk import register_tool as register

from integrations.arr.tools._helpers import error, sanitize, validate_url

logger = logging.getLogger(__name__)

# Cached admin user ID (resolved on first call)
_admin_user_id: str | None = None


def _base_url() -> str:
    return settings.JELLYFIN_URL.rstrip("/")


def _headers() -> dict[str, str]:
    return {"X-Emby-Token": settings.JELLYFIN_API_KEY}


async def _get(path: str, params: dict | None = None, timeout: float = 15.0):
    url_err = validate_url(settings.JELLYFIN_URL, "Jellyfin")
    if url_err:
        raise ValueError(url_err)
    url = f"{_base_url()}{path}"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=_headers(), params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
    except httpx.TimeoutException:
        raise httpx.TimeoutException(
            f"Jellyfin request timed out after {timeout}s: {path}"
        )


async def _post(path: str, payload: dict | None = None, timeout: float = 15.0):
    url_err = validate_url(settings.JELLYFIN_URL, "Jellyfin")
    if url_err:
        raise ValueError(url_err)
    url = f"{_base_url()}{path}"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=_headers(), json=payload or {}, timeout=timeout)
            resp.raise_for_status()
            # Some Jellyfin endpoints return empty body
            if resp.content:
                return resp.json()
            return {}
    except httpx.TimeoutException:
        raise httpx.TimeoutException(
            f"Jellyfin request timed out after {timeout}s: {path}"
        )


async def _delete(path: str, timeout: float = 15.0):
    url_err = validate_url(settings.JELLYFIN_URL, "Jellyfin")
    if url_err:
        raise ValueError(url_err)
    url = f"{_base_url()}{path}"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.delete(url, headers=_headers(), timeout=timeout)
            resp.raise_for_status()
    except httpx.TimeoutException:
        raise httpx.TimeoutException(
            f"Jellyfin request timed out after {timeout}s: {path}"
        )


async def _get_admin_user_id() -> str:
    """Resolve and cache the admin user ID."""
    global _admin_user_id
    if _admin_user_id:
        return _admin_user_id
    users = await _get("/Users")
    for u in users:
        policy = u.get("Policy", {})
        if policy.get("IsAdministrator"):
            _admin_user_id = u["Id"]
            return _admin_user_id
    # Fallback: first user
    if users:
        _admin_user_id = users[0]["Id"]
        return _admin_user_id
    raise RuntimeError("No Jellyfin users found")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@register({
    "type": "function",
    "function": {
        "name": "jellyfin_now_playing",
        "description": (
            "Show what's currently being played/streamed on Jellyfin. "
            "Returns active sessions with user, media, and playback progress."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
})
async def jellyfin_now_playing() -> str:
    if not settings.JELLYFIN_URL:
        return error("JELLYFIN_URL is not configured")
    try:
        sessions = await _get("/Sessions")
        active = []
        for s in sessions:
            now_playing = s.get("NowPlayingItem")
            if not now_playing:
                continue
            play_state = s.get("PlayState", {})
            ticks = play_state.get("PositionTicks", 0)
            total_ticks = now_playing.get("RunTimeTicks", 0)
            progress = round(ticks / total_ticks * 100, 1) if total_ticks > 0 else 0

            entry: dict = {
                "user": s.get("UserName", "Unknown"),
                "client": s.get("Client", ""),
                "device": s.get("DeviceName", ""),
                "media_type": now_playing.get("Type", ""),
                "name": sanitize(now_playing.get("Name", "")),
                "progress_pct": progress,
                "is_paused": play_state.get("IsPaused", False),
            }
            # Add series info for episodes
            if now_playing.get("SeriesName"):
                entry["series"] = sanitize(now_playing["SeriesName"])
                entry["season"] = now_playing.get("ParentIndexNumber")
                entry["episode"] = now_playing.get("IndexNumber")

            active.append(entry)

        return json.dumps({"count": len(active), "sessions": active}, ensure_ascii=False)
    except httpx.HTTPStatusError as e:
        return error(f"Jellyfin API error: HTTP {e.response.status_code}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Jellyfin at {_base_url()}")
    except Exception as e:
        logger.exception("jellyfin_now_playing failed")
        return error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "jellyfin_library",
        "description": (
            "Browse Jellyfin library: recent items, search, or stats. "
            "Actions: 'recent' (latest additions), 'search' (find media), 'stats' (library counts)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["recent", "search", "stats"],
                    "description": "What to retrieve (default 'recent').",
                },
                "search": {
                    "type": "string",
                    "description": "Search term (required for action='search').",
                },
                "media_type": {
                    "type": "string",
                    "enum": ["Movie", "Series", "Episode", "Audio", "MusicAlbum"],
                    "description": "Filter by media type.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 20).",
                },
            },
        },
    },
})
async def jellyfin_library(
    action: str = "recent",
    search: str | None = None,
    media_type: str | None = None,
    limit: int = 20,
) -> str:
    if not settings.JELLYFIN_URL:
        return error("JELLYFIN_URL is not configured")
    try:
        user_id = await _get_admin_user_id()

        if action == "stats":
            data = await _get("/Items/Counts")
            return json.dumps({"stats": data}, ensure_ascii=False)

        if action == "search":
            if not search:
                return error("search term required for action='search'")
            params: dict = {
                "searchTerm": search,
                "Limit": limit,
                "Recursive": "true",
                "Fields": "Overview,MediaSources",
            }
            if media_type:
                params["IncludeItemTypes"] = media_type
            data = await _get(f"/Users/{user_id}/Items", params=params)
            items = []
            for item in data.get("Items", []):
                entry: dict = {
                    "id": item.get("Id"),
                    "name": sanitize(item.get("Name", "")),
                    "type": item.get("Type"),
                    "year": item.get("ProductionYear"),
                }
                if item.get("Overview"):
                    entry["overview"] = sanitize(item["Overview"], max_len=200)
                if item.get("SeriesName"):
                    entry["series"] = sanitize(item["SeriesName"])
                items.append(entry)
            return json.dumps({"count": len(items), "items": items}, ensure_ascii=False)

        # Default: recent
        params = {"Limit": limit}
        if media_type:
            params["IncludeItemTypes"] = media_type
        data = await _get(f"/Users/{user_id}/Items/Latest", params=params)
        items = []
        for item in data:
            entry = {
                "id": item.get("Id"),
                "name": sanitize(item.get("Name", "")),
                "type": item.get("Type"),
                "year": item.get("ProductionYear"),
            }
            if item.get("SeriesName"):
                entry["series"] = sanitize(item["SeriesName"])
            items.append(entry)
        return json.dumps({"count": len(items), "items": items}, ensure_ascii=False)
    except httpx.HTTPStatusError as e:
        return error(f"Jellyfin API error: HTTP {e.response.status_code}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Jellyfin at {_base_url()}")
    except Exception as e:
        logger.exception("jellyfin_library failed")
        return error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "jellyfin_users",
        "description": (
            "Manage Jellyfin users: list, create, or delete. "
            "Actions: 'list' (show all users), 'create' (new user), 'delete' (remove user)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "create", "delete"],
                    "description": "Action to perform (default 'list').",
                },
                "username": {
                    "type": "string",
                    "description": "Username for create action.",
                },
                "password": {
                    "type": "string",
                    "description": "Password for create action.",
                },
                "user_id": {
                    "type": "string",
                    "description": "User ID for delete action.",
                },
            },
        },
    },
})
async def jellyfin_users(
    action: str = "list",
    username: str | None = None,
    password: str | None = None,
    user_id: str | None = None,
) -> str:
    if not settings.JELLYFIN_URL:
        return error("JELLYFIN_URL is not configured")
    try:
        if action == "list":
            users = await _get("/Users")
            result = []
            for u in users:
                policy = u.get("Policy", {})
                result.append({
                    "id": u.get("Id"),
                    "name": u.get("Name"),
                    "is_admin": policy.get("IsAdministrator", False),
                    "is_disabled": policy.get("IsDisabled", False),
                    "last_login": u.get("LastLoginDate"),
                    "last_active": u.get("LastActivityDate"),
                })
            return json.dumps({"count": len(result), "users": result}, ensure_ascii=False)

        if action == "create":
            if not username:
                return error("username required for create")
            new_user = await _post("/Users/New", {"Name": username, "Password": password or ""})
            return json.dumps({
                "status": "ok",
                "user_id": new_user.get("Id"),
                "username": new_user.get("Name"),
                "message": f"User '{username}' created successfully",
            }, ensure_ascii=False)

        if action == "delete":
            if not user_id:
                return error("user_id required for delete")
            await _delete(f"/Users/{user_id}")
            return json.dumps({
                "status": "ok",
                "message": f"User {user_id} deleted successfully",
            }, ensure_ascii=False)

        return error(f"Unknown action: {action}")
    except httpx.HTTPStatusError as e:
        return error(f"Jellyfin API error: HTTP {e.response.status_code}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Jellyfin at {_base_url()}")
    except Exception as e:
        logger.exception("jellyfin_users failed")
        return error(str(e))
