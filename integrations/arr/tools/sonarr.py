"""Sonarr tools — calendar, series, wanted, queue, commands."""

import json
import logging
from datetime import datetime, timedelta, timezone

import httpx

from integrations.arr.config import settings
from integrations._register import register

from integrations.arr.tools._helpers import error, sanitize

logger = logging.getLogger(__name__)


def _base_url() -> str:
    return settings.SONARR_URL.rstrip("/")


def _headers() -> dict[str, str]:
    return {"X-Api-Key": settings.SONARR_API_KEY}


async def _get(path: str, params: dict | None = None, timeout: float = 15.0):
    url = f"{_base_url()}{path}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_headers(), params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()


async def _post(path: str, payload: dict, timeout: float = 15.0):
    url = f"{_base_url()}{path}"
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=_headers(), json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json()


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
        return error(f"Sonarr API error: HTTP {e.response.status_code}")
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
            "List monitored series in Sonarr or search TVDB for new series to add. "
            "Without search: returns all monitored series with episode counts. "
            "With search: searches TVDB for matching series."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "search": {
                    "type": "string",
                    "description": "Search term to look up on TVDB. Omit to list monitored series.",
                },
            },
        },
    },
})
async def sonarr_series(search: str | None = None) -> str:
    if not settings.SONARR_URL:
        return error("SONARR_URL is not configured")
    try:
        if search:
            data = await _get("/api/v3/series/lookup", params={"term": search})
            results = []
            for s in data[:20]:
                results.append({
                    "tvdb_id": s.get("tvdbId"),
                    "title": sanitize(s.get("title", "")),
                    "year": s.get("year"),
                    "overview": sanitize(s.get("overview", ""), max_len=200),
                    "status": s.get("status"),
                    "season_count": s.get("statistics", {}).get("seasonCount", 0),
                })
            return json.dumps({"count": len(results), "results": results})
        else:
            data = await _get("/api/v3/series")
            series = []
            for s in data:
                stats = s.get("statistics", {})
                series.append({
                    "id": s.get("id"),
                    "title": sanitize(s.get("title", "")),
                    "year": s.get("year"),
                    "status": s.get("status"),
                    "season_count": stats.get("seasonCount", 0),
                    "episode_count": stats.get("episodeCount", 0),
                    "episode_file_count": stats.get("episodeFileCount", 0),
                    "monitored": s.get("monitored", False),
                })
            return json.dumps({"count": len(series), "series": series})
    except httpx.HTTPStatusError as e:
        return error(f"Sonarr API error: HTTP {e.response.status_code}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Sonarr at {_base_url()}")
    except Exception as e:
        logger.exception("sonarr_series failed")
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
        return json.dumps({
            "total_records": data.get("totalRecords", 0),
            "episodes": episodes,
        })
    except httpx.HTTPStatusError as e:
        return error(f"Sonarr API error: HTTP {e.response.status_code}")
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
            items.append({
                "series": sanitize(series.get("title", "Unknown")),
                "season": episode.get("seasonNumber"),
                "episode": episode.get("episodeNumber"),
                "quality": rec.get("quality", {}).get("quality", {}).get("name", ""),
                "size_mb": size_mb,
                "remaining_mb": remaining_mb,
                "status": rec.get("status", ""),
                "progress_pct": progress,
                "eta": rec.get("estimatedCompletionTime", ""),
            })
        return json.dumps({"count": len(items), "items": items})
    except httpx.HTTPStatusError as e:
        return error(f"Sonarr API error: HTTP {e.response.status_code}")
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
            "Trigger a Sonarr command: search for a series, specific episodes, or all missing episodes. "
            "Actions: SeriesSearch (requires series_id), EpisodeSearch (requires episode_ids), "
            "MissingEpisodeSearch (no params needed)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["SeriesSearch", "EpisodeSearch", "MissingEpisodeSearch"],
                    "description": "Command to execute.",
                },
                "series_id": {
                    "type": "integer",
                    "description": "Series ID (required for SeriesSearch).",
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
        if action == "SeriesSearch":
            if series_id is None:
                return error("series_id required for SeriesSearch")
            payload["seriesId"] = series_id
        elif action == "EpisodeSearch":
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
        return error(f"Sonarr API error: HTTP {e.response.status_code}")
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
            "Browse or grab releases for a Sonarr series or episode. "
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
                "series_id": {
                    "type": "integer",
                    "description": "Series ID (for search action).",
                },
                "episode_id": {
                    "type": "integer",
                    "description": "Episode ID (for search action — more specific than series_id).",
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
    series_id: int | None = None,
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
        params: dict = {}
        if episode_id is not None:
            params["episodeId"] = episode_id
        elif series_id is not None:
            params["seriesId"] = series_id
        else:
            return error("series_id or episode_id required for search")

        data = await _get("/api/v3/release", params=params, timeout=30.0)

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
        return error(f"Sonarr API error: HTTP {e.response.status_code}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Sonarr at {_base_url()}")
    except Exception as e:
        logger.exception("sonarr_releases failed")
        return error(str(e))
