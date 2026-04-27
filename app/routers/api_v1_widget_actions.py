"""Widget action endpoint — dispatches interactive widget actions.

POST /api/v1/widget-actions

When a user interacts with an interactive component (toggle, button, select, etc.)
in a tool result widget, the frontend sends the action here. Dispatch modes:

- dispatch:"tool" — calls the named tool through the standard tool dispatch pipeline
  (policy checks, recording, envelope building). This is the default and preferred path.
- dispatch:"api" — proxies a request to an allowlisted internal API endpoint.
- dispatch:"widget_config" — patch a pinned widget's config and return a refreshed envelope.
- dispatch:"db_query" — read-only SQLite query against the pin's bundle DB (no lock).
- dispatch:"db_exec" — write SQLite statement against the pin's bundle DB (acquires lock).
- dispatch:"widget_handler" — invoke a @on_action handler in the pin's widget.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.domain.errors import (
    ConflictError,
    DomainError,
    ForbiddenError,
    NotFoundError,
    UnprocessableError,
    ValidationError,
)
from app.dependencies import verify_auth_or_user, get_db
from app.tools.mcp import call_mcp_tool, get_mcp_server_for_tool, is_mcp_tool
from app.tools.registry import call_local_tool, is_local_tool
from app.agent.tool_dispatch import (
    ToolResultEnvelope,
    _build_default_envelope,
    _build_envelope_from_optin,
)
from app.services.widget_templates import (
    apply_widget_template,
    get_state_poll_config,
    apply_state_poll,
    substitute_vars,
)
from app.services.native_app_widgets import (
    build_envelope_for_native_instance,
    dispatch_native_widget_action,
    get_native_widget_instance_for_pin,
    get_widget_instance,
)

logger = logging.getLogger(__name__)


def _load_pin_manifest_safely(pin):
    """Load the pin's bundle widget.yaml if present; None on any failure.

    Used by the db-dispatch path to decide whether to route a query at the
    bundle-local DB path or at a shared-suite DB path. Errors are non-fatal
    — an unparseable or missing manifest just means "no suite", which is
    the same fallback as a bundle that never had a manifest.
    """
    try:
        from app.services.widget_py import resolve_bundle_dir
        from app.services.widget_manifest import parse_manifest

        bundle_dir = resolve_bundle_dir(pin)
        yaml_path = bundle_dir / "widget.yaml"
        if not yaml_path.is_file():
            return None
        return parse_manifest(yaml_path)
    except Exception:
        logger.debug("manifest load failed for pin %s", getattr(pin, "id", "?"), exc_info=True)
        return None

# Widget-actions is a dispatch proxy; each mode enforces its own authorization:
#   - dispatch:"tool" → tool registry + approval pipeline
#   - dispatch:"api"  → proxied endpoint's require_scopes(...) gate
#   - dispatch:"widget_config" → pin ownership check
# The router-level gate here is authentication-only. A prior commit required
# the `chat` scope, but chat is specifically "post messages in channels" —
# widget-actions doesn't post messages, and gating on it locked out widgets
# emitted by bots whose API keys omit `chat`.
router = APIRouter(
    prefix="/widget-actions",
    tags=["widget-actions"],
    dependencies=[Depends(verify_auth_or_user)],
)


def _resolve_tool_name(name: str) -> str:
    from app.services.tool_execution import resolve_tool_name

    return resolve_tool_name(name)


def _classify_domain_error(exc: BaseException) -> str:
    """Map a raised exception to the structural ``error_kind`` slot.

    Recoverable, 4xx-shaped domain errors (input rejection, missing thing,
    state conflict) are surfaced to the caller as benign. Generic exceptions
    fall through to ``"internal"`` so the attention surface still pages on
    them.
    """
    if isinstance(exc, ValidationError):
        return "validation"
    if isinstance(exc, NotFoundError):
        return "not_found"
    if isinstance(exc, ConflictError):
        return "conflict"
    if isinstance(exc, ForbiddenError):
        return "forbidden"
    if isinstance(exc, UnprocessableError):
        return "unprocessable"
    if isinstance(exc, DomainError):
        return "domain"
    if isinstance(exc, HTTPException):
        return f"http_{exc.status_code}"
    return "internal"

# ── Allowlisted internal API path prefixes for dispatch:"api" ──
_API_ALLOWLIST = [
    "/api/v1/admin/tasks",
    "/api/v1/channels",
]


class WidgetActionRequest(BaseModel):
    dispatch: Literal[
        "tool", "api", "widget_config", "db_query", "db_exec", "widget_handler", "native_widget",
    ] = "tool"
    # For tool dispatch
    tool: str | None = None
    args: dict = {}
    # For widget_handler dispatch — the @on_action handler name to invoke.
    # ``args`` above carries the handler's argument dict.
    handler: str | None = None
    # For API dispatch
    endpoint: str | None = None
    method: str = "POST"
    body: dict | None = None
    # For widget_config dispatch — patch a pinned widget's config and return
    # the refreshed envelope rendered with the merged config. All pins (both
    # user dashboards and implicit channel dashboards) live in the dashboard
    # pin table and are addressed via ``dashboard_pin_id``.
    dashboard_pin_id: uuid.UUID | None = None
    widget_instance_id: uuid.UUID | None = None
    config: dict | None = None
    # For db_query / db_exec dispatch — SQL statement + optional params.
    # ``dashboard_pin_id`` above identifies which pin's DB to target.
    sql: str | None = None
    params: list | None = None
    action: str | None = None
    # Context
    channel_id: uuid.UUID | None = None
    bot_id: str | None = None
    source_record_id: uuid.UUID | None = None
    # When the dispatching widget has a state_poll, passing display_label lets
    # the backend fetch fresh state after the action and return that envelope
    # instead of the (often stateless) action template output.
    display_label: str | None = None
    # Current widget_config — sent so tool/state_poll args can substitute
    # {{config.*}} without a DB roundtrip to fetch the pin.
    widget_config: dict | None = None


class WidgetActionResponse(BaseModel):
    ok: bool
    envelope: dict | None = None
    error: str | None = None
    # Structural classification of an error so downstream observers can tell
    # a benign 4xx-shaped domain rejection (validation, not_found, conflict,
    # forbidden, unprocessable, domain, http_<status>) from a real system
    # crash (``"internal"``). ``None`` on success.
    error_kind: str | None = None
    api_response: dict | None = None
    db_result: dict | None = None
    # widget_handler dispatch: handler's return value (JSON-able).
    result: Any = None


@router.post("", response_model=WidgetActionResponse)
async def dispatch_widget_action(req: WidgetActionRequest, db: AsyncSession = Depends(get_db)):
    """Dispatch a widget action — tool call or API proxy."""

    if req.dispatch == "tool":
        return await _dispatch_tool(req, db)
    elif req.dispatch == "api":
        return await _dispatch_api(req)
    elif req.dispatch == "widget_config":
        return await _dispatch_widget_config(req)
    elif req.dispatch in ("db_query", "db_exec"):
        return await _dispatch_db(req, db)
    elif req.dispatch == "widget_handler":
        return await _dispatch_widget_handler(req, db)
    elif req.dispatch == "native_widget":
        return await _dispatch_native_widget(req, db)
    else:
        raise HTTPException(400, f"Unknown dispatch type: {req.dispatch}")


@router.get("/stream")
async def widget_event_stream_endpoint(
    channel_id: uuid.UUID = Query(..., description="Channel whose event bus to tail"),
    kinds: str | None = Query(
        None,
        description="Comma-separated ChannelEventKind values. Omit for no filter.",
    ),
    since: int | None = Query(
        None,
        description="Last seq seen; replay ring-buffered events after this seq.",
    ),
):
    """SSE stream of channel events, consumable by ``window.spindrel.stream``.

    Authenticates via the widget-actions router-level ``verify_auth_or_user``
    dependency — widget JWTs (bot-scoped) and user JWTs both work. The bot's
    ability to see the channel is the authorization ceiling; kind filtering
    is a bandwidth optimization, not a scope gate.
    """
    from app.services.widget_action_stream import (
        parse_kinds_csv,
        widget_event_stream,
    )

    try:
        kind_set = parse_kinds_csv(kinds)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return StreamingResponse(
        widget_event_stream(
            channel_id=channel_id,
            kinds=kind_set,
            since=since,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _dispatch_tool(req: WidgetActionRequest, db: AsyncSession) -> WidgetActionResponse:
    """Call a tool and return its envelope."""
    if not req.tool:
        return WidgetActionResponse(ok=False, error="Missing 'tool' field for tool dispatch")

    name = req.tool
    args_str = json.dumps(req.args) if req.args else "{}"

    # Resolve the actual tool name — MCP tools may be registered with a server
    # prefix (e.g., "homeassistant-HassTurnOff") but templates reference the
    # bare name ("HassTurnOff"). Try bare first, then scan MCP servers for a
    # prefixed match.
    resolved_name = _resolve_tool_name(name)

    # Resolve tool type and call it
    result: str | None = None
    error_msg: str | None = None

    from app.agent.context import current_bot_id, current_channel_id

    bot_token = current_bot_id.set(req.bot_id) if req.bot_id else None
    channel_token = current_channel_id.set(req.channel_id) if req.channel_id else None
    try:
        if is_local_tool(resolved_name):
            try:
                result = await asyncio.wait_for(
                    call_local_tool(resolved_name, args_str),
                    timeout=settings.TOOL_DISPATCH_TIMEOUT,
                )
            except asyncio.TimeoutError:
                error_msg = f"Tool '{resolved_name}' timed out"
            except Exception as exc:
                error_msg = f"Tool '{resolved_name}' failed: {exc}"
        elif is_mcp_tool(resolved_name):
            try:
                result = await asyncio.wait_for(
                    call_mcp_tool(resolved_name, args_str),
                    timeout=settings.TOOL_DISPATCH_TIMEOUT,
                )
            except asyncio.TimeoutError:
                error_msg = f"MCP tool '{resolved_name}' timed out"
            except Exception as exc:
                error_msg = f"MCP tool '{resolved_name}' failed: {exc}"
        else:
            return WidgetActionResponse(ok=False, error=f"Unknown tool: {name}")
    finally:
        if bot_token is not None:
            current_bot_id.reset(bot_token)
        if channel_token is not None:
            current_channel_id.reset(channel_token)

    if error_msg:
        return WidgetActionResponse(ok=False, error=error_msg)

    if result is None:
        return WidgetActionResponse(ok=True, envelope=None)

    # Build envelope from result. ``cap_body=False`` — the envelope is handed
    # directly to widget JS via ``window.spindrel.callTool``; truncating would
    # deliver ``body=None`` and break ``JSON.parse(env.body)`` consumers. Widget
    # dispatch never flows into the LLM context window that the cap protects.
    envelope = _build_result_envelope(
        resolved_name, result, req.widget_config, cap_body=False,
    )

    logger.info(
        "Widget action: tool=%s resolved=%s args=%s channel=%s result_preview=%.200s",
        name, resolved_name, args_str, req.channel_id, result or "",
    )

    # Dashboard pins render the enclosing widget, not the action tool. After
    # a mutation, refresh and persist the pin's own state_poll so the UI does
    # not briefly swap to a stateless action envelope.
    if req.dashboard_pin_id is not None:
        from app.services.dashboard_pins import get_pin, update_pin_envelope

        try:
            pin = await get_pin(db, req.dashboard_pin_id)
        except Exception:
            logger.warning(
                "Widget action pin lookup failed: pin=%s",
                req.dashboard_pin_id,
                exc_info=True,
            )
        else:
            pin_tool_name = _resolve_tool_name(pin.tool_name)
            pin_poll_cfg = get_state_poll_config(pin_tool_name)
            if pin_poll_cfg:
                invalidate_poll_cache_for(pin_poll_cfg)
                settle_ms = int(pin_poll_cfg.get("post_action_settle_ms", 500))
                if settle_ms > 0:
                    await asyncio.sleep(settle_ms / 1000.0)
                pin_channel_id = pin.source_channel_id or req.channel_id
                pin_config = pin.widget_config or req.widget_config
                polled = await _do_state_poll(
                    tool_name=pin_tool_name,
                    display_label=(
                        req.display_label
                        or pin.display_label
                        or (pin.envelope or {}).get("display_label")
                        or ""
                    ),
                    poll_cfg=pin_poll_cfg,
                    widget_config=pin_config,
                    bot_id=pin.source_bot_id or req.bot_id,
                    channel_id=pin_channel_id,
                )
                if polled is not None:
                    env_dict = polled.compact_dict()
                    if pin.source_bot_id is not None:
                        env_dict["source_bot_id"] = pin.source_bot_id
                    else:
                        env_dict.pop("source_bot_id", None)
                    if pin_channel_id is not None:
                        env_dict["source_channel_id"] = str(pin_channel_id)
                    else:
                        env_dict.pop("source_channel_id", None)
                    try:
                        await update_pin_envelope(db, pin.id, env_dict)
                    except Exception:
                        logger.warning(
                            "Dashboard pin envelope write-back failed after action: pin=%s",
                            pin.id,
                            exc_info=True,
                        )
                    return WidgetActionResponse(ok=True, envelope=env_dict)
                return WidgetActionResponse(ok=True, envelope=None)

    # If the action tool itself has a state_poll, invalidate and try to fetch
    # fresh state now. This is the legacy inline-widget path; dashboard pins
    # are handled above using the enclosing pin's tool/config instead.
    poll_cfg = get_state_poll_config(resolved_name)
    if poll_cfg:
        invalidate_poll_cache_for(poll_cfg)
        if req.display_label:
            # Brief delay to let the downstream system settle before polling.
            # HA service calls return immediately but state propagation to
            # GetLiveContext can lag 200-500ms, especially for remote devices
            # like Shellys. Without this, we'd cache a pre-mutation state and
            # serve it to subsequent refreshes within the 30s TTL.
            settle_ms = int(poll_cfg.get("post_action_settle_ms", 500))
            if settle_ms > 0:
                await asyncio.sleep(settle_ms / 1000.0)
            polled = await _do_state_poll(
                tool_name=resolved_name,
                display_label=req.display_label,
                poll_cfg=poll_cfg,
                widget_config=req.widget_config,
                bot_id=req.bot_id,
                channel_id=req.channel_id,
            )
            if polled is not None:
                return WidgetActionResponse(ok=True, envelope=polled.compact_dict())

    return WidgetActionResponse(ok=True, envelope=envelope.compact_dict())


async def _dispatch_api(req: WidgetActionRequest) -> WidgetActionResponse:
    """Proxy an API request to an allowlisted internal endpoint."""
    if not req.endpoint:
        return WidgetActionResponse(ok=False, error="Missing 'endpoint' field for API dispatch")

    # Validate against allowlist
    if not any(req.endpoint.startswith(prefix) for prefix in _API_ALLOWLIST):
        return WidgetActionResponse(
            ok=False,
            error=f"Endpoint '{req.endpoint}' is not in the widget action allowlist",
        )

    # Use httpx to proxy the request to ourselves
    import httpx

    base_url = f"http://127.0.0.1:{settings.PORT}"
    method = req.method.upper()
    url = f"{base_url}{req.endpoint}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(method, url, json=req.body)
            resp.raise_for_status()
            try:
                data = resp.json()
            except Exception:
                data = {"text": resp.text}
    except httpx.HTTPStatusError as exc:
        return WidgetActionResponse(ok=False, error=f"API error: {exc.response.status_code}")
    except Exception as exc:
        return WidgetActionResponse(ok=False, error=f"API request failed: {exc}")

    return WidgetActionResponse(ok=True, api_response=data)


async def _dispatch_db(req: WidgetActionRequest, db: AsyncSession) -> WidgetActionResponse:
    """Execute a SQLite read (db_query) or write (db_exec) on the pin's bundle DB.

    ``db_query`` — parameterised SELECT; returns ``rows`` as a list of dicts.
      No lock held — WAL mode lets concurrent readers run freely.
    ``db_exec`` — INSERT/UPDATE/DELETE/DDL; acquires the per-path asyncio lock
      so concurrent writes serialise safely.  Returns ``{lastInsertRowid,
      rowsAffected}``.

    Auth: widget bearer (bot-scoped) identifies the pin via ``dashboard_pin_id``.
    """
    import asyncio as _asyncio
    import sqlite3 as _sqlite3

    if not req.dashboard_pin_id:
        return WidgetActionResponse(ok=False, error="db_query/db_exec requires dashboard_pin_id")
    if not req.sql:
        return WidgetActionResponse(ok=False, error="db_query/db_exec requires sql")

    from app.services.dashboard_pins import get_pin
    from app.services.widget_db import acquire_db, resolve_db_path

    try:
        pin = await get_pin(db, req.dashboard_pin_id)
        # Load the pin's manifest so suite-shared bundles route to the
        # dashboard-scoped DB. Best-effort: if the manifest can't be parsed
        # we fall back to the bundle-local path resolver.
        manifest = _load_pin_manifest_safely(pin)
        db_path = resolve_db_path(pin, manifest)
    except ValueError as exc:
        return WidgetActionResponse(ok=False, error=str(exc))
    except Exception as exc:
        logger.warning("db dispatch pin lookup failed: %s", exc, exc_info=True)
        return WidgetActionResponse(ok=False, error="Pin not found")

    params = req.params or []
    sql = req.sql

    if req.dispatch == "db_query":
        # For bundles with a manifest (especially suite-shared DBs) we route
        # through acquire_db so migrations run on first open even if no
        # writer has opened the file yet. For unmanifested bundles we keep
        # the lock-free read path (WAL allows concurrent readers).
        if manifest is not None and manifest.db is not None:
            db_config = manifest.db
            try:
                async with acquire_db(db_path, db_config) as conn:
                    def _query_locked() -> list[dict]:
                        cursor = conn.execute(sql, params)
                        return [dict(row) for row in cursor.fetchall()]
                    rows = await _asyncio.to_thread(_query_locked)
            except Exception as exc:
                return WidgetActionResponse(ok=False, error=f"db_query failed: {exc}")
            return WidgetActionResponse(ok=True, db_result={"rows": rows})

        def _query() -> list[dict]:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = _sqlite3.connect(str(db_path), check_same_thread=False)
            conn.row_factory = _sqlite3.Row
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                cursor = conn.execute(sql, params)
                return [dict(row) for row in cursor.fetchall()]
            finally:
                conn.close()

        try:
            rows = await _asyncio.to_thread(_query)
        except Exception as exc:
            return WidgetActionResponse(ok=False, error=f"db_query failed: {exc}")
        return WidgetActionResponse(ok=True, db_result={"rows": rows})

    # db_exec — write path, hold the per-path lock.
    def _exec(conn: _sqlite3.Connection) -> dict:
        cursor = conn.execute(sql, params)
        conn.commit()
        return {
            "lastInsertRowid": cursor.lastrowid,
            "rowsAffected": cursor.rowcount,
        }

    db_config = manifest.db if manifest is not None else None
    try:
        async with acquire_db(db_path, db_config) as conn:
            result = await _asyncio.to_thread(_exec, conn)
    except Exception as exc:
        return WidgetActionResponse(ok=False, error=f"db_exec failed: {exc}")

    return WidgetActionResponse(ok=True, db_result=result)


async def _dispatch_widget_handler(
    req: WidgetActionRequest, db: AsyncSession,
) -> WidgetActionResponse:
    """Invoke a ``@on_action`` Python handler declared in the pin's ``widget.py``.

    Identity / scope flow:
      iframe → POST /widget-actions → pin lookup → invoke_action(pin, handler)
      Handler's ctx.tool(...) goes through the standard ``_check_tool_policy``
      gate under the pin's ``source_bot_id``. No elevation.
    """
    if not req.dashboard_pin_id:
        return WidgetActionResponse(
            ok=False, error="widget_handler requires dashboard_pin_id",
        )
    if not req.handler:
        return WidgetActionResponse(
            ok=False, error="widget_handler requires 'handler' field",
        )

    from app.services.dashboard_pins import get_pin
    from app.services.widget_py import invoke_action

    try:
        pin = await get_pin(db, req.dashboard_pin_id)
    except (HTTPException, DomainError) as exc:
        return WidgetActionResponse(
            ok=False, error=str(exc.detail), error_kind=_classify_domain_error(exc),
        )
    except Exception as exc:
        logger.warning("widget_handler pin lookup failed: %s", exc, exc_info=True)
        return WidgetActionResponse(ok=False, error="Pin not found", error_kind="not_found")

    try:
        result = await invoke_action(pin, req.handler, req.args or {})
    except FileNotFoundError as exc:
        return WidgetActionResponse(ok=False, error=str(exc), error_kind="not_found")
    except KeyError as exc:
        return WidgetActionResponse(ok=False, error=str(exc).strip("'\""), error_kind="validation")
    except PermissionError as exc:
        return WidgetActionResponse(ok=False, error=str(exc), error_kind="forbidden")
    except ValueError as exc:
        return WidgetActionResponse(ok=False, error=str(exc), error_kind="validation")
    except asyncio.TimeoutError:
        return WidgetActionResponse(
            ok=False, error=f"handler {req.handler!r} timed out", error_kind="timeout",
        )
    except Exception as exc:
        logger.exception("widget_handler %s failed", req.handler)
        return WidgetActionResponse(
            ok=False, error=f"{type(exc).__name__}: {exc}", error_kind="internal",
        )

    logger.info(
        "widget_handler dispatch: pin=%s handler=%s", req.dashboard_pin_id, req.handler,
    )
    return WidgetActionResponse(ok=True, result=result)


async def _dispatch_native_widget(
    req: WidgetActionRequest, db: AsyncSession,
) -> WidgetActionResponse:
    """Invoke a first-party native widget action.

    Accepts either ``widget_instance_id`` directly or ``dashboard_pin_id`` for
    convenience when the caller only knows the pinned host surface.
    """
    if not req.action:
        return WidgetActionResponse(ok=False, error="native_widget requires 'action'")

    instance = None
    pin = None
    if req.widget_instance_id is not None:
        instance = await get_widget_instance(db, req.widget_instance_id)
    elif req.dashboard_pin_id is not None:
        from app.services.dashboard_pins import get_pin

        try:
            pin = await get_pin(db, req.dashboard_pin_id)
        except (HTTPException, DomainError) as exc:
            return WidgetActionResponse(
                ok=False,
                error=str(exc.detail),
                error_kind=_classify_domain_error(exc),
            )
        instance = await get_native_widget_instance_for_pin(db, pin)
    else:
        return WidgetActionResponse(
            ok=False,
            error="native_widget requires widget_instance_id or dashboard_pin_id",
        )

    if instance is None:
        return WidgetActionResponse(
            ok=False, error="Native widget instance not found", error_kind="not_found",
        )

    try:
        result = await dispatch_native_widget_action(
            db,
            instance=instance,
            action=req.action,
            args=req.args or {},
            bot_id=req.bot_id,
        )
        await db.commit()
        await db.refresh(instance)
    except (HTTPException, DomainError) as exc:
        await db.rollback()
        return WidgetActionResponse(
            ok=False,
            error=str(exc.detail),
            error_kind=_classify_domain_error(exc),
        )
    except Exception as exc:
        await db.rollback()
        logger.exception("native_widget %s failed", req.action)
        return WidgetActionResponse(
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
            error_kind="internal",
        )

    envelope = build_envelope_for_native_instance(
        instance,
        display_label=pin.display_label if pin is not None else None,
        source_bot_id=pin.source_bot_id if pin is not None else req.bot_id,
    )
    if pin is not None:
        pin.envelope = envelope
        await db.commit()

    logger.info(
        "native_widget dispatch: instance=%s action=%s pin=%s",
        instance.id, req.action, req.dashboard_pin_id,
    )
    return WidgetActionResponse(ok=True, result=result, envelope=envelope)


def _build_result_envelope(
    tool_name: str,
    raw_result: str,
    widget_config: dict | None = None,
    *,
    cap_body: bool = True,
) -> ToolResultEnvelope:
    """Build a ToolResultEnvelope from a raw tool result string.

    Tries in order: _envelope opt-in → widget template → default envelope.
    ``widget_config`` is threaded into the widget template so ``{{widget_config.*}}``
    resolves against the caller's per-pin runtime config. ``{{config.*}}``
    remains as a deprecated compatibility alias.

    ``cap_body=False`` skips the 4KB body truncation for callers that need the
    full payload (e.g. widget-actions tool dispatch, where the envelope is
    handed straight to widget JS that parses ``body``).
    """
    # Try to parse as JSON and check for _envelope opt-in
    try:
        parsed = json.loads(raw_result)
        if isinstance(parsed, dict) and "_envelope" in parsed:
            return _build_envelope_from_optin(
                parsed["_envelope"], raw_result, cap_body=cap_body,
            )
    except (json.JSONDecodeError, TypeError):
        pass

    # Try widget template from integration manifests
    widget_env = apply_widget_template(tool_name, raw_result, widget_config)
    if widget_env is not None:
        return widget_env

    return _build_default_envelope(raw_result, cap_body=cap_body)


# ── State poll cache — deduplicates concurrent poll calls ──
# Keyed by (resolved_tool_name, json_args) so widgets that re-poll the same
# tool with different args (e.g. per-location weather) don't clobber each other.

_poll_cache: dict[tuple[str, str], tuple[float, str]] = {}
_POLL_CACHE_TTL = 30.0  # seconds


def _evict_stale_cache() -> None:
    """Remove expired entries from the poll cache."""
    now = time.monotonic()
    stale = [k for k, (ts, _) in _poll_cache.items() if now - ts >= _POLL_CACHE_TTL]
    for k in stale:
        del _poll_cache[k]


def invalidate_poll_cache_for(poll_cfg: dict) -> None:
    """Drop cached poll results for a given state_poll config.

    Called after any tool mutation that may have changed the polled state
    (widget-action dispatch or bot tool_dispatch) so the next refresh hits
    the real service instead of serving a pre-mutation cache hit. Invalidates
    all arg variants since we don't know which widget triggered the mutation.
    """
    poll_tool = poll_cfg.get("tool")
    if not poll_tool:
        return
    resolved = _resolve_tool_name(poll_tool)
    for key in [k for k in _poll_cache if k[0] == resolved]:
        _poll_cache.pop(key, None)


async def _do_state_poll(
    *, tool_name: str, display_label: str, poll_cfg: dict,
    widget_config: dict | None = None,
    bot_id: str | None = None,
    channel_id: uuid.UUID | None = None,
) -> ToolResultEnvelope | None:
    """Fetch fresh state via the configured poll tool and render its template.

    Used by both the /refresh endpoint and the post-action envelope swap in
    _dispatch_tool. Returns None on error.

    ``widget_config`` — per-pin runtime config. Exposed as
    ``{{widget_config.*}}`` in state_poll args so a toggled flag can change
    the tool arguments. ``{{config.*}}`` remains as a deprecated
    compatibility alias. The same config is also passed to the template
    engine so the rendered envelope can gate components on it.

    ``bot_id`` / ``channel_id`` — set as ContextVars during the tool call so
    poll tools that read ``current_bot_id`` / ``current_channel_id`` (e.g.
    list_api_endpoints, workspace tools) resolve identity from the pinned
    widget's source instead of returning "No bot context available."
    """
    from app.agent.context import current_bot_id, current_channel_id

    poll_tool = poll_cfg.get("tool")
    if not poll_tool:
        return None

    resolved_poll_tool = _resolve_tool_name(poll_tool)

    # Substitute widget_meta ({{display_label}}, {{tool_name}},
    # {{widget_config.*}})
    # into args so each pinned widget can re-poll with its own identifying
    # value. Static configs pass through unchanged.
    raw_args = poll_cfg.get("args", {}) or {}
    widget_meta = {
        "display_label": display_label,
        "tool_name": tool_name,
        "widget_config": widget_config or {},
        "config": widget_config or {},
        # HTML-template widgets read these off widget_meta so apply_state_poll
        # can re-emit them on the refreshed envelope — preserving iframe auth
        # across refreshes. Component widgets ignore them.
        "source_bot_id": bot_id,
        "source_channel_id": str(channel_id) if channel_id else None,
    }
    substituted_args = substitute_vars(raw_args, widget_meta)
    poll_args = json.dumps(substituted_args, sort_keys=True)
    cache_key = (resolved_poll_tool, poll_args)

    now = time.monotonic()
    cached = _poll_cache.get(cache_key)
    if cached and (now - cached[0]) < _POLL_CACHE_TTL:
        raw_result: str | None = cached[1]
    else:
        raw_result = None
        bot_token = current_bot_id.set(bot_id) if bot_id else None
        channel_token = current_channel_id.set(channel_id) if channel_id else None
        try:
            if is_local_tool(resolved_poll_tool):
                raw_result = await asyncio.wait_for(
                    call_local_tool(resolved_poll_tool, poll_args),
                    timeout=settings.TOOL_DISPATCH_TIMEOUT,
                )
            elif is_mcp_tool(resolved_poll_tool):
                raw_result = await asyncio.wait_for(
                    call_mcp_tool(resolved_poll_tool, poll_args),
                    timeout=settings.TOOL_DISPATCH_TIMEOUT,
                )
            else:
                logger.warning("Unknown poll tool: %s", poll_tool)
                return None
        except asyncio.TimeoutError:
            logger.warning("Poll tool '%s' timed out", resolved_poll_tool)
            return None
        except Exception:
            logger.warning("Poll tool '%s' failed", resolved_poll_tool, exc_info=True)
            return None
        finally:
            if bot_token is not None:
                current_bot_id.reset(bot_token)
            if channel_token is not None:
                current_channel_id.reset(channel_token)

        if raw_result is None:
            return None

        _poll_cache[cache_key] = (now, raw_result)

    return apply_state_poll(tool_name, raw_result, widget_meta)


class WidgetRefreshRequest(BaseModel):
    tool_name: str
    display_label: str = ""
    # Channel-scope refresh context. Optional when dashboard_pin_id is set.
    channel_id: uuid.UUID | None = None
    bot_id: str | None = None
    # Dashboard-scope refresh — persists the fresh envelope back onto the pin.
    dashboard_pin_id: uuid.UUID | None = None
    # Current pin config — exposed as {{config.*}} in state_poll args and in
    # the state_poll template. Optional; missing = empty dict (defaults only).
    widget_config: dict | None = None


@router.post("/refresh", response_model=WidgetActionResponse)
async def refresh_widget_state(req: WidgetRefreshRequest):
    """Fetch fresh state for a pinned widget by calling its state_poll tool.

    The state_poll config is declared in the widget template YAML. Results are
    cached for 30s to avoid redundant calls when multiple pinned widgets from
    the same integration refresh on page load.
    """
    _evict_stale_cache()

    poll_cfg = get_state_poll_config(req.tool_name)
    if not poll_cfg:
        return WidgetActionResponse(ok=False, error=f"No state_poll config for {req.tool_name}")
    if not poll_cfg.get("tool"):
        return WidgetActionResponse(ok=False, error="state_poll missing 'tool' field")

    # If a dashboard pin is named, the pin's source_bot_id / source_channel_id
    # are authoritative (pin saved at creation time with the bot identity it
    # should refresh as). Request fields fall back when no pin is named — used
    # by inline channel widgets that pass their own context.
    pin_bot_id: str | None = None
    pin_channel_id: uuid.UUID | None = None
    if req.dashboard_pin_id is not None:
        from app.db.engine import async_session
        from app.db.models import WidgetDashboardPin
        try:
            async with async_session() as db:
                pin_row = await db.get(WidgetDashboardPin, req.dashboard_pin_id)
                if pin_row is not None:
                    pin_bot_id = pin_row.source_bot_id
                    pin_channel_id = pin_row.source_channel_id
        except Exception:
            logger.warning(
                "Dashboard pin lookup for refresh context failed: pin=%s",
                req.dashboard_pin_id, exc_info=True,
            )

    envelope = await _do_state_poll(
        tool_name=req.tool_name,
        display_label=req.display_label,
        poll_cfg=poll_cfg,
        widget_config=req.widget_config,
        bot_id=pin_bot_id or req.bot_id,
        channel_id=pin_channel_id or req.channel_id,
    )
    if envelope is None:
        return WidgetActionResponse(ok=False, error="State poll failed to produce an envelope")

    env_dict = envelope.compact_dict()

    # Pin identity is write-once at create, never mutated by refresh. The pin
    # row owns source_bot_id / source_channel_id; the envelope's copy is a
    # cache. Without this, a pin that ever held a bad bot id would re-stamp
    # itself on every refresh (self-amplifying loop).
    if req.dashboard_pin_id is not None:
        if pin_bot_id is not None:
            env_dict["source_bot_id"] = pin_bot_id
        else:
            env_dict.pop("source_bot_id", None)
        if pin_channel_id is not None:
            env_dict["source_channel_id"] = str(pin_channel_id)
        else:
            env_dict.pop("source_channel_id", None)

    # Persist dashboard-pin refreshes back to the table so reloads see fresh
    # state. Channel pins already get written back through the OmniPanel's
    # envelope-update store → POST /widget-pins flow; dashboard pins have no
    # equivalent store-side persist, so do it here.
    if req.dashboard_pin_id is not None:
        from app.db.engine import async_session
        from app.services.dashboard_pins import update_pin_envelope
        try:
            async with async_session() as db:
                await update_pin_envelope(db, req.dashboard_pin_id, env_dict)
        except Exception:
            logger.warning(
                "Dashboard pin envelope write-back failed: pin=%s",
                req.dashboard_pin_id, exc_info=True,
            )

    logger.info(
        "Widget refresh: tool=%s display_label=%s", req.tool_name, req.display_label,
    )
    return WidgetActionResponse(ok=True, envelope=env_dict)


async def _dispatch_widget_config(req: WidgetActionRequest) -> WidgetActionResponse:
    """Patch a pinned widget's config and return a refreshed envelope.

    All pins (both user dashboards and implicit channel dashboards) live in
    ``widget_dashboard_pins`` and are addressed via ``dashboard_pin_id``.

    Invalidates the state_poll cache and calls ``_do_state_poll`` with the
    merged config so templated ``{{config.*}}`` in state_poll args picks up
    the new value.
    """
    if req.config is None:
        return WidgetActionResponse(ok=False, error="Missing 'config' for widget_config dispatch")
    if req.dashboard_pin_id is None:
        return WidgetActionResponse(ok=False, error="Missing 'dashboard_pin_id' for widget_config dispatch")

    from app.db.engine import async_session
    from app.services.dashboard_pins import apply_dashboard_pin_config_patch

    try:
        async with async_session() as db:
            patched_pin = await apply_dashboard_pin_config_patch(
                db, req.dashboard_pin_id, req.config, merge=True,
            )
    except (HTTPException, DomainError) as exc:
        return WidgetActionResponse(
            ok=False,
            error=f"Pin patch failed: {exc.detail}",
            error_kind=_classify_domain_error(exc),
        )
    except Exception as exc:
        return WidgetActionResponse(
            ok=False, error=f"Pin patch failed: {exc}", error_kind="internal",
        )

    merged_config = patched_pin.get("widget_config") or {}
    tool_name = patched_pin.get("tool_name", "")
    resolved = _resolve_tool_name(tool_name)

    poll_cfg = get_state_poll_config(resolved)
    if not poll_cfg:
        # Without a state_poll we can't re-render — caller should apply the
        # new config client-side against the existing envelope.
        return WidgetActionResponse(ok=True, envelope=None, api_response=patched_pin)

    invalidate_poll_cache_for(poll_cfg)
    pin_bot_id = patched_pin.get("source_bot_id")
    pin_channel_raw = patched_pin.get("source_channel_id")
    pin_channel_uuid: uuid.UUID | None = None
    if pin_channel_raw:
        try:
            pin_channel_uuid = uuid.UUID(pin_channel_raw)
        except (ValueError, TypeError):
            pin_channel_uuid = None
    envelope = await _do_state_poll(
        tool_name=resolved,
        display_label=req.display_label or (patched_pin.get("envelope") or {}).get("display_label") or "",
        poll_cfg=poll_cfg,
        widget_config=merged_config,
        bot_id=pin_bot_id,
        channel_id=pin_channel_uuid,
    )
    if envelope is None:
        return WidgetActionResponse(ok=True, envelope=None, api_response=patched_pin)

    logger.info(
        "widget_config dispatch: dashboard_pin=%s tool=%s patch=%s merged=%s",
        req.dashboard_pin_id, resolved, req.config, merged_config,
    )
    return WidgetActionResponse(ok=True, envelope=envelope.compact_dict(), api_response=patched_pin)
