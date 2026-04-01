"""Jellyseerr tools — media requests, search, approve/decline/request."""

import json
import logging

import httpx

from integrations.arr.config import settings
from integrations._register import register

from integrations.arr.tools._helpers import error, sanitize, validate_url

logger = logging.getLogger(__name__)


def _base_url() -> str:
    return settings.JELLYSEERR_URL.rstrip("/")


def _headers() -> dict[str, str]:
    return {"X-Api-Key": settings.JELLYSEERR_API_KEY}


async def _get(path: str, params: dict | None = None, timeout: float = 15.0):
    url_err = validate_url(settings.JELLYSEERR_URL, "Jellyseerr")
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
            f"Jellyseerr request timed out after {timeout}s: {path}"
        )


async def _post(path: str, payload: dict | None = None, timeout: float = 15.0):
    url_err = validate_url(settings.JELLYSEERR_URL, "Jellyseerr")
    if url_err:
        raise ValueError(url_err)
    url = f"{_base_url()}{path}"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=_headers(), json=payload or {}, timeout=timeout)
            resp.raise_for_status()
            if resp.content:
                return resp.json()
            return {}
    except httpx.TimeoutException:
        raise httpx.TimeoutException(
            f"Jellyseerr request timed out after {timeout}s: {path}"
        )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@register({
    "type": "function",
    "function": {
        "name": "jellyseerr_requests",
        "description": (
            "List media requests in Jellyseerr. "
            "Filters: all, pending, approved, processing, available, unavailable, failed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "enum": ["all", "pending", "approved", "processing", "available", "unavailable", "failed"],
                    "description": "Filter by request status (default 'all').",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 20).",
                },
            },
        },
    },
})
async def jellyseerr_requests(filter: str = "all", limit: int = 20) -> str:
    if not settings.JELLYSEERR_URL:
        return error("JELLYSEERR_URL is not configured")
    try:
        params: dict = {"take": limit}
        if filter != "all":
            params["filter"] = filter
        data = await _get("/api/v1/request", params=params)
        results_data = data.get("results", [])
        requests_list = []
        for req in results_data:
            media = req.get("media", {})
            entry: dict = {
                "id": req.get("id"),
                "media_type": req.get("type") or media.get("mediaType", "unknown"),
                "status": _request_status(req.get("status", 0)),
                "requested_by": req.get("requestedBy", {}).get("displayName", "Unknown"),
                "created_at": req.get("createdAt", ""),
            }
            # Pull title from media info
            media_info = req.get("media", {})
            if media_info.get("externalServiceSlug"):
                entry["title"] = sanitize(media_info["externalServiceSlug"])
            # Try to get TMDB/TVDB IDs
            if media_info.get("tmdbId"):
                entry["tmdb_id"] = media_info["tmdbId"]
            if media_info.get("tvdbId"):
                entry["tvdb_id"] = media_info["tvdbId"]

            requests_list.append(entry)

        return json.dumps({
            "total": data.get("pageInfo", {}).get("results", len(requests_list)),
            "requests": requests_list,
        })
    except httpx.HTTPStatusError as e:
        body = e.response.text[:200] if e.response.text else ""
        return error(f"Jellyseerr API error: HTTP {e.response.status_code}: {body}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Jellyseerr at {_base_url()}")
    except Exception as e:
        logger.exception("jellyseerr_requests failed")
        return error(str(e))


def _request_status(code: int) -> str:
    return {1: "pending", 2: "approved", 3: "declined"}.get(code, f"unknown({code})")


@register({
    "type": "function",
    "function": {
        "name": "jellyseerr_search",
        "description": (
            "Search TMDB via Jellyseerr for movies and TV shows. "
            "Returns results with TMDB IDs that can be used to create requests."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search term.",
                },
            },
            "required": ["query"],
        },
    },
})
async def jellyseerr_search(query: str) -> str:
    if not settings.JELLYSEERR_URL:
        return error("JELLYSEERR_URL is not configured")
    try:
        data = await _get("/api/v1/search", params={"query": query, "page": 1})
        results = []
        for item in data.get("results", [])[:20]:
            media_type = item.get("mediaType", "unknown")
            entry: dict = {
                "media_type": media_type,
                "id": item.get("id"),
            }
            if media_type == "movie":
                entry["title"] = sanitize(item.get("title", ""))
                entry["year"] = (item.get("releaseDate") or "")[:4]
                entry["overview"] = sanitize(item.get("overview", ""), max_len=200)
            else:
                entry["title"] = sanitize(item.get("name", ""))
                entry["year"] = (item.get("firstAirDate") or "")[:4]
                entry["overview"] = sanitize(item.get("overview", ""), max_len=200)

            # Include media status if already requested/available
            media_info = item.get("mediaInfo")
            if media_info:
                entry["status"] = _media_status(media_info.get("status", 0))

            results.append(entry)

        return json.dumps({"count": len(results), "results": results})
    except httpx.HTTPStatusError as e:
        body = e.response.text[:200] if e.response.text else ""
        return error(f"Jellyseerr API error: HTTP {e.response.status_code}: {body}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Jellyseerr at {_base_url()}")
    except Exception as e:
        logger.exception("jellyseerr_search failed")
        return error(str(e))


def _media_status(code: int) -> str:
    return {
        1: "unknown", 2: "pending", 3: "processing",
        4: "partially_available", 5: "available",
    }.get(code, f"unknown({code})")


@register({
    "type": "function",
    "function": {
        "name": "jellyseerr_manage",
        "description": (
            "Manage Jellyseerr requests: approve, decline, or create a new request. "
            "For approve/decline: requires request_id. "
            "For request: requires media_id (TMDB ID) and media_type. "
            "For TV requests, optionally specify seasons."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["approve", "decline", "request"],
                    "description": "Action to perform.",
                },
                "request_id": {
                    "type": "integer",
                    "description": "Request ID (for approve/decline).",
                },
                "media_id": {
                    "type": "integer",
                    "description": "TMDB ID (for creating a new request).",
                },
                "media_type": {
                    "type": "string",
                    "enum": ["movie", "tv"],
                    "description": "Media type (for creating a new request).",
                },
                "seasons": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Season numbers to request (TV only; omit for all).",
                },
            },
            "required": ["action"],
        },
    },
})
async def jellyseerr_manage(
    action: str,
    request_id: int | None = None,
    media_id: int | None = None,
    media_type: str | None = None,
    seasons: list[int] | None = None,
) -> str:
    if not settings.JELLYSEERR_URL:
        return error("JELLYSEERR_URL is not configured")
    try:
        if action == "approve":
            if request_id is None:
                return error("request_id required for approve")
            result = await _post(f"/api/v1/request/{request_id}/approve")
            return json.dumps({"status": "ok", "message": f"Request {request_id} approved"})

        if action == "decline":
            if request_id is None:
                return error("request_id required for decline")
            result = await _post(f"/api/v1/request/{request_id}/decline")
            return json.dumps({"status": "ok", "message": f"Request {request_id} declined"})

        if action == "request":
            if media_id is None or media_type is None:
                return error("media_id and media_type required for request")
            payload: dict = {"mediaId": media_id, "mediaType": media_type}
            if media_type == "tv" and seasons:
                payload["seasons"] = seasons
            result = await _post("/api/v1/request", payload)
            return json.dumps({
                "status": "ok",
                "request_id": result.get("id"),
                "message": f"Request created for {media_type} (TMDB ID {media_id})",
            })

        return error(f"Unknown action: {action}")
    except httpx.HTTPStatusError as e:
        body = e.response.text[:200] if e.response.text else ""
        return error(f"Jellyseerr API error: HTTP {e.response.status_code}: {body}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Jellyseerr at {_base_url()}")
    except Exception as e:
        logger.exception("jellyseerr_manage failed")
        return error(str(e))
