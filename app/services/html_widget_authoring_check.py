"""Shared authoring diagnostics for standalone HTML widgets."""
from __future__ import annotations

import json
import time
from typing import Any

from app.services.widget_health import check_envelope_health
from app.tools.local.preview_widget import preview_widget


def _phase(name: str, status: str, message: str, *, duration_ms: int | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"name": name, "status": status, "message": message}
    if duration_ms is not None:
        out["duration_ms"] = duration_ms
    return out


def _issue(phase: str, severity: str, message: str, *, kind: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "phase": phase,
        "severity": severity,
        "message": message,
    }
    if kind:
        out["kind"] = kind
    return out


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
        return "HTML widget authoring check passed."
    if readiness == "needs_runtime":
        return "Static checks passed, but runtime smoke did not produce a reliable browser result."
    if issues:
        first = issues[0]
        suffix = f" (+{len(issues) - 1} more)" if len(issues) > 1 else ""
        return f"{first.get('message', 'HTML widget authoring issue')}{suffix}"
    return "HTML widget authoring check needs attention."


def _target_ref(*, library_ref: str | None, path: str | None) -> str:
    if library_ref and library_ref.strip():
        return f"html-authoring:library:{library_ref.strip()}"
    if path and path.strip():
        return f"html-authoring:path:{path.strip()}"
    return "html-authoring:inline"


def _next_actions(
    *,
    readiness: str,
    library_ref: str | None,
    path: str | None,
    display_label: str,
    display_mode: str,
    runtime: str | None,
) -> list[dict[str, Any]]:
    if readiness != "ready":
        return []
    args: dict[str, Any] = {}
    if library_ref and library_ref.strip():
        args["widget"] = library_ref.strip()
        args["source_kind"] = "library"
        action = "pin_widget"
        hint = "Pin the checked library widget, then call check_widget on the returned pin id."
    elif path and path.strip():
        args["path"] = path.strip()
        action = "emit_html_widget"
        hint = "Emit the checked path widget for the user to pin, then check the resulting pin."
    else:
        action = "emit_html_widget"
        hint = "Emit the checked inline widget for the user to pin. Prefer a library bundle for reusable widgets."
    if display_label.strip():
        args["display_label"] = display_label.strip()
    if display_mode and display_mode != "inline":
        args["display_mode"] = display_mode
    if runtime and str(runtime).strip().lower() == "react":
        args["runtime"] = "react"
    return [{"tool": action, "args": args, "hint": hint}]


async def run_html_widget_authoring_check(
    *,
    html: str | None = None,
    path: str | None = None,
    library_ref: str | None = None,
    js: str = "",
    css: str = "",
    display_label: str = "",
    extra_csp: dict | None = None,
    display_mode: str = "inline",
    runtime: str | None = None,
    include_runtime: bool = False,
    include_screenshot: bool = False,
) -> dict[str, Any]:
    phases: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    envelope: dict[str, Any] | None = None
    artifacts: dict[str, Any] = {}

    started = time.monotonic()
    preview_raw = await preview_widget(
        html=html,
        path=path,
        library_ref=library_ref,
        js=js,
        css=css,
        display_label=display_label,
        extra_csp=extra_csp,
        display_mode=display_mode,
        runtime=runtime,
    )
    try:
        preview = json.loads(preview_raw)
    except json.JSONDecodeError as exc:
        preview = {
            "ok": False,
            "errors": [{"phase": "preview", "severity": "error", "message": str(exc)}],
        }

    if preview.get("ok"):
        envelope = preview.get("envelope")
        phases.append(_phase(
            "preview",
            "healthy",
            "Preview envelope rendered.",
            duration_ms=int((time.monotonic() - started) * 1000),
        ))
    else:
        for item in preview.get("errors") or []:
            issues.append(_issue(
                str(item.get("phase") or "preview"),
                str(item.get("severity") or "error"),
                str(item.get("message") or "Preview failed."),
                kind=item.get("kind"),
            ))
        phases.append(_phase(
            "preview",
            "failing",
            "Preview failed.",
            duration_ms=int((time.monotonic() - started) * 1000),
        ))

    if envelope is not None:
        health = await check_envelope_health(
            envelope,
            target_ref=_target_ref(library_ref=library_ref, path=path),
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
        "next_actions": _next_actions(
            readiness=readiness,
            library_ref=library_ref,
            path=path,
            display_label=display_label,
            display_mode=display_mode,
            runtime=runtime,
        ),
    }
