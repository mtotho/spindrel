"""Sonarr tools — calendar, series, wanted, queue, commands, quality profiles."""

import json
import logging
from datetime import datetime, timedelta, timezone

import httpx

from integrations.arr.config import settings
from integrations._register import register

from integrations.arr.tools._helpers import coerce_list, error, sanitize, validate_url

logger = logging.getLogger(__name__)


def _base_url() -> str:
    return settings.SONARR_URL.rstrip("/")


def _headers() -> dict[str, str]:
    return {"X-Api-Key": settings.SONARR_API_KEY}


async def _get(path: str, params: dict | None = None, timeout: float = 15.0):
    url_err = validate_url(settings.SONARR_URL, "Sonarr")
    if url_err:
        raise ValueError(url_err)
    url = f"{_base_url()}{path}"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=_headers(), params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        body = e.response.text[:500] if e.response else ""
        raise httpx.HTTPStatusError(
            f"Sonarr {e.response.status_code} on {path}: {body}",
            request=e.request,
            response=e.response,
        )
    except httpx.TimeoutException:
        raise httpx.TimeoutException(
            f"Sonarr request timed out after {timeout}s: {path}"
        )


async def _post(path: str, payload: dict, timeout: float = 15.0):
    url_err = validate_url(settings.SONARR_URL, "Sonarr")
    if url_err:
        raise ValueError(url_err)
    url = f"{_base_url()}{path}"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=_headers(), json=payload, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        body = e.response.text[:500] if e.response else ""
        raise httpx.HTTPStatusError(
            f"Sonarr {e.response.status_code} on {path}: {body}",
            request=e.request,
            response=e.response,
        )
    except httpx.TimeoutException:
        raise httpx.TimeoutException(
            f"Sonarr request timed out after {timeout}s: {path}"
        )


async def _put(path: str, payload: dict, timeout: float = 15.0):
    url_err = validate_url(settings.SONARR_URL, "Sonarr")
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
            f"Sonarr {e.response.status_code} on {path}: {body}",
            request=e.request,
            response=e.response,
        )
    except httpx.TimeoutException:
        raise httpx.TimeoutException(
            f"Sonarr request timed out after {timeout}s: {path}"
        )


async def _delete(path: str, params: dict | None = None, timeout: float = 15.0):
    url_err = validate_url(settings.SONARR_URL, "Sonarr")
    if url_err:
        raise ValueError(url_err)
    url = f"{_base_url()}{path}"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.delete(url, headers=_headers(), params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.status_code
    except httpx.HTTPStatusError as e:
        body = e.response.text[:500] if e.response else ""
        raise httpx.HTTPStatusError(
            f"Sonarr {e.response.status_code} on {path}: {body}",
            request=e.request,
            response=e.response,
        )
    except httpx.TimeoutException:
        raise httpx.TimeoutException(
            f"Sonarr request timed out after {timeout}s: {path}"
        )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@register({
    "type": "function",
    "function": {
        "name": "sonarr_calendar",
        "description": (
            "Show upcoming TV episodes from Sonarr for the next N days. "
            "Returns episode titles, air dates, and download status."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "days_ahead": {
                    "type": "integer",
                    "description": "Number of days to look ahead (default 7).",
                },
            },
        },
    },
})
async def sonarr_calendar(days_ahead: int = 7) -> str:
    if not settings.SONARR_URL:
        return error("SONARR_URL is not configured")
    try:
        now = datetime.now(timezone.utc)
        params = {
            "start": now.strftime("%Y-%m-%d"),
            "end": (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d"),
            "includeSeries": "true",
        }
        data = await _get("/api/v3/calendar", params=params)
        episodes = []
        for ep in data:
            series = ep.get("series", {})
            episodes.append({
                "series": sanitize(series.get("title", "Unknown")),
                "season": ep.get("seasonNumber"),
                "episode": ep.get("episodeNumber"),
                "title": sanitize(ep.get("title", "")),
                "air_date": ep.get("airDateUtc", "")[:10],
                "has_file": ep.get("hasFile", False),
            })
        return json.dumps({"count": len(episodes), "episodes": episodes})
    except httpx.HTTPStatusError as e:
        return error(f"Sonarr API error: {e}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Sonarr at {_base_url()}")
    except Exception as e:
        logger.exception("sonarr_calendar failed")
        return error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "sonarr_series",
        "description": (
            "List monitored series in Sonarr or search TVDB. "
            "Use 'filter' to find a series in your library by name (fast, returns only matches). "
            "Use 'search' to look up new series on TVDB. "
            "IMPORTANT: Use the internal 'id' (NOT tvdb_id) for sonarr_episodes, sonarr_command, etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "search": {
                    "type": "string",
                    "description": "Search TVDB for new series to add. Returns tvdb_id + id (if in library).",
                },
                "filter": {
                    "type": "string",
                    "description": "Filter library series by name (case-insensitive substring match). Much faster than listing all.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results for library listing (default 50).",
                },
            },
        },
    },
})
async def sonarr_series(search: str | None = None, filter: str | None = None, limit: int = 50) -> str:
    if not settings.SONARR_URL:
        return error("SONARR_URL is not configured")
    try:
        if search:
            data = await _get("/api/v3/series/lookup", params={"term": search})
            results = []
            for s in data[:20]:
                entry: dict = {
                    "tvdb_id": s.get("tvdbId"),
                    "title": sanitize(s.get("title", "")),
                    "year": s.get("year"),
                    "status": s.get("status"),
                    "season_count": s.get("statistics", {}).get("seasonCount", 0),
                }
                if s.get("id"):
                    entry["id"] = s["id"]
                results.append(entry)
            return json.dumps({"count": len(results), "results": results})
        else:
            data = await _get("/api/v3/series")
            # Filter by name if provided
            if filter:
                filter_lower = filter.lower()
                data = [s for s in data if filter_lower in (s.get("title") or "").lower()]
            else:
                # Sort by added date, newest first (only when not filtering)
                data.sort(key=lambda s: s.get("added", ""), reverse=True)
            total = len(data)
            if limit > 0:
                data = data[:limit]
            series = []
            for s in data:
                stats = s.get("statistics", {})
                series.append({
                    "id": s.get("id"),
                    "title": sanitize(s.get("title", "")),
                    "year": s.get("year"),
                    "status": s.get("status"),
                    "added": (s.get("added") or "")[:10],
                    "season_count": stats.get("seasonCount", 0),
                    "episode_count": stats.get("episodeCount", 0),
                    "episode_file_count": stats.get("episodeFileCount", 0),
                    "monitored": s.get("monitored", False),
                })
            result: dict = {"count": len(series), "total_in_library": total, "series": series}
            if limit > 0 and total > limit:
                result["page"] = {"limit": limit, "returned": len(series), "has_more": True}
            return json.dumps(result)
    except httpx.HTTPStatusError as e:
        return error(f"Sonarr API error: {e}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Sonarr at {_base_url()}")
    except Exception as e:
        logger.exception("sonarr_series failed")
        return error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "sonarr_series_update",
        "description": (
            "Update a series in Sonarr — change quality profile, monitored status, "
            "series type, or path. Use sonarr_series() first to get the series internal ID "
            "and sonarr_quality_profiles() to get valid profile IDs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "series_id": {
                    "type": "integer",
                    "description": "Internal Sonarr series ID (the 'id' field, NOT tvdb_id).",
                },
                "quality_profile_id": {
                    "type": "integer",
                    "description": "Quality profile ID to assign (from sonarr_quality_profiles).",
                },
                "monitored": {
                    "type": "boolean",
                    "description": "Whether the series is monitored.",
                },
                "series_type": {
                    "type": "string",
                    "enum": ["standard", "daily", "anime"],
                    "description": "Series type.",
                },
            },
            "required": ["series_id"],
        },
    },
})
async def sonarr_series_update(
    series_id: int,
    quality_profile_id: int | None = None,
    monitored: bool | None = None,
    series_type: str | None = None,
) -> str:
    if not settings.SONARR_URL:
        return error("SONARR_URL is not configured")
    try:
        # Get current series data (PUT requires the full object)
        series = await _get(f"/api/v3/series/{series_id}")

        if quality_profile_id is not None:
            series["qualityProfileId"] = quality_profile_id
        if monitored is not None:
            series["monitored"] = monitored
        if series_type is not None:
            series["seriesType"] = series_type

        result = await _put(f"/api/v3/series/{series_id}", series)
        return json.dumps({
            "status": "ok",
            "id": result.get("id"),
            "title": sanitize(result.get("title", "")),
            "quality_profile_id": result.get("qualityProfileId"),
            "monitored": result.get("monitored"),
            "series_type": result.get("seriesType"),
        })
    except httpx.HTTPStatusError as e:
        return error(f"Sonarr API error: {e}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Sonarr at {_base_url()}")
    except Exception as e:
        logger.exception("sonarr_series_update failed")
        return error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "sonarr_wanted",
        "description": (
            "List missing episodes that Sonarr is looking for. "
            "Shows episodes that are monitored but not yet downloaded."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 20).",
                },
            },
        },
    },
})
async def sonarr_wanted(limit: int = 20) -> str:
    if not settings.SONARR_URL:
        return error("SONARR_URL is not configured")
    try:
        data = await _get("/api/v3/wanted/missing", params={
            "pageSize": limit,
            "sortKey": "airDateUtc",
            "sortDirection": "descending",
            "includeSeries": "true",
        })
        records = data.get("records", [])
        episodes = []
        for ep in records:
            series = ep.get("series", {})
            episodes.append({
                "series": sanitize(series.get("title", "Unknown")),
                "season": ep.get("seasonNumber"),
                "episode": ep.get("episodeNumber"),
                "title": sanitize(ep.get("title", "")),
                "air_date": ep.get("airDateUtc", "")[:10],
            })
        total_records = data.get("totalRecords", 0)
        return json.dumps({
            "total_records": total_records,
            "page": {"limit": limit, "returned": len(episodes), "has_more": len(episodes) < total_records},
            "episodes": episodes,
        })
    except httpx.HTTPStatusError as e:
        return error(f"Sonarr API error: {e}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Sonarr at {_base_url()}")
    except Exception as e:
        logger.exception("sonarr_wanted failed")
        return error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "sonarr_queue",
        "description": (
            "Show items currently being downloaded or processed in Sonarr's queue. "
            "Returns download progress, quality, size, and ETA."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
})
async def sonarr_queue() -> str:
    if not settings.SONARR_URL:
        return error("SONARR_URL is not configured")
    try:
        data = await _get("/api/v3/queue", params={
            "pageSize": 50,
            "includeSeries": "true",
            "includeEpisode": "true",
        })
        records = data.get("records", [])
        items = []
        for rec in records:
            series = rec.get("series", {})
            episode = rec.get("episode", {})
            size_mb = round((rec.get("size", 0) or 0) / 1_048_576, 1)
            remaining_mb = round((rec.get("sizeleft", 0) or 0) / 1_048_576, 1)
            progress = round(100 * (1 - remaining_mb / size_mb), 1) if size_mb > 0 else 0
            item: dict = {
                "queue_id": rec.get("id"),
                "series": sanitize(series.get("title", "Unknown")),
                "series_id": series.get("id"),
                "season": episode.get("seasonNumber"),
                "episode": episode.get("episodeNumber"),
                "episode_id": episode.get("id"),
                "quality": rec.get("quality", {}).get("quality", {}).get("name", ""),
                "size_mb": size_mb,
                "status": rec.get("status", ""),
                "progress_pct": progress,
            }
            # Only include tracked_status and errors when there's a problem
            tracked = rec.get("trackedDownloadStatus", "")
            if tracked and tracked != "ok":
                item["tracked_status"] = tracked
            status_messages = rec.get("statusMessages", [])
            if status_messages:
                item["errors"] = [
                    sanitize(msg.get("title", ""), max_len=150)
                    for msg in status_messages[:2]
                ]
            items.append(item)
        return json.dumps({"count": len(items), "items": items})
    except httpx.HTTPStatusError as e:
        return error(f"Sonarr API error: {e}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Sonarr at {_base_url()}")
    except Exception as e:
        logger.exception("sonarr_queue failed")
        return error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "sonarr_command",
        "description": (
            "Trigger a Sonarr command: search for a series, specific episodes, all missing episodes, "
            "or refresh a series (rescan disk without searching). "
            "Actions: SeriesSearch (requires series_id), EpisodeSearch (requires episode_ids), "
            "MissingEpisodeSearch (no params), RefreshSeries (requires series_id — rescans disk state)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["SeriesSearch", "EpisodeSearch", "MissingEpisodeSearch", "RefreshSeries"],
                    "description": "Command to execute.",
                },
                "series_id": {
                    "type": "integer",
                    "description": "Internal Sonarr series ID (the 'id' field, NOT tvdb_id). Required for SeriesSearch and RefreshSeries.",
                },
                "episode_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Episode IDs (required for EpisodeSearch).",
                },
            },
            "required": ["action"],
        },
    },
})
async def sonarr_command(
    action: str,
    series_id: int | None = None,
    episode_ids: list[int] | None = None,
) -> str:
    if not settings.SONARR_URL:
        return error("SONARR_URL is not configured")
    try:
        payload: dict = {"name": action}
        if action in ("SeriesSearch", "RefreshSeries"):
            if series_id is None:
                return error(f"series_id required for {action}")
            payload["seriesId"] = series_id
        elif action == "EpisodeSearch":
            episode_ids = coerce_list(episode_ids, item_type=int) if episode_ids else []
            if not episode_ids:
                return error("episode_ids required for EpisodeSearch")
            payload["episodeIds"] = episode_ids
        result = await _post("/api/v3/command", payload)
        return json.dumps({
            "status": "ok",
            "command_id": result.get("id"),
            "action": action,
            "message": f"{action} command sent successfully",
        })
    except httpx.HTTPStatusError as e:
        return error(f"Sonarr API error: {e}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Sonarr at {_base_url()}")
    except Exception as e:
        logger.exception("sonarr_command failed")
        return error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "sonarr_releases",
        "description": (
            "Browse or grab releases for a Sonarr episode. "
            "Use action='search' with episode_id to list available releases sorted by seeders. "
            "Use action='grab' to download a specific release by guid + indexer_id. "
            "To search for a whole series, use sonarr_command with SeriesSearch instead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["search", "grab"],
                    "description": "Action: 'search' to browse releases, 'grab' to download one.",
                },
                "episode_id": {
                    "type": "integer",
                    "description": "Episode ID (required for search action).",
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
async def sonarr_releases(
    action: str,
    episode_id: int | None = None,
    guid: str | None = None,
    indexer_id: int | None = None,
) -> str:
    if not settings.SONARR_URL:
        return error("SONARR_URL is not configured")
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
        if episode_id is None:
            return error("episode_id required for release search")
        params: dict = {"episodeId": episode_id}

        data = await _get("/api/v3/release", params=params, timeout=60.0)

        # Sort by seeders descending, take top 15
        data.sort(key=lambda r: r.get("seeders", 0) or 0, reverse=True)
        releases = []
        for r in data[:15]:
            size_bytes = r.get("size", 0) or 0
            entry: dict = {
                "title": sanitize(r.get("title", ""), max_len=120),
                "size_mb": round(size_bytes / 1_048_576, 1),
                "seeders": r.get("seeders", 0),
                "quality": r.get("quality", {}).get("quality", {}).get("name", ""),
                "guid": r.get("guid", ""),
                "indexer_id": r.get("indexerId", 0),
                "indexer": r.get("indexer", ""),
            }
            rejections = r.get("rejections", [])
            if rejections:
                entry["rejected"] = True
            releases.append(entry)
        return json.dumps({"count": len(releases), "releases": releases})
    except httpx.HTTPStatusError as e:
        return error(f"Sonarr API error: {e}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Sonarr at {_base_url()}")
    except Exception as e:
        logger.exception("sonarr_releases failed")
        return error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "sonarr_episodes",
        "description": (
            "Get episode details for a series — shows hasFile, episodeFileId, monitored status, "
            "and episode IDs needed for other operations. Essential for diagnosing phantom file "
            "references (hasFile=true but file is actually missing/corrupt)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "series_id": {
                    "type": "integer",
                    "description": "Internal Sonarr series ID (the 'id' field from sonarr_series, NOT tvdb_id).",
                },
                "season": {
                    "type": "integer",
                    "description": "Filter to specific season number. Omit for all seasons.",
                },
            },
            "required": ["series_id"],
        },
    },
})
async def sonarr_episodes(series_id: int, season: int | None = None) -> str:
    if not settings.SONARR_URL:
        return error("SONARR_URL is not configured")
    try:
        params: dict = {"seriesId": series_id, "includeEpisodeFile": "true"}
        if season is not None:
            params["seasonNumber"] = season
        data = await _get("/api/v3/episode", params=params)
        episodes = []
        for ep in data:
            has_file = ep.get("hasFile", False)
            entry: dict = {
                "id": ep.get("id"),
                "season": ep.get("seasonNumber"),
                "episode": ep.get("episodeNumber"),
                "title": sanitize(ep.get("title", ""), max_len=60),
                "has_file": has_file,
                "monitored": ep.get("monitored", False),
            }
            # Only include file details when a file exists
            if has_file:
                ep_file = ep.get("episodeFile", {}) or {}
                entry["file_quality"] = ep_file.get("quality", {}).get("quality", {}).get("name", "")
                entry["file_size_mb"] = round((ep_file.get("size", 0) or 0) / 1_048_576, 1)
            episodes.append(entry)
        return json.dumps({"count": len(episodes), "episodes": episodes})
    except httpx.HTTPStatusError as e:
        return error(f"Sonarr API error: {e}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Sonarr at {_base_url()}")
    except Exception as e:
        logger.exception("sonarr_episodes failed")
        return error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "sonarr_history",
        "description": (
            "Get recent history events for a series or episode — shows grabs, imports, "
            "import failures, and deletions with error messages. Use to diagnose why "
            "downloads aren't importing."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "series_id": {
                    "type": "integer",
                    "description": "Internal Sonarr series ID (the 'id' field, NOT tvdb_id).",
                },
                "episode_id": {
                    "type": "integer",
                    "description": "Episode ID for episode-specific history. Omit for full series history.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max events to return (default 30).",
                },
            },
            "required": ["series_id"],
        },
    },
})
async def sonarr_history(
    series_id: int,
    episode_id: int | None = None,
    limit: int = 30,
) -> str:
    if not settings.SONARR_URL:
        return error("SONARR_URL is not configured")
    try:
        if episode_id is not None:
            params: dict = {
                "pageSize": limit,
                "episodeId": episode_id,
                "includeSeries": "true",
                "includeEpisode": "true",
            }
            data = await _get("/api/v3/history", params=params)
        else:
            data = await _get(f"/api/v3/history/series", params={
                "seriesId": series_id,
                "includeSeries": "true",
                "includeEpisode": "true",
            })
        records = data if isinstance(data, list) else data.get("records", [])
        events = []
        for rec in records[:limit]:
            episode = rec.get("episode", {}) or {}
            evt_data = rec.get("data", {}) or {}
            event: dict = {
                "event_type": rec.get("eventType", ""),
                "date": (rec.get("date") or "")[:19],  # trim timezone
                "season": episode.get("seasonNumber") or evt_data.get("seasonNumber"),
                "episode": episode.get("episodeNumber") or evt_data.get("episodeNumber"),
                "quality": rec.get("quality", {}).get("quality", {}).get("name", ""),
                "source_title": sanitize(rec.get("sourceTitle", ""), max_len=100),
            }
            evt_type = rec.get("eventType", "")
            if evt_type == "downloadFailed":
                event["error_message"] = sanitize(evt_data.get("message", ""), max_len=150)
            events.append(event)
        return json.dumps({"count": len(events), "events": events})
    except httpx.HTTPStatusError as e:
        return error(f"Sonarr API error: {e}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Sonarr at {_base_url()}")
    except Exception as e:
        logger.exception("sonarr_history failed")
        return error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "sonarr_queue_manage",
        "description": (
            "Remove items from Sonarr's download queue. Can optionally blocklist the release "
            "and/or remove from the download client (qBittorrent). Use this to clear stuck "
            "imports, phantom file references, or cancel unwanted downloads. "
            "Get queue item IDs from sonarr_queue() results."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "queue_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Queue record IDs to remove (from sonarr_queue results).",
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
async def sonarr_queue_manage(
    queue_ids: list[int],
    blocklist: bool = False,
    remove_from_client: bool = True,
) -> str:
    if not settings.SONARR_URL:
        return error("SONARR_URL is not configured")
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
        return error(f"Cannot connect to Sonarr at {_base_url()}")
    except Exception as e:
        logger.exception("sonarr_queue_manage failed")
        return error(str(e))


def _format_quality_profile(profile: dict) -> dict:
    """Extract useful fields from a quality profile."""
    items = profile.get("items", [])
    cutoff = profile.get("cutoff")

    # Build quality list — handle both individual qualities and groups
    qualities = []
    cutoff_name = None
    for item in items:
        if item.get("allowed", False):
            if item.get("items"):
                # Quality group
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
                # Individual quality
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
        "name": "sonarr_quality_profiles",
        "description": (
            "List or view Sonarr quality profiles. Shows allowed qualities, cutoff, "
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
async def sonarr_quality_profiles(profile_id: int | None = None) -> str:
    if not settings.SONARR_URL:
        return error("SONARR_URL is not configured")
    try:
        if profile_id is not None:
            data = await _get(f"/api/v3/qualityprofile/{profile_id}")
            return json.dumps(_format_quality_profile(data))
        else:
            data = await _get("/api/v3/qualityprofile")
            profiles = [_format_quality_profile(p) for p in data]
            return json.dumps({"count": len(profiles), "profiles": profiles})
    except httpx.HTTPStatusError as e:
        return error(f"Sonarr API error: {e}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Sonarr at {_base_url()}")
    except Exception as e:
        logger.exception("sonarr_quality_profiles failed")
        return error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "sonarr_quality_profile_update",
        "description": (
            "Update a Sonarr quality profile — enable/disable specific qualities, "
            "change the cutoff (quality target), or toggle upgrades. "
            "Use sonarr_quality_profiles first to see current state and valid quality names."
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
                    "description": "Quality name or group name to set as cutoff target (e.g. 'HDTV-1080p', 'WEB 1080p'). Must be an allowed quality.",
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
async def sonarr_quality_profile_update(
    profile_id: int,
    upgrade_allowed: bool | None = None,
    cutoff_quality: str | None = None,
    enable_qualities: list[str] | None = None,
    disable_qualities: list[str] | None = None,
) -> str:
    if not settings.SONARR_URL:
        return error("SONARR_URL is not configured")
    try:
        # Get current profile
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
                    # Quality group
                    group_name = (item.get("name") or "").lower()
                    if group_name in enable_set:
                        item["allowed"] = True
                    elif group_name in disable_set:
                        item["allowed"] = False
                    if cutoff_target and group_name == cutoff_target:
                        new_cutoff_id = item.get("id")
                    # Also process individual qualities within the group
                    for sub in item["items"]:
                        q_name = (sub.get("quality", {}).get("name") or "").lower()
                        if q_name in enable_set:
                            sub["allowed"] = True
                        elif q_name in disable_set:
                            sub["allowed"] = False
                        if cutoff_target and q_name == cutoff_target:
                            new_cutoff_id = sub.get("quality", {}).get("id")
                else:
                    # Individual quality
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
                return error(f"Cutoff quality '{cutoff_quality}' not found in profile. Use sonarr_quality_profiles to see valid names.")
            profile["cutoff"] = new_cutoff_id

        result = await _put(f"/api/v3/qualityprofile/{profile_id}", profile)
        return json.dumps(_format_quality_profile(result))
    except httpx.HTTPStatusError as e:
        return error(f"Sonarr API error: {e}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Sonarr at {_base_url()}")
    except Exception as e:
        logger.exception("sonarr_quality_profile_update failed")
        return error(str(e))
