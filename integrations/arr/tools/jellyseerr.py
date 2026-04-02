"""Jellyseerr tools — media requests, search, approve/decline/request."""

import asyncio
import json
import logging
from urllib.parse import quote, urlencode

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
            "List media requests in Jellyseerr (newest first) with titles and availability. "
            "Each result includes media_status (available/processing/pending/etc) showing "
            "whether the content is already in Jellyfin — no need to check Jellyfin separately. "
            "Supports paging via skip/limit. "
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
                    "description": "Max results per page (default 20).",
                },
                "skip": {
                    "type": "integer",
                    "description": "Number of results to skip for paging (default 0).",
                },
                "sort": {
                    "type": "string",
                    "enum": ["added", "modified"],
                    "description": "Sort order: 'added' (newest first, default) or 'modified' (recently updated first).",
                },
            },
        },
    },
})
async def jellyseerr_requests(filter: str = "all", limit: int = 20, skip: int = 0, sort: str = "added") -> str:
    if not settings.JELLYSEERR_URL:
        return error("JELLYSEERR_URL is not configured")
    try:
        params: dict = {"take": limit, "skip": skip}
        if sort == "modified":
            params["sort"] = "modified"
        if filter != "all":
            params["filter"] = filter
        data = await _get("/api/v1/request", params=params)
        results_data = data.get("results", [])
        page_info = data.get("pageInfo", {})
        total = page_info.get("results", len(results_data))

        # Build entries with media availability (from Jellyseerr, no Jellyfin call needed)
        requests_list = []
        title_lookups: list[tuple[int, str, int]] = []  # (index, media_type, tmdb_id)
        for req in results_data:
            media = req.get("media", {})
            media_type = req.get("type") or media.get("mediaType", "unknown")
            entry: dict = {
                "id": req.get("id"),
                "media_type": media_type,
                "status": _request_status(req.get("status", 0)),
                "media_status": _media_status(media.get("status", 0)),
                "requested_by": req.get("requestedBy", {}).get("displayName", "Unknown"),
                "created_at": req.get("createdAt", ""),
            }
            if media.get("tmdbId"):
                entry["tmdb_id"] = media["tmdbId"]
                title_lookups.append((len(requests_list), media_type, media["tmdbId"]))
            if media.get("tvdbId"):
                entry["tvdb_id"] = media["tvdbId"]
            requests_list.append(entry)

        # Batch-resolve titles from Jellyseerr's TMDB cache (parallel)
        if title_lookups:
            async def _fetch_title(mtype: str, tmdb_id: int) -> str | None:
                ep = "movie" if mtype == "movie" else "tv"
                try:
                    detail = await _get(f"/api/v1/{ep}/{tmdb_id}", timeout=8.0)
                    if ep == "movie":
                        return sanitize(detail.get("title", ""))
                    return sanitize(detail.get("name", ""))
                except Exception:
                    return None

            titles = await asyncio.gather(
                *[_fetch_title(mt, tid) for _, mt, tid in title_lookups]
            )
            for (idx, _, _), title in zip(title_lookups, titles):
                if title:
                    requests_list[idx]["title"] = title

        return json.dumps({
            "total": total,
            "page": {"skip": skip, "limit": limit, "returned": len(requests_list), "has_more": skip + len(requests_list) < total},
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
            "Returns results with TMDB IDs that can be used to create requests. "
            "Supports paging via page parameter (20 results per page)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search term.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (default 1, 20 results per page).",
                },
            },
            "required": ["query"],
        },
    },
})
async def jellyseerr_search(query: str, page: int = 1) -> str:
    if not settings.JELLYSEERR_URL:
        return error("JELLYSEERR_URL is not configured")
    try:
        # Manually encode query string — some Seerr versions reject unencoded
        # reserved characters even though httpx encodes params correctly.
        qs = urlencode({"query": query, "page": page}, quote_via=quote)
        data = await _get(f"/api/v1/search?{qs}")
        page_info = data.get("pageInfo", {})
        total_results = page_info.get("results", 0)
        total_pages = page_info.get("pages", 1)
        results = []
        for item in data.get("results", []):
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

        return json.dumps({
            "count": len(results),
            "page": {"current": page, "total_pages": total_pages, "total_results": total_results},
            "results": results,
        })
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
