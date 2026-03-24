"""Bennie Loggins write tools — log poop, puke, eating issues, eating/drinking."""

import json
import logging
from typing import Optional

import httpx

from integrations.bennieloggins.config import settings
from integrations._register import register

logger = logging.getLogger(__name__)


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.BENNIE_LOGGINS_API_KEY}",
        "Content-Type": "application/json",
    }


async def _post(path: str, body: dict) -> dict:
    base = settings.BENNIE_LOGGINS_BASE_URL.rstrip("/")
    url = f"{base}{path}"
    # Strip None values so the API only sees fields we actually set
    body = {k: v for k, v in body.items() if v is not None}
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=_headers(), json=body, timeout=15.0)
        resp.raise_for_status()
        return resp.json()


@register({
    "type": "function",
    "function": {
        "name": "bennie_loggins_log_poop",
        "description": (
            "Log a poop entry for Bennie. Requires moisture (0-10), form (0-10, Bristol Stool Chart), "
            "and size (0-10). Optionally include color, location, notes, boolean flags "
            "(hasDrips, hasMucus, hasBlood), strainLevel, and createdAt timestamp override."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "moisture": {
                    "type": "integer",
                    "description": "Moisture level 0-10 scale.",
                },
                "form": {
                    "type": "integer",
                    "description": "Form 0-10 scale (Bristol Stool Chart).",
                },
                "size": {
                    "type": "integer",
                    "description": "Size 0-10 scale.",
                },
                "user": {
                    "type": "string",
                    "description": "Fuzzy user hint (name/email substring). Falls back to first user.",
                },
                "color": {
                    "type": "string",
                    "description": "Color description (e.g. 'brown', 'dark brown').",
                },
                "location": {
                    "type": "string",
                    "description": "Where it happened (e.g. 'backyard', 'walk').",
                },
                "notes": {
                    "type": "string",
                    "description": "Additional notes.",
                },
                "hasDrips": {
                    "type": "boolean",
                    "description": "Drippy at end (default false).",
                },
                "hasMucus": {
                    "type": "boolean",
                    "description": "Contains mucus (default false).",
                },
                "hasBlood": {
                    "type": "boolean",
                    "description": "Contains blood (default false).",
                },
                "strainLevel": {
                    "type": "string",
                    "enum": ["normal", "mild", "moderate", "severe"],
                    "description": "Strain level during defecation.",
                },
                "createdAt": {
                    "type": "string",
                    "description": "ISO timestamp override (e.g. '2026-03-24T12:00:00.000Z').",
                },
            },
            "required": ["moisture", "form", "size"],
        },
    },
})
async def bennie_loggins_log_poop(
    moisture: int,
    form: int,
    size: int,
    user: Optional[str] = None,
    color: Optional[str] = None,
    location: Optional[str] = None,
    notes: Optional[str] = None,
    hasDrips: Optional[bool] = None,
    hasMucus: Optional[bool] = None,
    hasBlood: Optional[bool] = None,
    strainLevel: Optional[str] = None,
    createdAt: Optional[str] = None,
) -> str:
    try:
        body = {
            "moisture": moisture,
            "form": form,
            "size": size,
            "user": user,
            "color": color,
            "location": location,
            "notes": notes,
            "hasDrips": hasDrips,
            "hasMucus": hasMucus,
            "hasBlood": hasBlood,
            "strainLevel": strainLevel,
            "createdAt": createdAt,
        }
        data = await _post("/api/agent/pooplogs", body)
        return json.dumps(data, default=str)
    except httpx.HTTPStatusError as e:
        msg = f"Error logging poop: HTTP {e.response.status_code} — {e.response.text}"
        logger.warning("%s", msg)
        return msg
    except Exception as e:
        msg = f"Error logging poop: {e}"
        logger.exception("bennie_loggins_log_poop")
        return msg


@register({
    "type": "function",
    "function": {
        "name": "bennie_loggins_log_puke",
        "description": (
            "Log a puke/vomit entry for Bennie. Requires pukeType and size (0-10). "
            "Optionally include notes and createdAt timestamp override."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pukeType": {
                    "type": "string",
                    "description": "Type of vomit (e.g. 'liquid/mucus', 'chunks', 'other').",
                },
                "size": {
                    "type": "integer",
                    "description": "Size 0-10 scale.",
                },
                "user": {
                    "type": "string",
                    "description": "Fuzzy user hint (name/email substring).",
                },
                "notes": {
                    "type": "string",
                    "description": "Additional notes (e.g. 'after eating grass').",
                },
                "createdAt": {
                    "type": "string",
                    "description": "ISO timestamp override.",
                },
            },
            "required": ["pukeType", "size"],
        },
    },
})
async def bennie_loggins_log_puke(
    pukeType: str,
    size: int,
    user: Optional[str] = None,
    notes: Optional[str] = None,
    createdAt: Optional[str] = None,
) -> str:
    try:
        body = {
            "pukeType": pukeType,
            "size": size,
            "user": user,
            "notes": notes,
            "createdAt": createdAt,
        }
        data = await _post("/api/agent/pukelogs", body)
        return json.dumps(data, default=str)
    except httpx.HTTPStatusError as e:
        msg = f"Error logging puke: HTTP {e.response.status_code} — {e.response.text}"
        logger.warning("%s", msg)
        return msg
    except Exception as e:
        msg = f"Error logging puke: {e}"
        logger.exception("bennie_loggins_log_puke")
        return msg


@register({
    "type": "function",
    "function": {
        "name": "bennie_loggins_log_eating_issue",
        "description": (
            "Log an eating issue for Bennie. Requires eatingIssueType. "
            "Optionally include notes and createdAt timestamp override."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "eatingIssueType": {
                    "type": "string",
                    "enum": ["feeding-refused", "partial-eating", "slow-eating", "picky"],
                    "description": "Type of eating issue.",
                },
                "user": {
                    "type": "string",
                    "description": "Fuzzy user hint (name/email substring).",
                },
                "notes": {
                    "type": "string",
                    "description": "Additional notes (e.g. 'Only ate half of breakfast').",
                },
                "createdAt": {
                    "type": "string",
                    "description": "ISO timestamp override.",
                },
            },
            "required": ["eatingIssueType"],
        },
    },
})
async def bennie_loggins_log_eating_issue(
    eatingIssueType: str,
    user: Optional[str] = None,
    notes: Optional[str] = None,
    createdAt: Optional[str] = None,
) -> str:
    try:
        body = {
            "eatingIssueType": eatingIssueType,
            "user": user,
            "notes": notes,
            "createdAt": createdAt,
        }
        data = await _post("/api/agent/eating-issues", body)
        return json.dumps(data, default=str)
    except httpx.HTTPStatusError as e:
        msg = f"Error logging eating issue: HTTP {e.response.status_code} — {e.response.text}"
        logger.warning("%s", msg)
        return msg
    except Exception as e:
        msg = f"Error logging eating issue: {e}"
        logger.exception("bennie_loggins_log_eating_issue")
        return msg


@register({
    "type": "function",
    "function": {
        "name": "bennie_loggins_log_eating_drinking",
        "description": (
            "Log an eating or drinking event for Bennie. Requires type ('eating' or 'drinking') "
            "and amount (0-10). Optionally include notes and createdAt timestamp override."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["eating", "drinking"],
                    "description": "'eating' or 'drinking'.",
                },
                "amount": {
                    "type": "integer",
                    "description": "Amount 0-10 scale.",
                },
                "user": {
                    "type": "string",
                    "description": "Fuzzy user hint (name/email substring).",
                },
                "notes": {
                    "type": "string",
                    "description": "Additional notes (e.g. 'Ate most of dinner bowl').",
                },
                "createdAt": {
                    "type": "string",
                    "description": "ISO timestamp override.",
                },
            },
            "required": ["type", "amount"],
        },
    },
})
async def bennie_loggins_log_eating_drinking(
    type: str,
    amount: int,
    user: Optional[str] = None,
    notes: Optional[str] = None,
    createdAt: Optional[str] = None,
) -> str:
    try:
        body = {
            "type": type,
            "amount": amount,
            "user": user,
            "notes": notes,
            "createdAt": createdAt,
        }
        data = await _post("/api/agent/eating-drinking", body)
        return json.dumps(data, default=str)
    except httpx.HTTPStatusError as e:
        msg = f"Error logging eating/drinking: HTTP {e.response.status_code} — {e.response.text}"
        logger.warning("%s", msg)
        return msg
    except Exception as e:
        msg = f"Error logging eating/drinking: {e}"
        logger.exception("bennie_loggins_log_eating_drinking")
        return msg
