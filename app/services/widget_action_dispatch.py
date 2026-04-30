"""Dispatch runtime for interactive widget actions."""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3 as _sqlite3
import uuid

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
from app.agent.tool_dispatch import (
    ToolResultEnvelope,
    _build_default_envelope,
    _build_envelope_from_optin,
)
from app.schemas.widget_actions import WidgetActionRequest, WidgetActionResponse
from app.services.native_app_widgets import (
    build_envelope_for_native_instance,
    dispatch_native_widget_action,
    get_native_widget_instance_for_pin,
    get_widget_instance,
)
from app.services.widget_action_state_poll import (
    _do_state_poll,
    invalidate_poll_cache_for,
)
from app.services.widget_templates import apply_widget_template, get_state_poll_config
from app.tools.mcp import call_mcp_tool, is_mcp_tool
from app.tools.registry import call_local_tool, is_local_tool

logger = logging.getLogger(__name__)

_API_ALLOWLIST = [
    "/api/v1/admin/tasks",
    "/api/v1/channels",
]


def _resolve_tool_name(name: str) -> str:
    from app.services.tool_execution import resolve_tool_name

    return resolve_tool_name(name)


def _classify_domain_error(exc: BaseException) -> str:
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
    return "internal"


async def dispatch_widget_action(
    req: WidgetActionRequest,
    db: AsyncSession,
    *,
    auth: object,
) -> WidgetActionResponse:
    from app.services.widget_action_auth import authorize_widget_action_request

    await authorize_widget_action_request(db, auth, req)

    if req.dispatch == "tool":
        return await _dispatch_tool(req, db)
    if req.dispatch == "api":
        return await _dispatch_api(req)
    if req.dispatch == "widget_config":
        return await _dispatch_widget_config(req, db)
    if req.dispatch in ("db_query", "db_exec"):
        return await _dispatch_db(req, db)
    if req.dispatch == "widget_handler":
        return await _dispatch_widget_handler(req, db)
    if req.dispatch == "native_widget":
        return await _dispatch_native_widget(req, db)
    raise ValidationError(f"Unknown dispatch type: {req.dispatch}")


async def _dispatch_tool(req: WidgetActionRequest, db: AsyncSession) -> WidgetActionResponse:
    if not req.tool:
        return WidgetActionResponse(ok=False, error="Missing 'tool' field for tool dispatch")

    name = req.tool
    args_str = json.dumps(req.args) if req.args else "{}"
    resolved_name = _resolve_tool_name(name)

    result: str | None = None
    error_msg: str | None = None
    pin = None
    if req.dashboard_pin_id is not None:
        from app.services.dashboard_pins import get_pin

        try:
            pin = await get_pin(db, req.dashboard_pin_id)
        except Exception:
            logger.warning(
                "Widget action pin lookup failed before tool dispatch: pin=%s",
                req.dashboard_pin_id,
                exc_info=True,
            )

    effective_bot_id = req.bot_id or (getattr(pin, "source_bot_id", None) if pin is not None else None)
    effective_channel_id = req.channel_id or (getattr(pin, "source_channel_id", None) if pin is not None else None)

    policy_response = await _check_widget_tool_policy(
        req,
        resolved_name=resolved_name,
        effective_bot_id=effective_bot_id,
    )
    if policy_response is not None:
        return policy_response

    from app.agent.context import current_bot_id, current_channel_id

    bot_token = current_bot_id.set(str(effective_bot_id)) if effective_bot_id else None
    channel_token = current_channel_id.set(effective_channel_id) if effective_channel_id else None
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

    envelope = _build_result_envelope(
        resolved_name,
        result,
        req.widget_config,
        cap_body=False,
    )

    logger.info(
        "Widget action: tool=%s resolved=%s args=%s channel=%s result_preview=%.200s",
        name,
        resolved_name,
        args_str,
        req.channel_id,
        result or "",
    )

    pin_response = await _refresh_dashboard_pin_after_tool_action(req, db, pin)
    if pin_response is not None:
        return pin_response

    inline_response = await _refresh_inline_action_tool_if_possible(req, resolved_name)
    if inline_response is not None:
        return inline_response

    return WidgetActionResponse(ok=True, envelope=envelope.compact_dict())


async def _check_widget_tool_policy(
    req: WidgetActionRequest,
    *,
    resolved_name: str,
    effective_bot_id: str | uuid.UUID | None,
) -> WidgetActionResponse | None:
    try:
        if is_local_tool(resolved_name):
            from app.tools.registry import get_tool_execution_policy, get_tool_safety_tier

            execution_policy = get_tool_execution_policy(resolved_name)
            if execution_policy != "normal":
                from app.services.machine_control import validate_current_execution_policy

                resolution = await validate_current_execution_policy(execution_policy)
                if not resolution.allowed:
                    return WidgetActionResponse(
                        ok=False,
                        error=resolution.reason or "This tool is not available from widget actions.",
                        error_kind="forbidden",
                    )

            safety_tier = get_tool_safety_tier(resolved_name)
            if effective_bot_id:
                return await _tool_policy_decision_response(
                    req,
                    resolved_name=resolved_name,
                    effective_bot_id=effective_bot_id,
                )
            if safety_tier in {"exec_capable", "control_plane"}:
                return WidgetActionResponse(
                    ok=False,
                    error="High-privilege widget actions require bot context.",
                    error_kind="forbidden",
                )
        elif is_mcp_tool(resolved_name) and effective_bot_id:
            return await _tool_policy_decision_response(
                req,
                resolved_name=resolved_name,
                effective_bot_id=effective_bot_id,
            )
    except Exception:
        logger.exception("Widget action policy check failed for %s", resolved_name)
        return WidgetActionResponse(
            ok=False,
            error="Policy evaluation error.",
            error_kind="internal",
        )
    return None


async def _tool_policy_decision_response(
    req: WidgetActionRequest,
    *,
    resolved_name: str,
    effective_bot_id: str | uuid.UUID,
) -> WidgetActionResponse | None:
    from app.agent.tool_dispatch import _check_tool_policy

    correlation_id = str(req.source_record_id or req.dashboard_pin_id or uuid.uuid4())
    decision = await _check_tool_policy(
        str(effective_bot_id),
        resolved_name,
        req.args or {},
        correlation_id=correlation_id,
    )
    if decision is None:
        return None
    if decision.action == "deny":
        return WidgetActionResponse(
            ok=False,
            error=f"Denied by policy: {decision.reason or '(no reason)'}",
            error_kind="forbidden",
        )
    if decision.action == "require_approval":
        return WidgetActionResponse(
            ok=False,
            error=decision.reason or "This tool requires approval before it can run.",
            error_kind="conflict",
        )
    return None


async def _refresh_dashboard_pin_after_tool_action(
    req: WidgetActionRequest,
    db: AsyncSession,
    pin,
) -> WidgetActionResponse | None:
    if req.dashboard_pin_id is None:
        return None

    from app.services.dashboard_pins import get_pin, update_pin_envelope

    if pin is None:
        try:
            pin = await get_pin(db, req.dashboard_pin_id)
        except Exception:
            logger.warning(
                "Widget action pin lookup failed: pin=%s",
                req.dashboard_pin_id,
                exc_info=True,
            )
    if pin is None:
        return None

    pin_tool_name = _resolve_tool_name(pin.tool_name)
    pin_poll_cfg = get_state_poll_config(pin_tool_name)
    if not pin_poll_cfg:
        return None

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
    if polled is None:
        return WidgetActionResponse(ok=True, envelope=None)

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


async def _refresh_inline_action_tool_if_possible(
    req: WidgetActionRequest,
    resolved_name: str,
) -> WidgetActionResponse | None:
    poll_cfg = get_state_poll_config(resolved_name)
    if not poll_cfg:
        return None

    invalidate_poll_cache_for(poll_cfg)
    if not req.display_label:
        return None

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
    return None


async def _dispatch_api(req: WidgetActionRequest) -> WidgetActionResponse:
    if not req.endpoint:
        return WidgetActionResponse(ok=False, error="Missing 'endpoint' field for API dispatch")
    if not any(req.endpoint.startswith(prefix) for prefix in _API_ALLOWLIST):
        return WidgetActionResponse(
            ok=False,
            error=f"Endpoint '{req.endpoint}' is not in the widget action allowlist",
        )

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
    if not req.dashboard_pin_id:
        return WidgetActionResponse(ok=False, error="db_query/db_exec requires dashboard_pin_id")
    if not req.sql:
        return WidgetActionResponse(ok=False, error="db_query/db_exec requires sql")

    from app.services.dashboard_pins import get_pin
    from app.services.widget_db import (
        acquire_db,
        install_widget_sql_authorizer,
        resolve_db_path,
    )

    try:
        pin = await get_pin(db, req.dashboard_pin_id)
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
        if manifest is not None and manifest.db is not None:
            db_config = manifest.db
            try:
                async with acquire_db(db_path, db_config) as conn:
                    cursor = conn.execute(sql, params)
                    rows = [dict(row) for row in cursor.fetchall()]
            except Exception as exc:
                return WidgetActionResponse(ok=False, error=f"db_query failed: {exc}")
            return WidgetActionResponse(ok=True, db_result={"rows": rows})

        def _query() -> list[dict]:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = _sqlite3.connect(str(db_path), check_same_thread=False)
            conn.row_factory = _sqlite3.Row
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                install_widget_sql_authorizer(conn)
                cursor = conn.execute(sql, params)
                return [dict(row) for row in cursor.fetchall()]
            finally:
                conn.close()

        try:
            rows = _query()
        except Exception as exc:
            return WidgetActionResponse(ok=False, error=f"db_query failed: {exc}")
        return WidgetActionResponse(ok=True, db_result={"rows": rows})

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
            result = _exec(conn)
    except Exception as exc:
        return WidgetActionResponse(ok=False, error=f"db_exec failed: {exc}")
    return WidgetActionResponse(ok=True, db_result=result)


def _load_pin_manifest_safely(pin):
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


async def _dispatch_widget_handler(
    req: WidgetActionRequest,
    db: AsyncSession,
) -> WidgetActionResponse:
    if not req.dashboard_pin_id:
        return WidgetActionResponse(ok=False, error="widget_handler requires dashboard_pin_id")
    if not req.handler:
        return WidgetActionResponse(ok=False, error="widget_handler requires 'handler' field")

    from app.services.dashboard_pins import get_pin
    from app.services.widget_py import invoke_action

    try:
        pin = await get_pin(db, req.dashboard_pin_id)
    except DomainError as exc:
        return WidgetActionResponse(
            ok=False,
            error=str(exc.detail),
            error_kind=_classify_domain_error(exc),
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
            ok=False,
            error=f"handler {req.handler!r} timed out",
            error_kind="timeout",
        )
    except Exception as exc:
        logger.exception("widget_handler %s failed", req.handler)
        return WidgetActionResponse(
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
            error_kind="internal",
        )

    logger.info("widget_handler dispatch: pin=%s handler=%s", req.dashboard_pin_id, req.handler)
    return WidgetActionResponse(ok=True, result=result)


async def _dispatch_native_widget(
    req: WidgetActionRequest,
    db: AsyncSession,
) -> WidgetActionResponse:
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
        except DomainError as exc:
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
            ok=False,
            error="Native widget instance not found",
            error_kind="not_found",
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
    except DomainError as exc:
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
        instance.id,
        req.action,
        req.dashboard_pin_id,
    )
    return WidgetActionResponse(ok=True, result=result, envelope=envelope)


def _build_result_envelope(
    tool_name: str,
    raw_result: str,
    widget_config: dict | None = None,
    *,
    cap_body: bool = True,
) -> ToolResultEnvelope:
    try:
        parsed = json.loads(raw_result)
        if isinstance(parsed, dict) and "_envelope" in parsed:
            return _build_envelope_from_optin(
                parsed["_envelope"],
                raw_result,
                cap_body=cap_body,
            )
    except (json.JSONDecodeError, TypeError):
        pass

    widget_env = apply_widget_template(tool_name, raw_result, widget_config)
    if widget_env is not None:
        return widget_env
    return _build_default_envelope(raw_result, cap_body=cap_body)


async def _dispatch_widget_config(req: WidgetActionRequest, db: AsyncSession | None = None) -> WidgetActionResponse:
    if req.config is None:
        return WidgetActionResponse(ok=False, error="Missing 'config' for widget_config dispatch")
    if req.dashboard_pin_id is None:
        return WidgetActionResponse(ok=False, error="Missing 'dashboard_pin_id' for widget_config dispatch")

    from app.services.dashboard_pins import apply_dashboard_pin_config_patch

    try:
        if db is not None:
            patched_pin = await apply_dashboard_pin_config_patch(
                db,
                req.dashboard_pin_id,
                req.config,
                merge=True,
            )
        else:
            from app.db.engine import async_session

            async with async_session() as session:
                patched_pin = await apply_dashboard_pin_config_patch(
                    session,
                    req.dashboard_pin_id,
                    req.config,
                    merge=True,
                )
    except DomainError as exc:
        return WidgetActionResponse(
            ok=False,
            error=f"Pin patch failed: {exc.detail}",
            error_kind=_classify_domain_error(exc),
        )
    except Exception as exc:
        return WidgetActionResponse(
            ok=False,
            error=f"Pin patch failed: {exc}",
            error_kind="internal",
        )

    merged_config = patched_pin.get("widget_config") or {}
    tool_name = patched_pin.get("tool_name", "")
    resolved = _resolve_tool_name(tool_name)

    poll_cfg = get_state_poll_config(resolved)
    if not poll_cfg:
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
        req.dashboard_pin_id,
        resolved,
        req.config,
        merged_config,
    )
    return WidgetActionResponse(ok=True, envelope=envelope.compact_dict(), api_response=patched_pin)
