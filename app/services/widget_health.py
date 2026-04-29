"""Widget health checks and dashboard health summaries.

This service turns two existing low-level signals into a durable read model:
static widget metadata validation and the in-browser debug ring. Browser smoke
checks are opportunistic so widget health is useful in local/dev deployments
without making Playwright infrastructure a hard dependency.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import WidgetDashboardPin, WidgetHealthCheck
from app.services import widget_debug
from app.services.dashboard_pins import get_pin, list_pins, serialize_pin

logger = logging.getLogger(__name__)

STATUS_ORDER = {"healthy": 0, "unknown": 1, "warning": 2, "failing": 3}
INTERACTIVE_HTML = "application/vnd.spindrel.html+interactive"
NATIVE_APP = "application/vnd.spindrel.native-app+json"
COMPONENTS = "application/vnd.spindrel.components+json"
_MAX_ISSUES = 12
_MAX_MESSAGE = 500


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clip(value: object, limit: int = _MAX_MESSAGE) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _issue(
    phase: str,
    severity: str,
    message: str,
    *,
    kind: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "phase": phase,
        "severity": severity,
        "message": _clip(message),
    }
    if kind:
        item["kind"] = kind
    if evidence:
        item["evidence"] = evidence
    return item


def _phase(name: str, status: str, message: str, *, duration_ms: int | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": name,
        "status": status,
        "message": _clip(message),
    }
    if duration_ms is not None:
        out["duration_ms"] = duration_ms
    return out


def _overall_status(phases: list[dict[str, Any]], issues: list[dict[str, Any]]) -> str:
    if any(issue.get("severity") == "error" for issue in issues):
        return "failing"
    if any(issue.get("severity") == "warning" for issue in issues):
        return "warning"
    if any(phase.get("status") == "unknown" for phase in phases):
        return "unknown"
    return "healthy"


def _summary(status: str, issues: list[dict[str, Any]]) -> str:
    if status == "healthy":
        return "No widget health issues found."
    if not issues:
        return "Widget health could not be fully determined."
    first = issues[0]
    count = len(issues)
    suffix = f" (+{count - 1} more)" if count > 1 else ""
    return f"{first.get('message', 'Widget health issue')}{suffix}"


def _static_check(pin: WidgetDashboardPin | None, envelope: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    content_type = envelope.get("content_type")
    body = envelope.get("body")
    plain_body = envelope.get("plain_body")
    display_label = envelope.get("display_label") or (pin.display_label if pin else None)

    if not isinstance(content_type, str) or not content_type.strip():
        issues.append(_issue("static", "error", "Widget envelope is missing content_type.", kind="missing_content_type"))
    elif content_type not in {INTERACTIVE_HTML, NATIVE_APP, COMPONENTS, "text/html", "application/vnd.spindrel.diff+text", "application/vnd.spindrel.file-listing+json"}:
        issues.append(_issue("static", "warning", f"Widget content_type is uncommon: {content_type}.", kind="uncommon_content_type"))

    if not display_label:
        issues.append(_issue("static", "warning", "Widget has no display label; users may see a raw tool name.", kind="missing_label"))

    if content_type == INTERACTIVE_HTML:
        source_path = envelope.get("source_path")
        source_library_ref = envelope.get("source_library_ref")
        if not source_path and not source_library_ref and not isinstance(body, str):
            issues.append(_issue("static", "error", "Interactive HTML widget has no body, source path, or library ref.", kind="missing_html_source"))
        html = body if isinstance(body, str) else ""
        if "fetch(" in html and "spindrel.api" not in html and "spindrel.apiFetch" not in html:
            issues.append(_issue("static", "warning", "Widget appears to use raw fetch; prefer window.spindrel.api/apiFetch for authenticated calls.", kind="raw_fetch"))
        if "console.log" in html and "spindrel.log" not in html:
            issues.append(_issue("static", "warning", "Widget uses console.log without spindrel.log; bot inspection is easier with spindrel.log.", kind="console_log"))
        if envelope.get("runtime") == "react" and "text/spindrel-react" not in html and isinstance(body, str):
            issues.append(_issue("static", "warning", "React runtime widget body does not include a text/spindrel-react script block.", kind="react_script_missing"))

    if content_type != INTERACTIVE_HTML and isinstance(plain_body, str) and not plain_body.strip():
        issues.append(_issue("static", "warning", "Widget plain_body is empty; compact surfaces may have little fallback text.", kind="empty_plain_body"))

    status = "failing" if any(i["severity"] == "error" for i in issues) else ("warning" if issues else "healthy")
    message = "Static validation passed." if not issues else f"Static validation found {len(issues)} issue(s)."
    return _phase("static", status, message), issues


def _debug_events_check(pin_id: uuid.UUID | None) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, int]]:
    if pin_id is None:
        return _phase("debug_events", "unknown", "Draft widgets do not have a pinned debug event ring."), [], {}

    events = widget_debug.get_events(pin_id, limit=50)
    counts = dict(Counter(str(event.get("kind") or "unknown") for event in events))
    issues: list[dict[str, Any]] = []
    for event in events:
        if len(issues) >= _MAX_ISSUES:
            break
        kind = str(event.get("kind") or "unknown")
        if kind in {"error", "rejection"}:
            msg = event.get("message") or event.get("reason") or "Widget runtime error."
            evidence = {k: event.get(k) for k in ("line", "col", "src", "stack") if event.get(k) is not None}
            issues.append(_issue("debug_events", "error", _clip(msg), kind=kind, evidence=evidence or None))
        elif kind == "console" and str(event.get("level") or "").lower() == "error":
            args = event.get("args")
            msg = args[0] if isinstance(args, list) and args else "Widget logged console.error."
            issues.append(_issue("debug_events", "error", _clip(msg), kind="console_error"))
        elif kind in {"tool-call", "load-attachment", "load-asset"} and event.get("ok") is False:
            msg = event.get("error") or f"{kind} failed."
            evidence = {k: event.get(k) for k in ("tool", "status", "durationMs", "id") if event.get(k) is not None}
            issues.append(_issue("debug_events", "error", _clip(msg), kind=f"{kind}_failed", evidence=evidence or None))

    if issues:
        return _phase("debug_events", "failing", f"Debug ring has {len(issues)} runtime issue(s)."), issues, counts
    if not events:
        return _phase("debug_events", "unknown", "No browser debug events have been captured for this pin yet."), [], counts
    return _phase("debug_events", "healthy", f"Debug ring has {len(events)} event(s) and no failures."), [], counts


async def _browser_smoke_check(pin_id: uuid.UUID | None, *, include_browser: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not include_browser:
        return _phase("browser_smoke", "unknown", "Browser smoke check was not requested."), []
    if pin_id is None:
        return _phase("browser_smoke", "unknown", "Draft browser smoke checks require a pinned widget in v1."), []
    if not settings.BASE_URL.strip():
        return _phase("browser_smoke", "unknown", "BASE_URL is not configured, so the server cannot open the widget UI."), []

    started = time.monotonic()
    try:
        from playwright.async_api import async_playwright
        from scripts.screenshots.playwright_runtime import launch_async_browser
    except Exception as exc:  # pragma: no cover - depends on optional runtime import shape
        return _phase("browser_smoke", "unknown", f"Playwright is unavailable: {exc}"), []

    base_url = settings.BASE_URL.rstrip("/")
    route = f"{base_url}/widgets/pins/{pin_id}?widget_health_check=1"
    page_errors: list[str] = []
    console_errors: list[str] = []
    request_failures: list[str] = []

    try:
        async with async_playwright() as pw:
            browser = await launch_async_browser(pw, headless=True)
            try:
                context = await browser.new_context(viewport={"width": 1280, "height": 800}, device_scale_factor=1)
                auth_state = {
                    "state": {
                        "serverUrl": base_url,
                        "apiKey": settings.API_KEY,
                        "accessToken": "",
                        "refreshToken": "",
                        "user": None,
                        "isConfigured": True,
                    },
                    "version": 0,
                }
                await context.add_init_script(
                    "localStorage.setItem('agent-auth', JSON.stringify(%s));" % json.dumps(auth_state)
                )
                page = await context.new_page()
                page.on("pageerror", lambda exc: page_errors.append(str(exc)))
                page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
                page.on("requestfailed", lambda req: request_failures.append(req.url))
                await page.goto(route, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(1800)
                body_text = (await page.locator("body").inner_text(timeout=3000)).strip()
                await context.close()
            finally:
                await browser.close()
    except Exception as exc:
        phase = _phase(
            "browser_smoke",
            "unknown",
            f"Browser smoke infrastructure failed before a reliable result: {exc}",
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return phase, []

    issues: list[dict[str, Any]] = []
    if "Widget could not be loaded" in body_text:
        issues.append(_issue("browser_smoke", "error", "Full-widget page reported that the widget could not be loaded.", kind="page_load_failure"))
    for msg in page_errors[:3]:
        issues.append(_issue("browser_smoke", "error", msg, kind="page_error"))
    for msg in console_errors[:3]:
        issues.append(_issue("browser_smoke", "error", msg, kind="console_error"))
    if request_failures:
        issues.append(_issue("browser_smoke", "warning", f"{len(request_failures)} browser request(s) failed during smoke check.", kind="request_failed"))

    status = "failing" if any(i["severity"] == "error" for i in issues) else ("warning" if issues else "healthy")
    msg = "Browser smoke check loaded the widget page." if not issues else f"Browser smoke check found {len(issues)} issue(s)."
    return _phase("browser_smoke", status, msg, duration_ms=int((time.monotonic() - started) * 1000)), issues


def _result_dict(
    *,
    check_id: uuid.UUID,
    pin_id: uuid.UUID | None,
    target_kind: str,
    target_ref: str,
    status: str,
    summary: str,
    phases: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    event_counts: dict[str, int],
    checked_at: datetime,
) -> dict[str, Any]:
    return {
        "check_id": str(check_id),
        "pin_id": str(pin_id) if pin_id else None,
        "target_kind": target_kind,
        "target_ref": target_ref,
        "status": status,
        "summary": summary,
        "phases": phases,
        "issues": issues,
        "event_counts": event_counts,
        "checked_at": checked_at.isoformat(),
    }


def serialize_health_check(row: WidgetHealthCheck) -> dict[str, Any]:
    return _result_dict(
        check_id=row.id,
        pin_id=row.pin_id,
        target_kind=row.target_kind,
        target_ref=row.target_ref,
        status=row.status,
        summary=row.summary,
        phases=row.phases or [],
        issues=row.issues or [],
        event_counts=row.event_counts or {},
        checked_at=row.checked_at,
    )


async def latest_health_for_pins(
    db: AsyncSession,
    pin_ids: list[uuid.UUID | str],
) -> dict[str, dict[str, Any]]:
    parsed: list[uuid.UUID] = []
    for value in pin_ids:
        try:
            parsed.append(value if isinstance(value, uuid.UUID) else uuid.UUID(str(value)))
        except (TypeError, ValueError):
            continue
    if not parsed:
        return {}

    rows = (await db.execute(
        select(WidgetHealthCheck)
        .where(WidgetHealthCheck.pin_id.in_(parsed))
        .order_by(WidgetHealthCheck.pin_id, WidgetHealthCheck.checked_at.desc())
    )).scalars().all()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.pin_id)
        if key not in out:
            out[key] = serialize_health_check(row)
    return out


async def check_pin_health(
    db: AsyncSession,
    pin_id: uuid.UUID | str,
    *,
    include_browser: bool = True,
    persist: bool = True,
) -> dict[str, Any]:
    pid = pin_id if isinstance(pin_id, uuid.UUID) else uuid.UUID(str(pin_id))
    pin = await get_pin(db, pid)
    envelope = pin.envelope or {}
    phases: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    static_phase, static_issues = _static_check(pin, envelope)
    phases.append(static_phase)
    issues.extend(static_issues)

    debug_phase, debug_issues, event_counts = _debug_events_check(pin.id)
    phases.append(debug_phase)
    issues.extend(debug_issues)

    browser_phase, browser_issues = await _browser_smoke_check(pin.id, include_browser=include_browser)
    phases.append(browser_phase)
    issues.extend(browser_issues)

    issues = issues[:_MAX_ISSUES]
    status = _overall_status(phases, issues)
    checked_at = _now()
    check_id = uuid.uuid4()
    summary = _summary(status, issues)
    if persist:
        row = WidgetHealthCheck(
            id=check_id,
            pin_id=pin.id,
            target_kind="pin",
            target_ref=str(pin.id),
            status=status,
            summary=summary,
            phases=phases,
            issues=issues,
            event_counts=event_counts,
            checked_at=checked_at,
        )
        db.add(row)
        await db.commit()
    return _result_dict(
        check_id=check_id,
        pin_id=pin.id,
        target_kind="pin",
        target_ref=str(pin.id),
        status=status,
        summary=summary,
        phases=phases,
        issues=issues,
        event_counts=event_counts,
        checked_at=checked_at,
    )


async def check_envelope_health(
    envelope: dict[str, Any],
    *,
    target_ref: str = "draft",
    include_browser: bool = False,
) -> dict[str, Any]:
    phases: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    static_phase, static_issues = _static_check(None, envelope or {})
    phases.append(static_phase)
    issues.extend(static_issues)
    debug_phase, debug_issues, event_counts = _debug_events_check(None)
    phases.append(debug_phase)
    issues.extend(debug_issues)
    browser_phase, browser_issues = await _browser_smoke_check(None, include_browser=include_browser)
    phases.append(browser_phase)
    issues.extend(browser_issues)
    status = _overall_status(phases, issues)
    checked_at = _now()
    return _result_dict(
        check_id=uuid.uuid4(),
        pin_id=None,
        target_kind="draft",
        target_ref=target_ref,
        status=status,
        summary=_summary(status, issues),
        phases=phases,
        issues=issues[:_MAX_ISSUES],
        event_counts=event_counts,
        checked_at=checked_at,
    )


async def check_dashboard_widgets(
    db: AsyncSession,
    dashboard_key: str,
    *,
    limit: int = 20,
    include_browser: bool = True,
) -> dict[str, Any]:
    pins = await list_pins(db, dashboard_key=dashboard_key)
    selected = pins[: max(0, min(int(limit or 20), 100))]
    results: list[dict[str, Any]] = []
    for pin in selected:
        results.append(await check_pin_health(db, pin.id, include_browser=include_browser, persist=True))

    counts = dict(Counter(result["status"] for result in results))
    worst = "healthy"
    for status in counts:
        if STATUS_ORDER.get(status, 0) > STATUS_ORDER.get(worst, 0):
            worst = status
    return {
        "dashboard_key": dashboard_key,
        "checked_count": len(results),
        "total_pins": len(pins),
        "status": worst if results else "unknown",
        "counts": counts,
        "results": results,
    }


async def dashboard_pins_with_health(
    db: AsyncSession,
    dashboard_key: str,
) -> list[dict[str, Any]]:
    pins = await list_pins(db, dashboard_key=dashboard_key)
    serialized = [serialize_pin(pin) for pin in pins]
    latest = await latest_health_for_pins(db, [pin["id"] for pin in serialized])
    for pin in serialized:
        health = latest.get(str(pin.get("id")))
        if health:
            pin["widget_health"] = health
    return serialized
