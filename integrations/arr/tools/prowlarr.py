"""Prowlarr tools — indexer management, search, status, applications."""

import json
import logging
from typing import Any

import httpx

from integrations.arr.config import settings
from integrations._register import register

from integrations.arr.tools._helpers import error, sanitize, validate_url

logger = logging.getLogger(__name__)


def _base_url() -> str:
    return settings.PROWLARR_URL.rstrip("/")


def _headers() -> dict[str, str]:
    return {"X-Api-Key": settings.PROWLARR_API_KEY}


async def _get(path: str, params: dict | None = None, timeout: float = 15.0):
    url_err = validate_url(settings.PROWLARR_URL, "Prowlarr")
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
            f"Prowlarr {e.response.status_code} on {path}: {body}",
            request=e.request,
            response=e.response,
        )
    except httpx.TimeoutException:
        raise httpx.TimeoutException(
            f"Prowlarr request timed out after {timeout}s: {path}"
        )


async def _post(path: str, payload: dict, timeout: float = 15.0):
    url_err = validate_url(settings.PROWLARR_URL, "Prowlarr")
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
            f"Prowlarr {e.response.status_code} on {path}: {body}",
            request=e.request,
            response=e.response,
        )
    except httpx.TimeoutException:
        raise httpx.TimeoutException(
            f"Prowlarr request timed out after {timeout}s: {path}"
        )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@register({
    "type": "function",
    "function": {
        "name": "prowlarr_indexers",
        "description": (
            "List or test Prowlarr indexers. Shows name, protocol, status (enabled/disabled), "
            "priority, and connected apps. Use action='test' with indexer_id to test connectivity. "
            "Use action='test_all' to test all indexers at once."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "test", "test_all"],
                    "description": "Action: 'list' (default), 'test' a specific indexer, 'test_all'.",
                },
                "indexer_id": {
                    "type": "integer",
                    "description": "Indexer ID (required for 'test' action).",
                },
            },
        },
    },
})
async def prowlarr_indexers(
    action: str = "list",
    indexer_id: int | None = None,
) -> str:
    if not settings.PROWLARR_URL:
        return error("PROWLARR_URL is not configured")
    try:
        if action == "test" and indexer_id is not None:
            # Get the indexer config first, then test it
            indexer = await _get(f"/api/v1/indexer/{indexer_id}")
            try:
                await _post("/api/v1/indexer/test", indexer)
                return json.dumps({
                    "indexer_id": indexer_id,
                    "name": sanitize(indexer.get("name", "")),
                    "test_result": "ok",
                })
            except httpx.HTTPStatusError as e:
                body = e.response.text[:300] if e.response else str(e)
                return json.dumps({
                    "indexer_id": indexer_id,
                    "name": sanitize(indexer.get("name", "")),
                    "test_result": "failed",
                    "error": sanitize(body, max_len=300),
                })

        if action == "test_all":
            try:
                await _post("/api/v1/indexer/testall", {})
                return json.dumps({"test_result": "ok", "message": "All indexers passed"})
            except httpx.HTTPStatusError as e:
                body = e.response.text[:500] if e.response else str(e)
                return json.dumps({
                    "test_result": "failed",
                    "error": sanitize(body, max_len=500),
                })

        # Default: list
        data = await _get("/api/v1/indexer")
        # Also get indexer statuses to merge failure info
        statuses = {}
        try:
            status_data = await _get("/api/v1/indexerstatus")
            for s in status_data:
                statuses[s.get("indexerId")] = s
        except Exception:
            pass  # Status endpoint is optional info

        indexers = []
        for idx in data:
            idx_id = idx.get("id")
            status = statuses.get(idx_id, {})
            entry: dict = {
                "id": idx_id,
                "name": sanitize(idx.get("name", "")),
                "protocol": idx.get("protocol", ""),
                "enabled": idx.get("enable", False),
                "priority": idx.get("priority", 25),
                "app_profile_id": idx.get("appProfileId"),
            }
            # Add failure info if indexer has issues
            if status:
                disabled_till = status.get("disabledTill")
                if disabled_till:
                    entry["disabled_till"] = disabled_till
                most_recent_failure = status.get("mostRecentFailure")
                if most_recent_failure:
                    entry["last_failure"] = most_recent_failure
                entry["escalation_level"] = status.get("escalationLevel", 0)
            indexers.append(entry)
        return json.dumps({"count": len(indexers), "indexers": indexers})
    except httpx.HTTPStatusError as e:
        return error(f"Prowlarr API error: {e}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Prowlarr at {_base_url()}")
    except Exception as e:
        logger.exception("prowlarr_indexers failed")
        return error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "prowlarr_search",
        "description": (
            "Search across all Prowlarr indexers for releases. Returns results from every "
            "configured indexer, showing which indexers found matches and which didn't. "
            "Useful for diagnosing 'no releases available' — if no indexer returns results, "
            "the content may not be indexed anywhere."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g. 'Grey\\'s Anatomy S22E12').",
                },
                "type": {
                    "type": "string",
                    "enum": ["search", "tvsearch", "movie"],
                    "description": "Search type: 'search' (general), 'tvsearch' (TV-specific), 'movie'. Default 'search'.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 20).",
                },
                "indexer_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Limit search to specific indexer IDs. Omit to search all.",
                },
            },
            "required": ["query"],
        },
    },
})
async def prowlarr_search(
    query: str,
    type: str = "search",
    limit: int = 20,
    indexer_ids: list[int] | None = None,
) -> str:
    if not settings.PROWLARR_URL:
        return error("PROWLARR_URL is not configured")
    try:
        params: dict = {"query": query, "type": type, "limit": 100}
        if indexer_ids:
            params["indexerIds"] = ",".join(str(i) for i in indexer_ids)

        data = await _get("/api/v1/search", params=params, timeout=60.0)

        # Sort by seeders descending
        data.sort(key=lambda r: r.get("seeders", 0) or 0, reverse=True)

        results = []
        for r in data[:limit]:
            size_bytes = r.get("size", 0) or 0
            results.append({
                "title": sanitize(r.get("title", ""), max_len=200),
                "size_mb": round(size_bytes / 1_048_576, 1),
                "seeders": r.get("seeders", 0),
                "leechers": r.get("leechers", 0),
                "indexer": sanitize(r.get("indexer", "")),
                "indexer_id": r.get("indexerId", 0),
                "protocol": r.get("protocol", ""),
                "age_days": r.get("age", 0),
                "guid": r.get("guid", ""),
                "categories": [
                    c.get("name", "") for c in (r.get("categories") or [])[:3]
                ],
            })
        return json.dumps({"count": len(results), "total_found": len(data), "results": results})
    except httpx.HTTPStatusError as e:
        return error(f"Prowlarr API error: {e}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Prowlarr at {_base_url()}")
    except Exception as e:
        logger.exception("prowlarr_search failed")
        return error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "prowlarr_apps",
        "description": (
            "List applications connected to Prowlarr (Sonarr, Radarr, etc.) and their sync status. "
            "Shows which apps receive indexer updates and whether sync is working."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
})
async def prowlarr_apps() -> str:
    if not settings.PROWLARR_URL:
        return error("PROWLARR_URL is not configured")
    try:
        data = await _get("/api/v1/applications")
        apps = []
        for app in data:
            apps.append({
                "id": app.get("id"),
                "name": sanitize(app.get("name", "")),
                "implementation": app.get("implementation", ""),
                "sync_level": app.get("syncLevel", ""),
            })
        return json.dumps({"count": len(apps), "apps": apps})
    except httpx.HTTPStatusError as e:
        return error(f"Prowlarr API error: {e}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Prowlarr at {_base_url()}")
    except Exception as e:
        logger.exception("prowlarr_apps failed")
        return error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "prowlarr_health",
        "description": (
            "Check Prowlarr system health — shows indexer issues, app sync problems, "
            "update availability, and other warnings. The first thing to check when "
            "indexers aren't working."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
})
async def prowlarr_health() -> str:
    if not settings.PROWLARR_URL:
        return error("PROWLARR_URL is not configured")
    try:
        data = await _get("/api/v1/health")
        issues = []
        for item in data:
            issues.append({
                "type": item.get("type", ""),
                "source": item.get("source", ""),
                "message": sanitize(item.get("message", ""), max_len=300),
                "wiki_url": item.get("wikiUrl", ""),
            })
        return json.dumps({"count": len(issues), "issues": issues})
    except httpx.HTTPStatusError as e:
        return error(f"Prowlarr API error: {e}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Prowlarr at {_base_url()}")
    except Exception as e:
        logger.exception("prowlarr_health failed")
        return error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "prowlarr_tags",
        "description": (
            "List Prowlarr tags. Tags link indexers to indexer proxies like FlareSolverr. "
            "Use this to find the tag ID for FlareSolverr before adding indexers that need it "
            "(e.g. 1337x, KickassTorrents — sites behind Cloudflare protection)."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
})
async def prowlarr_tags() -> str:
    if not settings.PROWLARR_URL:
        return error("PROWLARR_URL is not configured")
    try:
        data = await _get("/api/v1/tag")
        tags = []
        for t in data:
            tags.append({
                "id": t.get("id"),
                "label": sanitize(t.get("label", "")),
            })
        return json.dumps({"count": len(tags), "tags": tags})
    except httpx.HTTPStatusError as e:
        return error(f"Prowlarr API error: {e}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Prowlarr at {_base_url()}")
    except Exception as e:
        logger.exception("prowlarr_tags failed")
        return error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "prowlarr_indexer_schemas",
        "description": (
            "Browse available indexer types that can be added to Prowlarr. "
            "Returns all supported indexer definitions (ThePirateBay, 1337x, NZBgeek, etc.) "
            "with their protocol, privacy level, and required configuration fields. "
            "Use search to filter by name. Use this to find an indexer before adding it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "search": {
                    "type": "string",
                    "description": "Filter schemas by name (case-insensitive substring match).",
                },
            },
        },
    },
})
async def prowlarr_indexer_schemas(search: str | None = None) -> str:
    if not settings.PROWLARR_URL:
        return error("PROWLARR_URL is not configured")
    try:
        data = await _get("/api/v1/indexer/schema")
        schemas = []
        for s in data:
            name = s.get("name", "")
            if search and search.lower() not in name.lower():
                continue
            # Extract required fields info
            fields = []
            for f in s.get("fields", []):
                if f.get("name") == "definitionFile":
                    continue  # internal field
                fields.append({
                    "name": f.get("name", ""),
                    "label": f.get("label", ""),
                    "type": f.get("type", ""),
                    "required": not f.get("advanced", False),
                    "value": f.get("value"),
                })
            schemas.append({
                "definition_name": s.get("definitionName", ""),
                "name": sanitize(name),
                "implementation": s.get("implementation", ""),
                "protocol": s.get("protocol", ""),
                "privacy": s.get("privacy", ""),
                "supports_rss": s.get("supportsRss", False),
                "supports_search": s.get("supportsSearch", False),
                "fields": fields,
            })
        return json.dumps({"count": len(schemas), "schemas": schemas})
    except httpx.HTTPStatusError as e:
        return error(f"Prowlarr API error: {e}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Prowlarr at {_base_url()}")
    except Exception as e:
        logger.exception("prowlarr_indexer_schemas failed")
        return error(str(e))


async def _put(path: str, payload: dict, timeout: float = 15.0):
    url_err = validate_url(settings.PROWLARR_URL, "Prowlarr")
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
            f"Prowlarr {e.response.status_code} on {path}: {body}",
            request=e.request,
            response=e.response,
        )
    except httpx.TimeoutException:
        raise httpx.TimeoutException(
            f"Prowlarr request timed out after {timeout}s: {path}"
        )


async def _delete(path: str, timeout: float = 15.0):
    url_err = validate_url(settings.PROWLARR_URL, "Prowlarr")
    if url_err:
        raise ValueError(url_err)
    url = f"{_base_url()}{path}"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.delete(url, headers=_headers(), timeout=timeout)
            resp.raise_for_status()
            return resp.status_code
    except httpx.HTTPStatusError as e:
        body = e.response.text[:500] if e.response else ""
        raise httpx.HTTPStatusError(
            f"Prowlarr {e.response.status_code} on {path}: {body}",
            request=e.request,
            response=e.response,
        )
    except httpx.TimeoutException:
        raise httpx.TimeoutException(
            f"Prowlarr request timed out after {timeout}s: {path}"
        )


@register({
    "type": "function",
    "function": {
        "name": "prowlarr_indexer_manage",
        "description": (
            "Add, update, or remove a Prowlarr indexer. "
            "To add: use action='add' with definition_name (from prowlarr_indexer_schemas) and "
            "field_values for any required config (e.g. API key, base URL). "
            "To update: use action='update' with indexer_id and field_values to change. "
            "To enable/disable: use action='update' with indexer_id and enabled=true/false. "
            "To remove: use action='delete' with indexer_id."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "update", "delete"],
                    "description": "Action to perform.",
                },
                "indexer_id": {
                    "type": "integer",
                    "description": "Indexer ID (required for update/delete).",
                },
                "definition_name": {
                    "type": "string",
                    "description": "Schema definition name from prowlarr_indexer_schemas (required for add).",
                },
                "name": {
                    "type": "string",
                    "description": "Display name for the indexer (optional for add, uses definition name by default).",
                },
                "enabled": {
                    "type": "boolean",
                    "description": "Whether the indexer is enabled (default true for add).",
                },
                "priority": {
                    "type": "integer",
                    "description": "Indexer priority 1-50, lower = higher priority (default 25).",
                },
                "app_profile_id": {
                    "type": "integer",
                    "description": "App profile ID that controls which apps (Sonarr/Radarr) this indexer syncs to. Default 1 (standard). Required for add.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Tag IDs to assign (e.g. FlareSolverr proxy tag). Get IDs from prowlarr_tags. Empty array if none needed.",
                },
                "field_values": {
                    "type": "object",
                    "description": "Configuration field values as key-value pairs (e.g. {\"apiKey\": \"abc123\", \"baseUrl\": \"https://...\"}). Field names come from prowlarr_indexer_schemas.",
                },
            },
            "required": ["action"],
        },
    },
})
async def prowlarr_indexer_manage(
    action: str,
    indexer_id: int | None = None,
    definition_name: str | None = None,
    name: str | None = None,
    enabled: bool = True,
    priority: int = 25,
    app_profile_id: int = 1,
    tags: list[int] | None = None,
    field_values: dict[str, Any] | None = None,
) -> str:
    if not settings.PROWLARR_URL:
        return error("PROWLARR_URL is not configured")
    try:
        if action == "delete":
            if indexer_id is None:
                return error("indexer_id required for delete")
            await _delete(f"/api/v1/indexer/{indexer_id}")
            return json.dumps({"status": "ok", "message": f"Indexer {indexer_id} deleted"})

        if action == "add":
            if not definition_name:
                return error("definition_name required for add (get from prowlarr_indexer_schemas)")
            # Get the schema for this definition
            schemas = await _get("/api/v1/indexer/schema")
            schema = None
            for s in schemas:
                if s.get("definitionName", "").lower() == definition_name.lower():
                    schema = s
                    break
            if not schema:
                return error(f"Indexer definition '{definition_name}' not found. Use prowlarr_indexer_schemas to list available definitions.")

            # Build the indexer config from schema
            schema["name"] = name or schema.get("name", definition_name)
            schema["enable"] = enabled
            schema["priority"] = priority
            schema["appProfileId"] = app_profile_id
            schema["tags"] = tags if tags is not None else []

            # Apply field values
            if field_values:
                for field in schema.get("fields", []):
                    if field.get("name") in field_values:
                        field["value"] = field_values[field["name"]]

            result = await _post("/api/v1/indexer", schema)
            return json.dumps({
                "status": "ok",
                "indexer_id": result.get("id"),
                "name": sanitize(result.get("name", "")),
                "message": f"Indexer '{result.get('name', '')}' added successfully",
            })

        if action == "update":
            if indexer_id is None:
                return error("indexer_id required for update")
            # Get current config
            current = await _get(f"/api/v1/indexer/{indexer_id}")
            # Apply updates
            if name is not None:
                current["name"] = name
            current["enable"] = enabled
            current["priority"] = priority
            if field_values:
                for field in current.get("fields", []):
                    if field.get("name") in field_values:
                        field["value"] = field_values[field["name"]]

            result = await _put(f"/api/v1/indexer/{indexer_id}", current)
            return json.dumps({
                "status": "ok",
                "indexer_id": result.get("id"),
                "name": sanitize(result.get("name", "")),
                "message": f"Indexer '{result.get('name', '')}' updated",
            })

        return error(f"Unknown action: {action}")
    except httpx.HTTPStatusError as e:
        return error(f"Prowlarr API error: {e}")
    except httpx.ConnectError:
        return error(f"Cannot connect to Prowlarr at {_base_url()}")
    except Exception as e:
        logger.exception("prowlarr_indexer_manage failed")
        return error(str(e))
