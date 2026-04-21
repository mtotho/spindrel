from __future__ import annotations

import copy
import json
import logging
from typing import Any

from pydantic import BaseModel
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WidgetTemplatePackage
from app.services.widget_package_loader import (
    discard_preview_module,
    load_preview_module,
    rewrite_refs_for_preview,
)
from app.services.widget_package_validation import validate_package
from app.services.widget_templates import _substitute, _substitute_string

logger = logging.getLogger(__name__)


class ValidationIssueOut(BaseModel):
    phase: str
    message: str
    line: int | None = None
    severity: str = "error"


class PreviewEnvelope(BaseModel):
    content_type: str
    body: str
    display: str
    display_label: str | None = None
    refreshable: bool = False
    refresh_interval_seconds: int | None = None
    source_bot_id: str | None = None
    source_channel_id: str | None = None


class PreviewOut(BaseModel):
    ok: bool
    envelope: PreviewEnvelope | None = None
    errors: list[ValidationIssueOut] = []


def render_preview_envelope(
    widget_def: dict[str, Any],
    *,
    tool_name: str,
    sample_payload: dict,
    widget_config: dict | None,
    source_bot_id: str | None = None,
    source_channel_id: str | None = None,
) -> PreviewEnvelope:
    from app.services.widget_templates import _apply_code_transform, _build_html_widget_body

    data = dict(sample_payload) if isinstance(sample_payload, dict) else {}
    default_config = widget_def.get("default_config") or {}
    merged_config = {**default_config, **(widget_config or {})}
    data_with_config = {**data, "config": merged_config}

    display_label = None
    raw_label = widget_def.get("display_label")
    if isinstance(raw_label, str):
        resolved = _substitute_string(raw_label, data_with_config)
        if isinstance(resolved, str) and resolved.strip():
            display_label = resolved.strip()

    state_poll = widget_def.get("state_poll") or {}
    interval = state_poll.get("refresh_interval_seconds")

    html_template = widget_def.get("html_template")
    if isinstance(html_template, dict) and isinstance(html_template.get("body"), str):
        body = _build_html_widget_body(html_template["body"], data)
        return PreviewEnvelope(
            content_type=widget_def.get(
                "content_type", "application/vnd.spindrel.html+interactive",
            ),
            body=body,
            display=widget_def.get("display", "inline"),
            display_label=display_label,
            refreshable=bool(widget_def.get("state_poll")),
            refresh_interval_seconds=int(interval) if interval else None,
            source_bot_id=source_bot_id,
            source_channel_id=source_channel_id,
        )

    template = widget_def.get("template") or {}
    filled = _substitute(copy.deepcopy(template), data_with_config)

    transform_ref = widget_def.get("transform")
    if transform_ref and isinstance(filled, dict):
        components = filled.get("components")
        if isinstance(components, list):
            filled["components"] = _apply_code_transform(transform_ref, data_with_config, components)

    return PreviewEnvelope(
        content_type=widget_def.get(
            "content_type", "application/vnd.spindrel.components+json",
        ),
        body=json.dumps(filled),
        display=widget_def.get("display", "inline"),
        display_label=display_label,
        refreshable=bool(widget_def.get("state_poll")),
        refresh_interval_seconds=int(interval) if interval else None,
        source_bot_id=source_bot_id,
        source_channel_id=source_channel_id,
    )


async def preview_active_widget_for_tool(
    db: AsyncSession,
    *,
    tool_name: str,
    sample_payload: dict | None,
    widget_config: dict | None,
    source_bot_id: str | None = None,
    source_channel_id: str | None = None,
) -> PreviewOut:
    pkg = (
        await db.execute(
            select(WidgetTemplatePackage).where(
                WidgetTemplatePackage.tool_name == tool_name,
                WidgetTemplatePackage.is_active.is_(True),
                WidgetTemplatePackage.is_orphaned.is_(False),
                WidgetTemplatePackage.is_invalid.is_(False),
            )
        )
    ).scalar_one_or_none()

    widget_def: dict[str, Any] | None = None
    preview_mod_name: str | None = None
    try:
        if pkg is not None:
            result = validate_package(pkg.yaml_template, pkg.python_code)
            if not result.ok:
                return PreviewOut(
                    ok=False,
                    errors=[
                        ValidationIssueOut(
                            phase=e.phase,
                            message=e.message,
                            line=e.line,
                            severity=e.severity,
                        )
                        for e in result.errors
                    ],
                )
            widget_def = result.template or yaml.safe_load(pkg.yaml_template) or {}
            if pkg.python_code and pkg.python_code.strip():
                _, preview_mod_name = load_preview_module(pkg.python_code)
            widget_def = rewrite_refs_for_preview(widget_def, preview_mod_name)
        else:
            from app.services.widget_templates import _widget_templates

            entry = _widget_templates.get(tool_name)
            if entry is None:
                bare = tool_name.split("-", 1)[1] if "-" in tool_name else None
                if bare:
                    entry = _widget_templates.get(bare)
            if entry is None:
                return PreviewOut(
                    ok=False,
                    errors=[
                        ValidationIssueOut(
                            phase="lookup",
                            message=f"No active widget template for tool '{tool_name}'",
                        )
                    ],
                )
            widget_def = {
                "content_type": entry.get("content_type"),
                "display": entry.get("display", "inline"),
                "display_label": entry.get("display_label"),
                "template": entry.get("template"),
                "html_template": (
                    {"body": entry.get("html_template_body")}
                    if entry.get("html_template_body")
                    else None
                ),
                "default_config": entry.get("default_config"),
                "transform": entry.get("transform"),
                "state_poll": entry.get("state_poll"),
            }

        envelope = render_preview_envelope(
            widget_def,
            tool_name=tool_name,
            sample_payload=sample_payload or {},
            widget_config=widget_config,
            source_bot_id=source_bot_id,
            source_channel_id=source_channel_id,
        )
    except Exception as exc:
        logger.warning("preview-for-tool failed for %s: %s", tool_name, exc, exc_info=True)
        return PreviewOut(
            ok=False,
            errors=[ValidationIssueOut(phase="python", message=str(exc))],
        )
    finally:
        discard_preview_module(preview_mod_name)

    return PreviewOut(ok=True, envelope=envelope)
