"""ARR aggregate read tools.

The individual Sonarr/Radarr/qBit/etc. tools are still the right interface
for focused investigation and mutations. This module provides compact snapshot
tools for heartbeat-style sweeps where one model/tool iteration should gather
the routine read-only state across whichever services the user configured.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from integrations.arr.config import settings
from integrations.arr.tools._helpers import coerce_list
from integrations.arr.tools.bazarr import bazarr_subtitles
from integrations.arr.tools.jellyfin import jellyfin_library
from integrations.arr.tools.jellyseerr import jellyseerr_requests
from integrations.arr.tools.prowlarr import prowlarr_health, prowlarr_indexers
from integrations.arr.tools.qbit import qbit_torrents
from integrations.arr.tools.radarr import radarr_movies, radarr_queue
from integrations.arr.tools.sonarr import sonarr_calendar, sonarr_queue, sonarr_wanted
from integrations.sdk import register_tool as register

KNOWN_SERVICES = ("sonarr", "radarr", "qbit", "jellyfin", "jellyseerr", "prowlarr", "bazarr")
SERVICE_TIMEOUT_S = 25.0


def _configured(service: str) -> bool:
    if service == "sonarr":
        return bool(settings.SONARR_URL and settings.SONARR_API_KEY)
    if service == "radarr":
        return bool(settings.RADARR_URL and settings.RADARR_API_KEY)
    if service == "qbit":
        return bool(settings.QBIT_URL and settings.QBIT_USERNAME and settings.QBIT_PASSWORD)
    if service == "jellyfin":
        return bool(settings.JELLYFIN_URL and settings.JELLYFIN_API_KEY)
    if service == "jellyseerr":
        return bool(settings.JELLYSEERR_URL and settings.JELLYSEERR_API_KEY)
    if service == "prowlarr":
        return bool(settings.PROWLARR_URL and settings.PROWLARR_API_KEY)
    if service == "bazarr":
        return bool(settings.BAZARR_URL and settings.BAZARR_API_KEY)
    return False


def _parse_tool_json(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {"error": "Tool returned non-JSON output."}
    return payload if isinstance(payload, dict) else {"result": payload}


def _limit_array(payload: dict[str, Any], key: str, limit: int) -> dict[str, Any]:
    value = payload.get(key)
    if isinstance(value, list) and len(value) > limit:
        payload = dict(payload)
        payload[key] = value[:limit]
        payload[f"{key}_truncated"] = len(value) - limit
    return payload


def _classify_error(message: str) -> str:
    lower = message.lower()
    if "not configured" in lower:
        return "not_configured"
    if "cannot connect" in lower or "timed out" in lower or "timeout" in lower:
        return "unavailable"
    return "error"


async def _call_json(factory: Callable[[], Awaitable[str]]) -> dict[str, Any]:
    raw = await asyncio.wait_for(factory(), timeout=SERVICE_TIMEOUT_S)
    return _parse_tool_json(raw)


async def _service_snapshot(
    service: str,
    checks: dict[str, Callable[[], Awaitable[str]]],
    *,
    array_limits: dict[str, tuple[str, int]] | None = None,
) -> dict[str, Any]:
    if not _configured(service):
        return {"status": "not_configured", "error": f"{service} is not configured"}

    array_limits = array_limits or {}
    results = await asyncio.gather(
        *[_call_json(factory) for factory in checks.values()],
        return_exceptions=True,
    )

    payload: dict[str, Any] = {"status": "ok"}
    status = "ok"
    for key, result in zip(checks.keys(), results, strict=False):
        if isinstance(result, Exception):
            message = str(result) or type(result).__name__
            payload[key] = {"error": message}
            status = _classify_error(message)
            continue

        if "error" in result:
            error_text = str(result.get("error") or "unknown error")
            payload[key] = result
            if status == "ok":
                status = _classify_error(error_text)
            continue

        array_limit = array_limits.get(key)
        if array_limit:
            result = _limit_array(dict(result), array_limit[0], array_limit[1])
        payload[key] = result

    payload["status"] = status
    return payload


def _overall_status(services: dict[str, dict[str, Any]]) -> str:
    statuses = {str(section.get("status") or "error") for section in services.values()}
    if not services or statuses <= {"not_configured"}:
        return "unavailable"
    if statuses == {"ok"}:
        return "ok"
    if "ok" not in statuses:
        return "unavailable"
    return "partial"


def _summary_lines(services: dict[str, dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for name in KNOWN_SERVICES:
        section = services.get(name)
        if not section:
            continue
        status = section.get("status")
        if status != "ok":
            lines.append(f"{name}: {status}")
            continue
        if name == "sonarr":
            queue = section.get("queue") or {}
            wanted = section.get("wanted") or {}
            calendar = section.get("calendar") or {}
            lines.append(
                "sonarr: ok "
                f"({queue.get('count', 0)} queued, "
                f"{wanted.get('count', 0)} wanted, "
                f"{calendar.get('count', 0)} upcoming)"
            )
        elif name == "radarr":
            queue = section.get("queue") or {}
            wanted = section.get("wanted") or {}
            lines.append(
                "radarr: ok "
                f"({queue.get('count', 0)} queued, {wanted.get('count', 0)} wanted)"
            )
        elif name == "qbit":
            downloading = section.get("downloading") or {}
            stalled = section.get("stalled") or {}
            lines.append(
                "qbit: ok "
                f"({downloading.get('count', 0)} downloading, {stalled.get('count', 0)} stalled)"
            )
        elif name == "jellyseerr":
            pending = section.get("pending") or {}
            processing = section.get("processing") or {}
            lines.append(
                "jellyseerr: ok "
                f"({pending.get('total', pending.get('count', 0))} pending, "
                f"{processing.get('total', processing.get('count', 0))} processing)"
            )
        else:
            lines.append(f"{name}: ok")
    return lines


@register({
    "type": "function",
    "function": {
        "name": "arr_heartbeat_snapshot",
        "description": (
            "Read-only aggregate health/status snapshot for ARR stack heartbeats. "
            "Checks whichever ARR services are configured and gracefully reports "
            "not_configured/unavailable/error per service instead of failing the whole run. "
            "Use this before detailed Sonarr/Radarr/qBit/Jellyfin follow-up tools."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "include_services": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": list(KNOWN_SERVICES),
                    },
                    "description": "Subset of services to inspect. Default: all ARR services.",
                },
                "days_ahead": {
                    "type": "integer",
                    "description": "Days of Sonarr calendar to include (default 7, max 28).",
                    "minimum": 1,
                    "maximum": 28,
                    "default": 7,
                },
                "wanted_limit": {
                    "type": "integer",
                    "description": "Max wanted/missing/request rows per service section (default 20, max 100).",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20,
                },
                "queue_limit": {
                    "type": "integer",
                    "description": "Max queue/torrent rows per service section (default 20, max 100).",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20,
                },
            },
        },
    },
}, returns={
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["ok", "partial", "unavailable"]},
        "summary": {"type": "array", "items": {"type": "string"}},
        "services": {"type": "object"},
        "sonarr": {"type": "object"},
        "radarr": {"type": "object"},
        "qbit": {"type": "object"},
        "jellyfin": {"type": "object"},
        "jellyseerr": {"type": "object"},
        "prowlarr": {"type": "object"},
        "bazarr": {"type": "object"},
    },
    "required": ["status", "summary", "services"],
})
async def arr_heartbeat_snapshot(
    include_services: list[str] | str | None = None,
    days_ahead: int | None = 7,
    wanted_limit: int | None = 20,
    queue_limit: int | None = 20,
) -> str:
    try:
        days = max(1, min(int(days_ahead or 7), 28))
    except (TypeError, ValueError):
        days = 7
    try:
        wanted_n = max(1, min(int(wanted_limit or 20), 100))
    except (TypeError, ValueError):
        wanted_n = 20
    try:
        queue_n = max(1, min(int(queue_limit or 20), 100))
    except (TypeError, ValueError):
        queue_n = 20

    if include_services:
        requested = [
            str(item).strip().lower()
            for item in coerce_list(include_services)
            if str(item).strip().lower() in KNOWN_SERVICES
        ]
    else:
        requested = list(KNOWN_SERVICES)
    if not requested:
        requested = list(KNOWN_SERVICES)

    service_calls: dict[str, Awaitable[dict[str, Any]]] = {}
    for service in requested:
        if service == "sonarr":
            service_calls[service] = _service_snapshot(
                "sonarr",
                {
                    "queue": sonarr_queue,
                    "wanted": lambda: sonarr_wanted(limit=wanted_n),
                    "calendar": lambda: sonarr_calendar(days_ahead=days),
                },
                array_limits={
                    "queue": ("items", queue_n),
                    "wanted": ("items", wanted_n),
                    "calendar": ("episodes", queue_n),
                },
            )
        elif service == "radarr":
            service_calls[service] = _service_snapshot(
                "radarr",
                {
                    "queue": radarr_queue,
                    "wanted": lambda: radarr_movies(filter="wanted", limit=wanted_n),
                },
                array_limits={
                    "queue": ("items", queue_n),
                    "wanted": ("movies", wanted_n),
                },
            )
        elif service == "qbit":
            service_calls[service] = _service_snapshot(
                "qbit",
                {
                    "downloading": lambda: qbit_torrents(filter="downloading", limit=queue_n),
                    "stalled": lambda: qbit_torrents(filter="stalled", limit=queue_n),
                },
                array_limits={
                    "downloading": ("torrents", queue_n),
                    "stalled": ("torrents", queue_n),
                },
            )
        elif service == "jellyfin":
            service_calls[service] = _service_snapshot(
                "jellyfin",
                {
                    "stats": lambda: jellyfin_library(action="stats"),
                    "recent": lambda: jellyfin_library(action="recent", limit=queue_n),
                },
                array_limits={"recent": ("items", queue_n)},
            )
        elif service == "jellyseerr":
            service_calls[service] = _service_snapshot(
                "jellyseerr",
                {
                    "pending": lambda: jellyseerr_requests(filter="pending", limit=wanted_n),
                    "processing": lambda: jellyseerr_requests(filter="processing", limit=wanted_n),
                    "available": lambda: jellyseerr_requests(filter="available", limit=wanted_n, sort="modified"),
                },
                array_limits={
                    "pending": ("requests", wanted_n),
                    "processing": ("requests", wanted_n),
                    "available": ("requests", wanted_n),
                },
            )
        elif service == "prowlarr":
            service_calls[service] = _service_snapshot(
                "prowlarr",
                {
                    "health": prowlarr_health,
                    "indexers": prowlarr_indexers,
                },
                array_limits={
                    "health": ("issues", wanted_n),
                    "indexers": ("indexers", wanted_n),
                },
            )
        elif service == "bazarr":
            service_calls[service] = _service_snapshot(
                "bazarr",
                {
                    "status": lambda: bazarr_subtitles(action="status"),
                    "wanted_episodes": lambda: bazarr_subtitles(action="wanted", media_type="episodes", limit=wanted_n),
                    "wanted_movies": lambda: bazarr_subtitles(action="wanted", media_type="movies", limit=wanted_n),
                },
                array_limits={
                    "wanted_episodes": ("items", wanted_n),
                    "wanted_movies": ("items", wanted_n),
                },
            )

    results = await asyncio.gather(*service_calls.values(), return_exceptions=True)
    services: dict[str, dict[str, Any]] = {}
    for name, result in zip(service_calls.keys(), results, strict=False):
        if isinstance(result, Exception):
            message = str(result) or type(result).__name__
            services[name] = {"status": _classify_error(message), "error": message}
        else:
            services[name] = result

    payload: dict[str, Any] = {
        "status": _overall_status(services),
        "summary": _summary_lines(services),
        "services": {name: section.get("status") for name, section in services.items()},
    }
    payload.update(services)
    return json.dumps(payload, ensure_ascii=False)
