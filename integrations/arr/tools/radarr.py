"""Radarr tools — movies listing, search, commands, quality profiles."""

import json
import logging

import httpx

from integrations.arr.config import settings
from integrations._register import register

from integrations.arr.tools._helpers import coerce_list, error, sanitize, validate_url

logger = logging.getLogger(__name__)


def _base_url() -> str:
    return settings.RADARR_URL.rstrip("/")


def _headers() -> dict[str, str]:
    return {"X-Api-Key": settings.RADARR_API_KEY}


async def _get(path: str, params: dict | None = None, timeout: float = 15.0):
    url_err = validate_url(settings.RADARR_URL, "Radarr")
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
            f"Radarr request timed out after {timeout}s: {path}"
        )


async def _post(path: str, payload: dict, timeout: float = 15.0):
    url_err = validate_url(settings.RADARR_URL, "Radarr")
    if url_err:
        raise ValueError(url_err)
    url = f"{_base_url()}{path}"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=_headers(), json=payload, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
    except httpx.TimeoutException:
        raise httpx.TimeoutException(
            f"Radarr request timed out after {timeout}s: {path}"
        )


async def _delete(path: str, params: dict | None = None, timeout: float = 15.0):
    url_err = validate_url(settings.RADARR_URL, "Radarr")
    if url_err:
        raise ValueError(url_err)
    url = f"{_base_url()}{path}"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.delete(url, headers=_headers(), params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.status_code
    except httpx.TimeoutException:
        raise httpx.TimeoutException(
            f"Radarr request timed out after {timeout}s: {path}"
        )


async def _put(path: str, payload: dict, timeout: float = 15.0):
    url_err = validate_url(settings.RADARR_URL, "Radarr")
    if url_err:
        raise ValueError(url_err)
    url = f"{_base_url()}{path}"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.put(url, headers=_headers(), json=payload, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        body = e.response.text[:500] if e.response else ""
        raise httpx.HTTPStatusError(
            f"Radarr {e.response.status_code} on {path}: {body}",
            request=e.request,
            response=e.response,
        )
    except httpx.TimeoutException:
        raise httpx.TimeoutException(
            f"Radarr request timed out after {timeout}s: {path}"
        )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@register({
    "type": "function",
    "function": {
        "name": "radarr_movies",
        "description": (
            "List movies in Radarr (newest first) or search TMDB for new movies to add. "
            "Without search: returns library movies sorted by recently added. "
            "With search: searches TMDB for matching movies. "
            "Filters: 'missing' (monitored, no file), 'wanted' (missing + monitored)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "search": {
                    "type": "string",
                    "description": "Search term to look up on TMDB. Omit to list library.",
                },
                "filter": {
                    "type": "string",
                    "enum": ["missing", "wanted"],
                    "description": "Filter library results. Omit for all movies.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results for library listing (default 50). Use 0 for all.",
                },
            },
        },
    },
})
async def radarr_movies(search: str | None = None, filter: str | None = None, limit: int = 50) -> str:
    if not settings.RADARR_URL:
        return error("RADARR_URL is not configured")
    try:
        if search:
            data = await _get("/api/v3/movie/lookup", params={"term": search})
            results = []
            for m in data[:20]:
                entry: dict = {
                    "tmdb_id": m.get("tmdbId"),
                    "title": sanitize(m.get("title", "")),
                    "year": m.get("year"),
                    "overview": sanitize(m.get("overview", ""), max_len=200),
                    "status": m.get("status"),
                    "runtime": m.get("runtime"),
                }
                # Include internal Radarr ID if movie is already in library
                if m.get("id"):
                    entry["id"] = m["id"]
                results.append(entry)
            return json.dumps({"count": len(results), "results": results})
        else:
            data = await _get("/api/v3/movie")
            # Sort by added date, newest first
            data.sort(key=lambda m: m.get("added", ""), reverse=True)
            total = len(data)
            movies = []
            for m in data:
                has_file = m.get("hasFile", False)
                monitored = m.get("monitored", False)
                if filter == "missing" and has_file:
                    continue
                if filter == "wanted" and (has_file or not monitored):
                    continue
                movies.append({
                    "id": m.get("id"),
                    "title": sanitize(m.get("title", "")),
                    "year": m.get("year"),
                    "status": m.get("status"),
                    "added": (m.get("added") or "")[:10],
                    "has_file": has_file,
                    "monitored": monitored,
                    "size_mb": round((m.get("sizeOnDisk", 0) or 0) / 1_048_576, 1),
                })
                if limit > 0 and len(movies) >= limit:
                    break
            result: dict = {"count": len(movies), "total_in_library": total, "movies": movies}
            if limit > 0 and len(movies) >= limit:
                result["page"] = {"limit": limit, "returned": len(movies), "has_more": True}
            return json.dumps(result)
    except httpx.HTTPStatusError as e:
        return error(f"Radarr API error: HTTP {e.response.status_code}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Radarr at {_base_url()}")
    except Exception as e:
        logger.exception("radarr_movies failed")
        return error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "radarr_command",
        "description": (
            "Trigger a Radarr command: search for specific movies, all missing movies, "
            "or refresh a movie (rescan disk without searching). "
            "Actions: MoviesSearch (requires movie_ids), MissingMoviesSearch (no params), "
            "RefreshMovie (requires movie_ids — rescans disk state)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["MoviesSearch", "MissingMoviesSearch", "RefreshMovie"],
                    "description": "Command to execute.",
                },
                "movie_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Movie IDs (required for MoviesSearch and RefreshMovie).",
                },
            },
            "required": ["action"],
        },
    },
})
async def radarr_command(
    action: str,
    movie_ids: list[int] | None = None,
) -> str:
    if not settings.RADARR_URL:
        return error("RADARR_URL is not configured")
    try:
        payload: dict = {"name": action}
        if action in ("MoviesSearch", "RefreshMovie"):
            movie_ids = coerce_list(movie_ids, item_type=int) if movie_ids else []
            if not movie_ids:
                return error(f"movie_ids required for {action}")
            payload["movieIds"] = movie_ids
        result = await _post("/api/v3/command", payload)
        return json.dumps({
            "status": "ok",
            "command_id": result.get("id"),
            "action": action,
            "message": f"{action} command sent successfully",
        })
    except httpx.HTTPStatusError as e:
        return error(f"Radarr API error: HTTP {e.response.status_code}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Radarr at {_base_url()}")
    except Exception as e:
        logger.exception("radarr_command failed")
        return error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "radarr_queue",
        "description": (
            "Show items currently being downloaded or processed in Radarr's queue. "
            "Returns download progress, quality, size, and ETA."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
})
async def radarr_queue() -> str:
    if not settings.RADARR_URL:
        return error("RADARR_URL is not configured")
    try:
        data = await _get("/api/v3/queue", params={
            "pageSize": 50,
            "includeMovie": "true",
        })
        records = data.get("records", [])
        items = []
        for rec in records:
            movie = rec.get("movie", {})
            size_mb = round((rec.get("size", 0) or 0) / 1_048_576, 1)
            remaining_mb = round((rec.get("sizeleft", 0) or 0) / 1_048_576, 1)
            progress = round(100 * (1 - remaining_mb / size_mb), 1) if size_mb > 0 else 0
            item: dict = {
                "queue_id": rec.get("id"),
                "movie": sanitize(movie.get("title", "Unknown")),
                "movie_id": movie.get("id"),
                "year": movie.get("year"),
                "quality": rec.get("quality", {}).get("quality", {}).get("name", ""),
                "size_mb": size_mb,
                "remaining_mb": remaining_mb,
                "status": rec.get("status", ""),
                "tracked_status": rec.get("trackedDownloadStatus", ""),
                "progress_pct": progress,
                "eta": rec.get("estimatedCompletionTime", ""),
            }
            status_messages = rec.get("statusMessages", [])
            if status_messages:
                item["errors"] = [
                    sanitize(msg.get("title", ""), max_len=200)
                    for msg in status_messages[:3]
                ]
            items.append(item)
        return json.dumps({"count": len(items), "items": items})
    except httpx.HTTPStatusError as e:
        return error(f"Radarr API error: HTTP {e.response.status_code}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Radarr at {_base_url()}")
    except Exception as e:
        logger.exception("radarr_queue failed")
        return error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "radarr_releases",
        "description": (
            "Browse or grab releases for a Radarr movie. "
            "Use action='search' to list available releases sorted by seeders. "
            "Use action='grab' to download a specific release by guid + indexer_id."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["search", "grab"],
                    "description": "Action: 'search' to browse releases, 'grab' to download one.",
                },
                "movie_id": {
                    "type": "integer",
                    "description": "Movie ID (for search action).",
                },
                "guid": {
                    "type": "string",
                    "description": "Release GUID (for grab action).",
                },
                "indexer_id": {
                    "type": "integer",
                    "description": "Indexer ID (for grab action).",
                },
            },
            "required": ["action"],
        },
    },
})
async def radarr_releases(
    action: str,
    movie_id: int | None = None,
    guid: str | None = None,
    indexer_id: int | None = None,
) -> str:
    if not settings.RADARR_URL:
        return error("RADARR_URL is not configured")
    try:
        if action == "grab":
            if not guid or indexer_id is None:
                return error("guid and indexer_id required for grab")
            result = await _post("/api/v3/release", {"guid": guid, "indexerId": indexer_id})
            return json.dumps({
                "status": "ok",
                "message": "Release grabbed successfully",
            })

        # Default: search
        if movie_id is None:
            return error("movie_id required for search")

        data = await _get("/api/v3/release", params={"movieId": movie_id}, timeout=60.0)

        # Sort by seeders descending, take top 15
        data.sort(key=lambda r: r.get("seeders", 0) or 0, reverse=True)
        releases = []
        for r in data[:15]:
            size_bytes = r.get("size", 0) or 0
            releases.append({
                "title": sanitize(r.get("title", ""), max_len=200),
                "size_mb": round(size_bytes / 1_048_576, 1),
                "seeders": r.get("seeders", 0),
                "leechers": r.get("leechers", 0),
                "quality": r.get("quality", {}).get("quality", {}).get("name", ""),
                "guid": r.get("guid", ""),
                "indexer_id": r.get("indexerId", 0),
                "indexer": r.get("indexer", ""),
                "age_days": r.get("ageMinutes", 0) // 1440 if r.get("ageMinutes") else 0,
                "rejected": bool(r.get("rejections")),
                "rejection_reasons": r.get("rejections", [])[:3],
            })
        return json.dumps({"count": len(releases), "releases": releases})
    except httpx.HTTPStatusError as e:
        return error(f"Radarr API error: HTTP {e.response.status_code}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Radarr at {_base_url()}")
    except Exception as e:
        logger.exception("radarr_releases failed")
        return error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "radarr_history",
        "description": (
            "Get recent history events for a movie — shows grabs, imports, "
            "import failures, and deletions with error messages. Use to diagnose "
            "why downloads aren't importing."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "movie_id": {
                    "type": "integer",
                    "description": "Movie ID to get history for.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max events to return (default 30).",
                },
            },
            "required": ["movie_id"],
        },
    },
})
async def radarr_history(movie_id: int, limit: int = 30) -> str:
    if not settings.RADARR_URL:
        return error("RADARR_URL is not configured")
    try:
        data = await _get(f"/api/v3/history/movie", params={
            "movieId": movie_id,
            "includeMovie": "true",
        })
        records = data if isinstance(data, list) else data.get("records", [])
        events = []
        for rec in records[:limit]:
            evt_data = rec.get("data", {}) or {}
            event: dict = {
                "event_type": rec.get("eventType", ""),
                "date": rec.get("date", ""),
                "quality": rec.get("quality", {}).get("quality", {}).get("name", ""),
                "source_title": sanitize(rec.get("sourceTitle", ""), max_len=200),
            }
            evt_type = rec.get("eventType", "")
            if evt_type == "downloadFailed":
                event["error_message"] = sanitize(evt_data.get("message", ""), max_len=300)
            if evt_type == "downloadFolderImported":
                event["imported_path"] = evt_data.get("importedPath", "")
                event["dropped_path"] = evt_data.get("droppedPath", "")
            if evt_type == "movieFileDeleted":
                event["reason"] = evt_data.get("reason", "")
            events.append(event)
        return json.dumps({"count": len(events), "events": events})
    except httpx.HTTPStatusError as e:
        return error(f"Radarr API error: HTTP {e.response.status_code}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Radarr at {_base_url()}")
    except Exception as e:
        logger.exception("radarr_history failed")
        return error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "radarr_queue_manage",
        "description": (
            "Remove items from Radarr's download queue. Can optionally blocklist the release "
            "and/or remove from the download client (qBittorrent). Use this to clear stuck "
            "imports or cancel unwanted downloads. Get queue item IDs from radarr_queue() results."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "queue_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Queue record IDs to remove (from radarr_queue results).",
                },
                "blocklist": {
                    "type": "boolean",
                    "description": "Add release to blocklist to prevent re-grabbing (default false).",
                },
                "remove_from_client": {
                    "type": "boolean",
                    "description": "Also remove from download client/qBittorrent (default true).",
                },
            },
            "required": ["queue_ids"],
        },
    },
})
async def radarr_queue_manage(
    queue_ids: list[int],
    blocklist: bool = False,
    remove_from_client: bool = True,
) -> str:
    if not settings.RADARR_URL:
        return error("RADARR_URL is not configured")
    queue_ids = coerce_list(queue_ids, item_type=int)
    if not queue_ids:
        return error("queue_ids is required")
    try:
        results = []
        for qid in queue_ids:
            try:
                await _delete(f"/api/v3/queue/{qid}", params={
                    "removeFromClient": str(remove_from_client).lower(),
                    "blocklist": str(blocklist).lower(),
                })
                results.append({"id": qid, "status": "removed"})
            except httpx.HTTPStatusError as e:
                results.append({"id": qid, "status": "error", "error": str(e)[:200]})
        return json.dumps({
            "removed": sum(1 for r in results if r["status"] == "removed"),
            "errors": sum(1 for r in results if r["status"] == "error"),
            "results": results,
        })
    except httpx.ConnectError:
        return error(f"Cannot connect to Radarr at {_base_url()}")
    except Exception as e:
        logger.exception("radarr_queue_manage failed")
        return error(str(e))


def _format_quality_profile(profile: dict) -> dict:
    """Extract useful fields from a quality profile."""
    items = profile.get("items", [])
    cutoff = profile.get("cutoff")

    qualities = []
    cutoff_name = None
    for item in items:
        if item.get("allowed", False):
            if item.get("items"):
                group_name = item.get("name", "Group")
                group_qualities = [
                    q.get("quality", {}).get("name", "")
                    for q in item["items"]
                    if q.get("allowed", True)
                ]
                qualities.append({"group": group_name, "qualities": group_qualities})
                if item.get("id") == cutoff:
                    cutoff_name = group_name
            else:
                q = item.get("quality", {})
                qualities.append(q.get("name", "Unknown"))
                if q.get("id") == cutoff:
                    cutoff_name = q.get("name")

    return {
        "id": profile.get("id"),
        "name": sanitize(profile.get("name", "")),
        "cutoff": cutoff_name or str(cutoff),
        "upgrade_allowed": profile.get("upgradeAllowed", False),
        "qualities": qualities,
    }


@register({
    "type": "function",
    "function": {
        "name": "radarr_quality_profiles",
        "description": (
            "List or view Radarr quality profiles. Shows allowed qualities, cutoff, "
            "and upgrade settings. Use profile_id to view a specific profile in detail."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "profile_id": {
                    "type": "integer",
                    "description": "View a specific profile by ID. Omit to list all.",
                },
            },
        },
    },
})
async def radarr_quality_profiles(profile_id: int | None = None) -> str:
    if not settings.RADARR_URL:
        return error("RADARR_URL is not configured")
    try:
        if profile_id is not None:
            data = await _get(f"/api/v3/qualityprofile/{profile_id}")
            return json.dumps(_format_quality_profile(data))
        else:
            data = await _get("/api/v3/qualityprofile")
            profiles = [_format_quality_profile(p) for p in data]
            return json.dumps({"count": len(profiles), "profiles": profiles})
    except httpx.HTTPStatusError as e:
        return error(f"Radarr API error: {e}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Radarr at {_base_url()}")
    except Exception as e:
        logger.exception("radarr_quality_profiles failed")
        return error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "radarr_quality_profile_update",
        "description": (
            "Update a Radarr quality profile — enable/disable specific qualities, "
            "change the cutoff (quality target), or toggle upgrades. "
            "Use radarr_quality_profiles first to see current state and valid quality names."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "profile_id": {
                    "type": "integer",
                    "description": "Quality profile ID to update.",
                },
                "upgrade_allowed": {
                    "type": "boolean",
                    "description": "Whether to allow quality upgrades.",
                },
                "cutoff_quality": {
                    "type": "string",
                    "description": "Quality name or group name to set as cutoff target (e.g. 'Bluray-1080p', 'WEB 1080p'). Must be an allowed quality.",
                },
                "enable_qualities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Quality names to enable (e.g. ['Bluray-1080p', 'WEB 1080p']).",
                },
                "disable_qualities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Quality names to disable (e.g. ['SDTV', 'DVD']).",
                },
            },
            "required": ["profile_id"],
        },
    },
})
async def radarr_quality_profile_update(
    profile_id: int,
    upgrade_allowed: bool | None = None,
    cutoff_quality: str | None = None,
    enable_qualities: list[str] | None = None,
    disable_qualities: list[str] | None = None,
) -> str:
    if not settings.RADARR_URL:
        return error("RADARR_URL is not configured")
    try:
        profile = await _get(f"/api/v3/qualityprofile/{profile_id}")

        if upgrade_allowed is not None:
            profile["upgradeAllowed"] = upgrade_allowed

        enable_set = {q.lower() for q in (enable_qualities or [])}
        disable_set = {q.lower() for q in (disable_qualities or [])}
        cutoff_target = cutoff_quality.lower() if cutoff_quality else None
        new_cutoff_id = None

        def _process_items(items: list) -> None:
            nonlocal new_cutoff_id
            for item in items:
                if item.get("items"):
                    group_name = (item.get("name") or "").lower()
                    if group_name in enable_set:
                        item["allowed"] = True
                    elif group_name in disable_set:
                        item["allowed"] = False
                    if cutoff_target and group_name == cutoff_target:
                        new_cutoff_id = item.get("id")
                    for sub in item["items"]:
                        q_name = (sub.get("quality", {}).get("name") or "").lower()
                        if q_name in enable_set:
                            sub["allowed"] = True
                        elif q_name in disable_set:
                            sub["allowed"] = False
                        if cutoff_target and q_name == cutoff_target:
                            new_cutoff_id = sub.get("quality", {}).get("id")
                else:
                    q_name = (item.get("quality", {}).get("name") or "").lower()
                    if q_name in enable_set:
                        item["allowed"] = True
                    elif q_name in disable_set:
                        item["allowed"] = False
                    if cutoff_target and q_name == cutoff_target:
                        new_cutoff_id = item.get("quality", {}).get("id")

        _process_items(profile.get("items", []))

        if cutoff_target:
            if new_cutoff_id is None:
                return error(f"Cutoff quality '{cutoff_quality}' not found in profile. Use radarr_quality_profiles to see valid names.")
            profile["cutoff"] = new_cutoff_id

        result = await _put(f"/api/v3/qualityprofile/{profile_id}", profile)
        return json.dumps(_format_quality_profile(result))
    except httpx.HTTPStatusError as e:
        return error(f"Radarr API error: {e}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Radarr at {_base_url()}")
    except Exception as e:
        logger.exception("radarr_quality_profile_update failed")
        return error(str(e))
