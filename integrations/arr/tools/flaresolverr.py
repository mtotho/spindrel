"""FlareSolverr tools — health, sessions, and end-to-end Cloudflare-bypass tests.

FlareSolverr exposes a single HTTP endpoint: ``POST /v1`` with a JSON body
``{"cmd": <command>, ...}``. There is no /health, no metrics by default, and
no authentication. Useful commands:

  - ``sessions.list``     — proves FS is reachable; carries version + active sessions
  - ``sessions.create``   — spins up a Chrome instance
  - ``sessions.destroy``  — frees a wedged session
  - ``request.get``       — actually fetches a URL through the Cloudflare bypass
"""

import json
import logging
import time
from typing import Any

import httpx

from integrations.arr.config import settings
from integrations.sdk import register_tool as register

from integrations.arr.tools._helpers import error, sanitize, validate_url

logger = logging.getLogger(__name__)

# Default to 90s — challenge solving can legitimately take 30-60s on the first
# request to a domain, and FS will time out internally before httpx does.
_DEFAULT_TIMEOUT = 90.0


def _base_url() -> str:
    return settings.FLARESOLVERR_URL.rstrip("/")


async def _post_v1(payload: dict, timeout: float = _DEFAULT_TIMEOUT) -> dict:
    """POST a command to FlareSolverr's /v1 endpoint and return the parsed JSON."""
    url_err = validate_url(settings.FLARESOLVERR_URL, "FlareSolverr")
    if url_err:
        raise ValueError(url_err)
    url = f"{_base_url()}/v1"
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json()


def _summarize_solution(solution: dict) -> dict:
    """Pull the interesting fields out of a request.get solution payload."""
    cookies = solution.get("cookies") or []
    cookie_names = {c.get("name", "") for c in cookies if isinstance(c, dict)}
    return {
        "solution_status": solution.get("status"),
        "solution_url": sanitize(solution.get("url", ""), max_len=300),
        "user_agent": sanitize(solution.get("userAgent", ""), max_len=300),
        "response_size": len(solution.get("response", "") or ""),
        "cookie_count": len(cookies),
        "cf_clearance": "cf_clearance" in cookie_names,
        "has_turnstile_token": bool(solution.get("turnstile_token")),
    }


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@register({
    "type": "function",
    "function": {
        "name": "flaresolverr_health",
        "description": (
            "Check whether FlareSolverr is reachable and alive. Returns FS version, "
            "uptime start, and the count of active browser sessions. THIS IS THE FIRST "
            "TOOL TO RUN when Cloudflare-protected indexers (1337x, EZTV, KickassTorrents) "
            "are failing — it tells you whether FS itself is the problem before you go "
            "poking at indexer tags or wiring."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}, returns={
        "type": "object",
        "properties": {
            "status": {
                "type": "string"
            },
            "base_url": {
                "type": "string"
            },
            "version": {
                "type": "string"
            },
            "fs_message": {
                "type": "string"
            },
            "session_count": {
                "type": "integer"
            },
            "active_sessions": {
                "type": "array",
                "items": {
                    "type": "string"
                }
            },
            "response_ms": {
                "type": "integer"
            },
            "error": {
                "type": "string"
            }
        }
    }
)
async def flaresolverr_health() -> str:
    if not settings.FLARESOLVERR_URL:
        return error("FLARESOLVERR_URL is not configured")
    started = time.monotonic()
    try:
        data = await _post_v1({"cmd": "sessions.list"}, timeout=15.0)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        sessions = data.get("sessions") or []
        return json.dumps({
            "status": "ok",
            "base_url": _base_url(),
            "version": data.get("version", "unknown"),
            "fs_message": sanitize(data.get("message", ""), max_len=300),
            "session_count": len(sessions),
            "active_sessions": [sanitize(str(s), max_len=80) for s in sessions],
            "response_ms": elapsed_ms,
        }, ensure_ascii=False)
    except httpx.ConnectError:
        return error(
            f"Cannot connect to FlareSolverr at {_base_url()} — container may be down "
            f"or FLARESOLVERR_URL is wrong"
        )
    except httpx.TimeoutException:
        return error(f"FlareSolverr at {_base_url()} timed out on sessions.list (FS may be wedged)")
    except httpx.HTTPStatusError as e:
        body = e.response.text[:300] if e.response else str(e)
        return error(f"FlareSolverr returned HTTP {e.response.status_code}: {sanitize(body, max_len=300)}")
    except Exception as e:
        logger.exception("flaresolverr_health failed")
        return error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "flaresolverr_sessions",
        "description": (
            "List, create, or destroy FlareSolverr browser sessions. Sessions are "
            "persistent Chrome instances that hold Cloudflare cookies between requests. "
            "Use 'list' to see what's active, 'create' to spin up a new one (catches "
            "'browser failed to start' issues), 'destroy' with session_id to free a "
            "wedged session."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "create", "destroy"],
                    "description": "Action to perform on sessions.",
                },
                "session_id": {
                    "type": "string",
                    "description": "Session ID — required for 'destroy', optional for 'create' (FS generates one if omitted).",
                },
            },
            "required": ["action"],
        },
    },
}, returns={
        "type": "object",
        "properties": {
            "status": {
                "type": "string"
            },
            "version": {
                "type": "string"
            },
            "session_count": {
                "type": "integer"
            },
            "sessions": {
                "type": "array",
                "items": {
                    "type": "string"
                }
            },
            "session_id": {
                "type": "string"
            },
            "message": {
                "type": "string"
            },
            "error": {
                "type": "string"
            }
        }
    }
)
async def flaresolverr_sessions(
    action: str,
    session_id: str | None = None,
) -> str:
    if not settings.FLARESOLVERR_URL:
        return error("FLARESOLVERR_URL is not configured")
    try:
        if action == "list":
            data = await _post_v1({"cmd": "sessions.list"}, timeout=15.0)
            sessions = data.get("sessions") or []
            return json.dumps({
                "status": "ok",
                "version": data.get("version", "unknown"),
                "session_count": len(sessions),
                "sessions": [sanitize(str(s), max_len=80) for s in sessions],
            }, ensure_ascii=False)

        if action == "create":
            payload: dict[str, Any] = {"cmd": "sessions.create"}
            if session_id:
                payload["session"] = session_id
            data = await _post_v1(payload, timeout=60.0)
            return json.dumps({
                "status": data.get("status", "ok"),
                "session_id": sanitize(str(data.get("session", "")), max_len=80),
                "message": sanitize(data.get("message", ""), max_len=300),
            }, ensure_ascii=False)

        if action == "destroy":
            if not session_id:
                return error("session_id is required for action='destroy'")
            data = await _post_v1(
                {"cmd": "sessions.destroy", "session": session_id},
                timeout=15.0,
            )
            return json.dumps({
                "status": data.get("status", "ok"),
                "session_id": session_id,
                "message": sanitize(data.get("message", ""), max_len=300),
            }, ensure_ascii=False)

        return error(f"Unknown action: {action}")
    except httpx.ConnectError:
        return error(f"Cannot connect to FlareSolverr at {_base_url()}")
    except httpx.TimeoutException:
        return error(f"FlareSolverr at {_base_url()} timed out on sessions.{action}")
    except httpx.HTTPStatusError as e:
        body = e.response.text[:300] if e.response else str(e)
        return error(f"FlareSolverr returned HTTP {e.response.status_code}: {sanitize(body, max_len=300)}")
    except Exception as e:
        logger.exception("flaresolverr_sessions failed")
        return error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "flaresolverr_test_fetch",
        "description": (
            "End-to-end test of FlareSolverr's Cloudflare bypass — actually fetch a URL "
            "through FS and report whether challenge solving worked. The smoking gun for "
            "diagnosing 'is FS currently solving challenges?'. A solution_status of 200 "
            "with cf_clearance=true proves FS is healthy. If FS returns an error message, "
            "this surfaces it directly so you can pattern-match (e.g. 'reCaptcha detected', "
            "'browser disconnected', 'Cloudflare challenge timeout')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": (
                        "URL to fetch through FlareSolverr. Use a known Cloudflare-protected "
                        "indexer URL (e.g. https://www.1337x.to/, https://eztvx.to/) when "
                        "diagnosing FS health, or the specific indexer URL that's failing."
                    ),
                },
                "session_id": {
                    "type": "string",
                    "description": "Optional existing session to reuse. Omit to use a one-shot request.",
                },
                "max_timeout_ms": {
                    "type": "integer",
                    "description": "FS internal timeout in milliseconds (default 60000).",
                },
            },
            "required": ["url"],
        },
    },
}, returns={
        "type": "object",
        "properties": {
            "fs_status": {
                "type": "string"
            },
            "fs_message": {
                "type": "string"
            },
            "fs_version": {
                "type": "string"
            },
            "response_ms": {
                "type": "integer"
            },
            "fetched_url": {
                "type": "string"
            },
            "solution_status": {
                "type": "integer"
            },
            "solution_url": {
                "type": "string"
            },
            "user_agent": {
                "type": "string"
            },
            "response_size": {
                "type": "integer"
            },
            "cookie_count": {
                "type": "integer"
            },
            "cf_clearance": {
                "type": "boolean"
            },
            "has_turnstile_token": {
                "type": "boolean"
            },
            "error": {
                "type": "string"
            }
        }
    }
)
async def flaresolverr_test_fetch(
    url: str,
    session_id: str | None = None,
    max_timeout_ms: int = 60000,
) -> str:
    if not settings.FLARESOLVERR_URL:
        return error("FLARESOLVERR_URL is not configured")
    started = time.monotonic()
    try:
        payload: dict[str, Any] = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": max_timeout_ms,
        }
        if session_id:
            payload["session"] = session_id
        # httpx timeout = FS internal timeout + 30s buffer for FS overhead
        data = await _post_v1(payload, timeout=(max_timeout_ms / 1000.0) + 30.0)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        result: dict[str, Any] = {
            "fs_status": data.get("status", "unknown"),
            "fs_message": sanitize(data.get("message", ""), max_len=300),
            "fs_version": data.get("version", "unknown"),
            "response_ms": elapsed_ms,
            "fetched_url": sanitize(url, max_len=300),
        }
        solution = data.get("solution")
        if isinstance(solution, dict):
            result.update(_summarize_solution(solution))
        return json.dumps(result, ensure_ascii=False)
    except httpx.ConnectError:
        return error(f"Cannot connect to FlareSolverr at {_base_url()}")
    except httpx.TimeoutException:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return error(
            f"FlareSolverr request.get timed out after {elapsed_ms}ms — "
            f"FS may be wedged, target may be unreachable, or max_timeout_ms is too low"
        )
    except httpx.HTTPStatusError as e:
        body = e.response.text[:300] if e.response else str(e)
        return error(f"FlareSolverr returned HTTP {e.response.status_code}: {sanitize(body, max_len=300)}")
    except Exception as e:
        logger.exception("flaresolverr_test_fetch failed")
        return error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "flaresolverr_destroy_all_sessions",
        "description": (
            "Destroy ALL active FlareSolverr sessions. This is the canonical 'turn it off "
            "and on again' fix for FS getting stuck after an upgrade or after a long-running "
            "session wedges. Less disruptive than restarting the container. Returns the count "
            "of sessions destroyed."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}, returns={
        "type": "object",
        "properties": {
            "status": {
                "type": "string"
            },
            "destroyed_count": {
                "type": "integer"
            },
            "destroyed": {
                "type": "array",
                "items": {
                    "type": "string"
                }
            },
            "failed": {
                "type": "array",
                "items": {
                    "type": "object"
                }
            },
            "version": {
                "type": "string"
            },
            "error": {
                "type": "string"
            }
        }
    }
)
async def flaresolverr_destroy_all_sessions() -> str:
    if not settings.FLARESOLVERR_URL:
        return error("FLARESOLVERR_URL is not configured")
    try:
        list_data = await _post_v1({"cmd": "sessions.list"}, timeout=15.0)
        sessions = list_data.get("sessions") or []
        destroyed: list[str] = []
        failed: list[dict] = []
        for s in sessions:
            sid = str(s)
            try:
                await _post_v1(
                    {"cmd": "sessions.destroy", "session": sid},
                    timeout=15.0,
                )
                destroyed.append(sid)
            except Exception as inner:
                failed.append({"session_id": sanitize(sid, max_len=80), "error": sanitize(str(inner), max_len=200)})
        return json.dumps({
            "status": "ok" if not failed else "partial",
            "destroyed_count": len(destroyed),
            "destroyed": [sanitize(s, max_len=80) for s in destroyed],
            "failed": failed,
            "version": list_data.get("version", "unknown"),
        }, ensure_ascii=False)
    except httpx.ConnectError:
        return error(f"Cannot connect to FlareSolverr at {_base_url()}")
    except httpx.TimeoutException:
        return error(f"FlareSolverr at {_base_url()} timed out listing sessions")
    except httpx.HTTPStatusError as e:
        body = e.response.text[:300] if e.response else str(e)
        return error(f"FlareSolverr returned HTTP {e.response.status_code}: {sanitize(body, max_len=300)}")
    except Exception as e:
        logger.exception("flaresolverr_destroy_all_sessions failed")
        return error(str(e))
