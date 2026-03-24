"""Radarr tools — movies listing, search, commands."""

import json
import logging

import httpx

from integrations.arr.config import settings
from integrations._register import register

from ._helpers import error, sanitize

logger = logging.getLogger(__name__)


def _base_url() -> str:
    return settings.RADARR_URL.rstrip("/")


def _headers() -> dict[str, str]:
    return {"X-Api-Key": settings.RADARR_API_KEY}


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
        "name": "radarr_movies",
        "description": (
            "List movies in Radarr or search TMDB for new movies to add. "
            "Without search: returns library movies (optionally filtered). "
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
            },
        },
    },
})
async def radarr_movies(search: str | None = None, filter: str | None = None) -> str:
    if not settings.RADARR_URL:
        return error("RADARR_URL is not configured")
    try:
        if search:
            data = await _get("/api/v3/movie/lookup", params={"term": search})
            results = []
            for m in data[:20]:
                results.append({
                    "tmdb_id": m.get("tmdbId"),
                    "title": sanitize(m.get("title", "")),
                    "year": m.get("year"),
                    "overview": sanitize(m.get("overview", ""), max_len=200),
                    "status": m.get("status"),
                    "runtime": m.get("runtime"),
                })
            return json.dumps({"count": len(results), "results": results})
        else:
            data = await _get("/api/v3/movie")
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
                    "has_file": has_file,
                    "monitored": monitored,
                    "size_mb": round((m.get("sizeOnDisk", 0) or 0) / 1_048_576, 1),
                })
            return json.dumps({"count": len(movies), "movies": movies})
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
            "Trigger a Radarr command: search for specific movies or all missing movies. "
            "Actions: MoviesSearch (requires movie_ids), MissingMoviesSearch (no params needed)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["MoviesSearch", "MissingMoviesSearch"],
                    "description": "Command to execute.",
                },
                "movie_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Movie IDs (required for MoviesSearch).",
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
        if action == "MoviesSearch":
            if not movie_ids:
                return error("movie_ids required for MoviesSearch")
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
