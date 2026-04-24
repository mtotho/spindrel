"""Widget presets, suites, previews, and recent-call render.

These endpoints all feed the "Add widget" UX surface: the user picks a
preset / suite / recent tool-call, the server renders an envelope, the
client either previews or pins it.
"""
from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_scopes
from app.services.dashboard_pins import (
    DEFAULT_DASHBOARD_KEY,
    create_pin,
    serialize_pin,
)


logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Recent widget-producing tool calls — used by the "Add widget" sheet's
# "Recent calls" tab. Surfaces tool calls whose result is a renderable
# widget envelope (components, html-interactive, html, etc.) so users can
# pin them straight to a dashboard without first pinning to a channel's
# OmniPanel rail.
# ---------------------------------------------------------------------------
_WIDGET_CONTENT_TYPES = {
    "application/vnd.spindrel.components+json",
    "application/vnd.spindrel.html+interactive",
    "application/vnd.spindrel.diff+text",
    "application/vnd.spindrel.file-listing+json",
    "text/html",
}


class PreviewForToolRequest(BaseModel):
    tool_name: str
    tool_args: dict | None = None
    widget_config: dict | None = None
    source_bot_id: str | None = None
    source_channel_id: uuid.UUID | None = None


class WidgetPresetPreviewRequest(BaseModel):
    config: dict | None = None
    source_bot_id: str | None = None
    source_channel_id: uuid.UUID | None = None


class WidgetPresetBindingOptionsRequest(BaseModel):
    source_id: str | None = None
    source_bot_id: str | None = None
    source_channel_id: uuid.UUID | None = None


class PinWidgetPresetRequest(BaseModel):
    dashboard_key: str | None = None
    config: dict | None = None
    source_bot_id: str | None = None
    source_channel_id: uuid.UUID | None = None
    display_label: str | None = None


class PinSuiteRequest(BaseModel):
    suite_id: str
    dashboard_key: str
    source_bot_id: str | None = None
    source_channel_id: uuid.UUID | None = None
    members: list[str] | None = None


@router.get(
    "/recent-calls",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def list_recent_widget_calls(
    channel_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List recent tool calls that can be rendered as a widget.

    A call qualifies if either:
    - the tool's stored ``result`` already IS an envelope (``_envelope``
      opt-in tools like ``emit_html_widget``), OR
    - a registered widget template for the tool produces one when applied
      to the stored ``result``.

    The rendered envelope is returned in each row so the UI can pin it
    directly without a second round-trip through the preview endpoints.
    """
    from sqlalchemy import select
    from app.db.models import Session as SessionModel, ToolCall, Channel
    from app.services.widget_templates import apply_widget_template

    # Pull more than `limit` up front since we filter out non-widget
    # envelopes after rendering — otherwise a page full of text results
    # would leave the user with an empty list.
    over_limit = limit * 4

    stmt = (
        select(ToolCall, SessionModel.channel_id, Channel.name)
        .join(SessionModel, SessionModel.id == ToolCall.session_id, isouter=True)
        .join(Channel, Channel.id == SessionModel.channel_id, isouter=True)
        .where(ToolCall.status == "done")
        .where(ToolCall.result.isnot(None))
        .order_by(ToolCall.created_at.desc())
    )
    if channel_id is not None:
        stmt = stmt.where(SessionModel.channel_id == channel_id)
    stmt = stmt.limit(over_limit)

    rows = (await db.execute(stmt)).all()

    out: list[dict] = []
    seen_identities: set[str] = set()
    for tool_call, row_channel_id, row_channel_name in rows:
        if len(out) >= limit:
            break
        raw = tool_call.result
        if not raw:
            continue

        envelope: dict | None = None

        # Path 1: template-rendered envelope (works for every tool with a
        # registered .widgets.yaml template). Cheap — dict lookup + a JSON
        # parse that succeeds fast on the 95% of tools that return JSON.
        try:
            rendered = apply_widget_template(tool_call.tool_name, raw)
        except Exception:
            rendered = None
        if rendered is not None:
            envelope = rendered.compact_dict()

        # Path 2: tool-shipped envelope via the ``_envelope`` opt-in wrapper
        # (``emit_html_widget`` and any bot-authored widget tool). Stored
        # shape is ``{"_envelope": {...content_type, body, ...}, "llm": "..."}``
        # — we unwrap and accept if the inner envelope is a widget type.
        if envelope is None:
            try:
                parsed = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if not isinstance(parsed, dict):
                continue
            inner = parsed.get("_envelope")
            if isinstance(inner, dict) and inner.get("content_type") in _WIDGET_CONTENT_TYPES:
                envelope = inner
            elif parsed.get("content_type") in _WIDGET_CONTENT_TYPES:
                # Legacy shape — result itself IS the envelope.
                envelope = parsed
            else:
                continue

        # De-dupe: tool_name + first 120 chars of body is a good-enough
        # identity for "is this the same widget I already saw 3 calls up".
        body = envelope.get("body")
        body_str = body if isinstance(body, str) else json.dumps(body or "")
        identity = f"{tool_call.tool_name}::{body_str[:120]}"
        if identity in seen_identities:
            continue
        seen_identities.add(identity)
        out.append({
            "id": str(tool_call.id),
            "tool_name": tool_call.tool_name,
            "bot_id": tool_call.bot_id,
            "channel_id": str(row_channel_id) if row_channel_id else None,
            "channel_name": row_channel_name,
            "tool_args": tool_call.arguments or {},
            "envelope": envelope,
            "display_label": envelope.get("display_label"),
            "created_at": tool_call.created_at.isoformat() if tool_call.created_at else None,
        })
    return {"calls": out}


@router.post(
    "/preview-for-tool",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def preview_dashboard_widget_for_tool(
    body: PreviewForToolRequest,
    db: AsyncSession = Depends(get_db),
):
    from app.services.tool_execution import execute_tool_with_context
    from app.services.widget_preview import preview_active_widget_for_tool

    parsed_result, _raw = await execute_tool_with_context(
        body.tool_name,
        body.tool_args or {},
        bot_id=body.source_bot_id,
        channel_id=str(body.source_channel_id) if body.source_channel_id else None,
    )
    payload = (
        parsed_result
        if isinstance(parsed_result, dict)
        else {"result": parsed_result}
    )
    preview = await preview_active_widget_for_tool(
        db,
        tool_name=body.tool_name,
        sample_payload=payload,
        widget_config=body.widget_config,
        source_bot_id=body.source_bot_id,
        source_channel_id=str(body.source_channel_id) if body.source_channel_id else None,
    )
    return preview.model_dump(mode="json")


@router.get(
    "/presets",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def list_dashboard_widget_presets(
    include_binding_options: bool = Query(default=False),
    source_bot_id: str | None = Query(default=None),
    source_channel_id: uuid.UUID | None = Query(default=None),
):
    from app.services.widget_presets import (
        list_widget_presets,
        resolve_preset_binding_options,
        serialize_widget_preset,
    )

    presets = []
    for preset in list_widget_presets():
        row = serialize_widget_preset(preset)
        if include_binding_options:
            options_by_source, errors_by_source = await resolve_preset_binding_options(
                preset,
                source_bot_id=source_bot_id,
                source_channel_id=str(source_channel_id) if source_channel_id else None,
            )
            row["resolved_binding_options"] = options_by_source
            row["binding_source_errors"] = errors_by_source
        presets.append(row)
    return {"presets": presets}


@router.get(
    "/presets/{preset_id}",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def get_dashboard_widget_preset(
    preset_id: str,
):
    from app.services.widget_presets import get_widget_preset, serialize_widget_preset

    return serialize_widget_preset(get_widget_preset(preset_id))


@router.get(
    "/presets/{preset_id}/binding-options",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def get_dashboard_widget_preset_binding_options_query(
    preset_id: str,
    source_id: str = Query(..., description="Binding source id from the preset manifest."),
    source_bot_id: str | None = Query(default=None),
    source_channel_id: uuid.UUID | None = Query(default=None),
):
    from app.services.widget_presets import list_binding_options

    options = await list_binding_options(
        preset_id=preset_id,
        source_id=source_id,
        source_bot_id=source_bot_id,
        source_channel_id=str(source_channel_id) if source_channel_id else None,
    )
    return {"options": options}


@router.post(
    "/presets/{preset_id}/binding-options",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def get_dashboard_widget_preset_binding_options_body(
    preset_id: str,
    body: WidgetPresetBindingOptionsRequest,
):
    from app.services.widget_presets import list_binding_options

    if not body.source_id:
        raise HTTPException(400, "source_id is required")
    options = await list_binding_options(
        preset_id=preset_id,
        source_id=body.source_id,
        source_bot_id=body.source_bot_id,
        source_channel_id=str(body.source_channel_id) if body.source_channel_id else None,
    )
    return {"options": options}


@router.post(
    "/presets/{preset_id}/binding-options/{source_id}",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def get_dashboard_widget_preset_binding_options(
    preset_id: str,
    source_id: str,
    body: WidgetPresetBindingOptionsRequest,
):
    from app.services.widget_presets import list_binding_options

    options = await list_binding_options(
        preset_id=preset_id,
        source_id=source_id,
        source_bot_id=body.source_bot_id,
        source_channel_id=str(body.source_channel_id) if body.source_channel_id else None,
    )
    return {"options": options}


@router.post(
    "/presets/{preset_id}/preview",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def preview_dashboard_widget_preset(
    preset_id: str,
    body: WidgetPresetPreviewRequest,
    db: AsyncSession = Depends(get_db),
):
    from app.services.widget_presets import preview_envelope_to_dict, preview_widget_preset

    preview, resolved_config, _tool_args = await preview_widget_preset(
        db,
        preset_id=preset_id,
        config=body.config,
        source_bot_id=body.source_bot_id,
        source_channel_id=str(body.source_channel_id) if body.source_channel_id else None,
    )
    return {
        "ok": preview.ok,
        "envelope": preview_envelope_to_dict(preview.envelope),
        "widget_contract": preview.widget_contract,
        "config_schema": preview.config_schema,
        "errors": [err.model_dump(mode="json") for err in preview.errors],
        "config": resolved_config,
    }


@router.post(
    "/presets/{preset_id}/pin",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def pin_dashboard_widget_preset(
    preset_id: str,
    body: PinWidgetPresetRequest,
    db: AsyncSession = Depends(get_db),
):
    from app.services.widget_presets import (
        get_widget_preset,
        preview_envelope_to_dict,
        preview_widget_preset,
    )

    preview, resolved_config, tool_args = await preview_widget_preset(
        db,
        preset_id=preset_id,
        config=body.config,
        source_bot_id=body.source_bot_id,
        source_channel_id=str(body.source_channel_id) if body.source_channel_id else None,
    )
    if not preview.ok or preview.envelope is None:
        raise HTTPException(400, f"Preset '{preset_id}' preview failed")

    preset = get_widget_preset(preset_id)
    tool_name = preset.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name.strip():
        raise HTTPException(400, f"Preset '{preset_id}' missing tool_name")

    envelope = preview_envelope_to_dict(preview.envelope)
    if isinstance(envelope, dict):
        envelope["source_instantiation_kind"] = "preset"
        envelope["source_preset_id"] = preset_id
    widget_origin = {
        "definition_kind": "tool_widget",
        "instantiation_kind": "preset",
        "tool_name": tool_name,
        "preset_id": preset_id,
    }
    tool_family = preset.get("tool_family")
    if isinstance(tool_family, str) and tool_family.strip():
        widget_origin["tool_family"] = tool_family.strip()
    template_id = envelope.get("template_id") if isinstance(envelope, dict) else None
    if isinstance(template_id, str) and template_id.strip():
        widget_origin["template_id"] = template_id.strip()

    pin = await create_pin(
        db,
        source_kind="adhoc",
        tool_name=tool_name,
        envelope=envelope,
        source_channel_id=body.source_channel_id,
        source_bot_id=body.source_bot_id,
        tool_args=tool_args,
        widget_config=resolved_config,
        widget_origin=widget_origin,
        display_label=body.display_label,
        dashboard_key=body.dashboard_key or DEFAULT_DASHBOARD_KEY,
    )
    return serialize_pin(pin)


@router.get(
    "/suites",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def list_suites():
    """List every discoverable widget suite on this server.

    Each suite is a widget folder under ``app/tools/local/widgets/`` or
    ``integrations/*/widgets/`` that contains a ``suite.yaml``. Members
    are the bundle slugs that declare ``db.shared: <suite_id>`` in their
    own ``widget.yaml``.
    """
    from app.services.widget_suite import scan_suites

    out = []
    for s in scan_suites():
        out.append({
            "suite_id": s.suite_id,
            "name": s.name,
            "description": s.description,
            "members": s.members,
            "schema_version": s.schema_version,
        })
    return {"suites": out}


@router.post(
    "/dashboard/pins/suite",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def pin_suite_endpoint(
    body: PinSuiteRequest,
    db: AsyncSession = Depends(get_db),
):
    """Atomically pin every member of a suite onto a dashboard.

    Layout: each member appends below the existing pins via the standard
    ``_default_grid_layout(position)`` helper — same behavior as pinning a
    single widget repeatedly. Users rearrange from there.
    """
    from app.services.dashboard_pins import create_suite_pins

    pins = await create_suite_pins(
        db,
        suite_id=body.suite_id,
        dashboard_key=body.dashboard_key,
        source_bot_id=body.source_bot_id,
        source_channel_id=body.source_channel_id,
        member_slugs=body.members,
    )
    return {
        "pins": [serialize_pin(p) for p in pins],
        "suite_id": body.suite_id,
        "dashboard_key": body.dashboard_key,
    }
