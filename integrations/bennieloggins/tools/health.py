"""Bennie Loggins read-only health tools — summary, poop logs, puke logs, vet visits."""

import json
import logging
from typing import Optional

import httpx

from integrations.bennieloggins.config import settings
from integrations._register import register

logger = logging.getLogger(__name__)


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.BENNIE_LOGGINS_API_KEY}"}


async def _get(path: str, params: dict | None = None) -> dict:
    base = settings.BENNIE_LOGGINS_BASE_URL.rstrip("/")
    url = f"{base}{path}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_headers(), params=params, timeout=15.0)
        resp.raise_for_status()
        return resp.json()


@register({
    "type": "function",
    "function": {
        "name": "bennie_loggins_health_summary",
        "description": (
            "Fetch a snapshot of Bennie's recent health data: poop logs, puke logs, "
            "eating issues, active medicines, food schedule. Call this first to orient "
            "before drilling into granular log history."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "recent_count": {
                    "type": "integer",
                    "description": "How many recent entries to include per log type (default: 10).",
                },
            },
            "required": [],
        },
    },
})
async def bennie_loggins_health_summary(recent_count: Optional[int] = None) -> str:
    try:
        params = {}
        if recent_count is not None:
            params["recentCount"] = recent_count
        data = await _get("/api/agent/summary", params or None)
        return json.dumps(data, default=str)
    except httpx.HTTPStatusError as e:
        msg = f"Error fetching health summary: HTTP {e.response.status_code} — {e.response.text}"
        logger.warning("%s", msg)
        return msg
    except Exception as e:
        msg = f"Error fetching health summary: {e}"
        logger.exception("bennie_loggins_health_summary")
        return msg


@register({
    "type": "function",
    "function": {
        "name": "bennie_loggins_health_poop_logs",
        "description": (
            "Fetch poop log history. Each log has moisture, form (Bristol 1-7), "
            "hasDrips, hasMucus, hasBlood, strainLevel, notes, healthScore. "
            "Filter by last_days or by start_date/end_date (ISO, e.g. 2026-01-01)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "last_days": {
                    "type": "integer",
                    "description": "Return only logs from the last N days.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Inclusive lower bound date (ISO format, e.g. 2026-01-01).",
                },
                "end_date": {
                    "type": "string",
                    "description": "Inclusive upper bound date (ISO format, e.g. 2026-03-13).",
                },
            },
            "required": [],
        },
    },
})
async def bennie_loggins_health_poop_logs(
    last_days: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    try:
        params: dict = {}
        if last_days is not None:
            params["lastDays"] = last_days
        else:
            if start_date is not None:
                params["startDate"] = start_date
            if end_date is not None:
                params["endDate"] = end_date
        data = await _get("/api/agent/pooplogs", params or None)
        return json.dumps(data, default=str)
    except httpx.HTTPStatusError as e:
        msg = f"Error fetching poop logs: HTTP {e.response.status_code} — {e.response.text}"
        logger.warning("%s", msg)
        return msg
    except Exception as e:
        msg = f"Error fetching poop logs: {e}"
        logger.exception("bennie_loggins_health_poop_logs")
        return msg


@register({
    "type": "function",
    "function": {
        "name": "bennie_loggins_health_puke_logs",
        "description": (
            "Fetch puke log history. Each log has pukeType, size, notes, healthScore. "
            "Filter by last_days or by start_date/end_date (ISO format)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "last_days": {
                    "type": "integer",
                    "description": "Return only logs from the last N days.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Inclusive lower bound date (ISO format, e.g. 2026-01-01).",
                },
                "end_date": {
                    "type": "string",
                    "description": "Inclusive upper bound date (ISO format, e.g. 2026-03-13).",
                },
            },
            "required": [],
        },
    },
})
async def bennie_loggins_health_puke_logs(
    last_days: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    try:
        params: dict = {}
        if last_days is not None:
            params["lastDays"] = last_days
        else:
            if start_date is not None:
                params["startDate"] = start_date
            if end_date is not None:
                params["endDate"] = end_date
        data = await _get("/api/agent/pukelogs", params or None)
        return json.dumps(data, default=str)
    except httpx.HTTPStatusError as e:
        msg = f"Error fetching puke logs: HTTP {e.response.status_code} — {e.response.text}"
        logger.warning("%s", msg)
        return msg
    except Exception as e:
        msg = f"Error fetching puke logs: {e}"
        logger.exception("bennie_loggins_health_puke_logs")
        return msg


@register({
    "type": "function",
    "function": {
        "name": "bennie_loggins_health_vet_visits",
        "description": (
            "Fetch vet visit history. Each visit has date, clinic, vet, weight, "
            "notable, procedures, treatments, nextAppointment, cost, notes. "
            "Filter by last_days or by start_date/end_date (ISO format)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "last_days": {
                    "type": "integer",
                    "description": "Return only visits from the last N days.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Inclusive lower bound date (ISO format, e.g. 2026-01-01).",
                },
                "end_date": {
                    "type": "string",
                    "description": "Inclusive upper bound date (ISO format, e.g. 2026-03-13).",
                },
            },
            "required": [],
        },
    },
})
async def bennie_loggins_health_vet_visits(
    last_days: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    try:
        params: dict = {}
        if last_days is not None:
            params["lastDays"] = last_days
        else:
            if start_date is not None:
                params["startDate"] = start_date
            if end_date is not None:
                params["endDate"] = end_date
        data = await _get("/api/agent/vet-visits", params or None)
        return json.dumps(data, default=str)
    except httpx.HTTPStatusError as e:
        msg = f"Error fetching vet visits: HTTP {e.response.status_code} — {e.response.text}"
        logger.warning("%s", msg)
        return msg
    except Exception as e:
        msg = f"Error fetching vet visits: {e}"
        logger.exception("bennie_loggins_health_vet_visits")
        return msg
