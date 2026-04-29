"""Shared widget authoring diagnostic pipeline."""
from __future__ import annotations

import time
from typing import Any

import yaml

from app.services.widget_health import check_envelope_health
from app.services.widget_package_loader import (
    discard_preview_module,
    load_preview_module,
    rewrite_refs_for_preview,
)
from app.services.widget_package_validation import validate_package
from app.services.widget_preview import render_preview_envelope


def _phase(name: str, status: str, message: str, *, duration_ms: int | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"name": name, "status": status, "message": message}
    if duration_ms is not None:
        out["duration_ms"] = duration_ms
    return out


def _issue(phase: str, severity: str, message: str, *, line: int | None = None, kind: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "phase": phase,
        "severity": severity,
        "message": message,
    }
    if line is not None:
        out["line"] = line
    if kind:
        out["kind"] = kind
    return out


def _validation_issue(issue: Any) -> dict[str, Any]:
    return _issue(
        str(getattr(issue, "phase", "validation")),
        str(getattr(issue, "severity", "error") or "error"),
        str(getattr(issue, "message", "Validation issue")),
        line=getattr(issue, "line", None),
    )


def _readiness(phases: list[dict[str, Any]], issues: list[dict[str, Any]], *, runtime_requested: bool) -> str:
    if any(issue.get("severity") == "error" for issue in issues):
        return "blocked"
    if any(issue.get("severity") == "warning" for issue in issues):
        return "needs_attention"
    if runtime_requested and not any(
        phase.get("name") == "browser_smoke" and phase.get("status") == "healthy"
        for phase in phases
    ):
        return "needs_runtime"
    return "ready"


def _summary(readiness: str, issues: list[dict[str, Any]]) -> str:
    if readiness == "ready":
        return "Widget authoring check passed."
    if readiness == "needs_runtime":
        return "Static checks passed, but runtime smoke did not produce a reliable browser result."
    if issues:
        first = issues[0]
        suffix = f" (+{len(issues) - 1} more)" if len(issues) > 1 else ""
        return f"{first.get('message', 'Widget authoring issue')}{suffix}"
    return "Widget authoring check needs attention."


async def run_widget_authoring_check(
    *,
    yaml_template: str,
    python_code: str | None = None,
    sample_payload: dict[str, Any] | None = None,
    widget_config: dict[str, Any] | None = None,
    tool_name: str | None = None,
    source_bot_id: str | None = None,
    source_channel_id: str | None = None,
    include_runtime: bool = False,
    include_screenshot: bool = False,
) -> dict[str, Any]:
    phases: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    envelope: dict[str, Any] | None = None
    artifacts: dict[str, Any] = {}

    started = time.monotonic()
    result = validate_package(yaml_template, python_code)
    issues.extend(_validation_issue(issue) for issue in result.errors)
    issues.extend(_validation_issue(issue) for issue in result.warnings)
    phases.append(_phase(
        "validation",
        "failing" if result.errors else ("warning" if result.warnings else "healthy"),
        "Validation passed." if not result.errors and not result.warnings else f"Validation found {len(result.errors)} error(s) and {len(result.warnings)} warning(s).",
        duration_ms=int((time.monotonic() - started) * 1000),
    ))
    if result.errors:
        readiness = _readiness(phases, issues, runtime_requested=include_runtime)
        return {
            "ok": False,
            "readiness": readiness,
            "summary": _summary(readiness, issues),
            "phases": phases,
            "issues": issues,
            "envelope": None,
            "artifacts": artifacts,
        }

    widget_def = result.template or yaml.safe_load(yaml_template) or {}
    preview_mod_name: str | None = None
    started = time.monotonic()
    try:
        if python_code and python_code.strip():
            _, preview_mod_name = load_preview_module(python_code)
        rewritten = rewrite_refs_for_preview(widget_def, preview_mod_name)
        rendered = render_preview_envelope(
            rewritten,
            tool_name=tool_name or "",
            sample_payload=sample_payload or {},
            widget_config=widget_config,
            source_bot_id=source_bot_id,
            source_channel_id=source_channel_id,
        )
        envelope = rendered.model_dump(mode="json", exclude_none=True)
        phases.append(_phase(
            "preview",
            "healthy",
            "Preview envelope rendered.",
            duration_ms=int((time.monotonic() - started) * 1000),
        ))
    except Exception as exc:  # noqa: BLE001 - report as authoring feedback
        issues.append(_issue("preview", "error", str(exc), kind="preview_exception"))
        phases.append(_phase(
            "preview",
            "failing",
            f"Preview render failed: {exc}",
            duration_ms=int((time.monotonic() - started) * 1000),
        ))
    finally:
        discard_preview_module(preview_mod_name)

    if envelope is not None:
        health = await check_envelope_health(
            envelope,
            target_ref=f"authoring:{tool_name or 'draft'}",
            include_browser=include_runtime,
            include_screenshot=include_screenshot,
        )
        phases.extend(health.get("phases") or [])
        issues.extend(health.get("issues") or [])
        if isinstance(health.get("artifacts"), dict):
            artifacts.update(health["artifacts"])

    readiness = _readiness(phases, issues, runtime_requested=include_runtime)
    return {
        "ok": readiness == "ready",
        "readiness": readiness,
        "summary": _summary(readiness, issues),
        "phases": phases,
        "issues": issues,
        "envelope": envelope,
        "artifacts": artifacts,
    }
