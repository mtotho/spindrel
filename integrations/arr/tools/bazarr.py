"""Bazarr tools — subtitle management."""

import json
import logging

import httpx

from integrations.arr.config import settings
from integrations.sdk import register_tool as register

from integrations.arr.tools._helpers import error, sanitize, validate_url

logger = logging.getLogger(__name__)


def _base_url() -> str:
    return settings.BAZARR_URL.rstrip("/")


async def _get(path: str, params: dict | None = None, timeout: float = 15.0):
    url_err = validate_url(settings.BAZARR_URL, "Bazarr")
    if url_err:
        raise ValueError(url_err)
    url = f"{_base_url()}{path}"
    p = dict(params or {})
    p["apikey"] = settings.BAZARR_API_KEY
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=p, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
    except httpx.TimeoutException:
        raise httpx.TimeoutException(
            f"Bazarr request timed out after {timeout}s: {path}"
        )


async def _post(path: str, params: dict | None = None, payload: dict | None = None, timeout: float = 15.0):
    url_err = validate_url(settings.BAZARR_URL, "Bazarr")
    if url_err:
        raise ValueError(url_err)
    url = f"{_base_url()}{path}"
    p = dict(params or {})
    p["apikey"] = settings.BAZARR_API_KEY
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, params=p, json=payload or {}, timeout=timeout)
            resp.raise_for_status()
            if resp.content:
                return resp.json()
            return {}
    except httpx.TimeoutException:
        raise httpx.TimeoutException(
            f"Bazarr request timed out after {timeout}s: {path}"
        )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@register({
    "type": "function",
    "function": {
        "name": "bazarr_subtitles",
        "description": (
            "Manage subtitles via Bazarr: view wanted subtitles, trigger searches, or check status. "
            "Actions: 'wanted' (missing subtitles), 'search' (trigger search for missing), "
            "'status' (system health). Media types: 'episodes' or 'movies'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["wanted", "search", "status"],
                    "description": "Action to perform (default 'wanted').",
                },
                "media_type": {
                    "type": "string",
                    "enum": ["episodes", "movies"],
                    "description": "Media type (default 'episodes').",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results for wanted list (default 20).",
                },
            },
        },
    },
})
async def bazarr_subtitles(
    action: str = "wanted",
    media_type: str = "episodes",
    limit: int = 20,
) -> str:
    if not settings.BAZARR_URL:
        return error("BAZARR_URL is not configured")
    try:
        if action == "status":
            data = await _get("/api/system/status")
            return json.dumps({"status": data}, ensure_ascii=False)

        if action == "search":
            data = await _post(f"/api/{media_type}/wanted/search")
            return json.dumps({
                "status": "ok",
                "message": f"Subtitle search triggered for wanted {media_type}",
            }, ensure_ascii=False)

        # Default: wanted
        data = await _get(f"/api/{media_type}/wanted", params={"length": str(limit)})
        items_data = data.get("data", [])
        items = []
        for item in items_data:
            entry: dict = {
                "title": sanitize(item.get("seriesTitle", "") or item.get("title", "")),
                "missing_subtitles": item.get("missing_subtitles", []),
            }
            if item.get("episode"):
                entry["season"] = item.get("season")
                entry["episode"] = item.get("episode")
            if item.get("sceneName"):
                entry["scene_name"] = sanitize(item["sceneName"])
            items.append(entry)

        return json.dumps({
            "total": data.get("total", len(items)),
            "items": items,
        }, ensure_ascii=False)
    except httpx.HTTPStatusError as e:
        return error(f"Bazarr API error: HTTP {e.response.status_code}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Bazarr at {_base_url()}")
    except Exception as e:
        logger.exception("bazarr_subtitles failed")
        return error(str(e))
