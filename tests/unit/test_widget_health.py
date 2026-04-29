from __future__ import annotations

from uuid import uuid4

import pytest

from app.services import widget_debug
from app.services.widget_health import (
    _debug_events_check,
    _overall_status,
    _static_check,
    check_envelope_health,
)


@pytest.fixture(autouse=True)
def _reset_widget_debug_ring():
    widget_debug.reset_all()
    yield
    widget_debug.reset_all()


def test_static_check_flags_missing_interactive_source() -> None:
    phase, issues = _static_check(None, {
        "content_type": "application/vnd.spindrel.html+interactive",
        "display_label": "Broken",
    })

    assert phase["status"] == "failing"
    assert any(issue["kind"] == "missing_html_source" for issue in issues)


def test_static_check_warns_on_raw_fetch() -> None:
    phase, issues = _static_check(None, {
        "content_type": "application/vnd.spindrel.html+interactive",
        "display_label": "Fetchy",
        "body": "<script>fetch('/api/v1/things')</script>",
    })

    assert phase["status"] == "warning"
    assert any(issue["kind"] == "raw_fetch" for issue in issues)


def test_debug_events_check_summarizes_runtime_failures() -> None:
    pin_id = uuid4()
    widget_debug.record_event(pin_id, {
        "kind": "tool-call",
        "tool": "example",
        "ok": False,
        "error": "Tool failed",
    })
    widget_debug.record_event(pin_id, {
        "kind": "error",
        "message": "Cannot read property x",
        "line": 12,
    })

    phase, issues, counts = _debug_events_check(pin_id)

    assert phase["status"] == "failing"
    assert counts == {"tool-call": 1, "error": 1}
    assert [issue["severity"] for issue in issues] == ["error", "error"]


def test_overall_status_keeps_unknown_when_browser_not_run() -> None:
    phases = [
        {"name": "static", "status": "healthy"},
        {"name": "browser_smoke", "status": "unknown"},
    ]

    assert _overall_status(phases, []) == "unknown"


@pytest.mark.asyncio
async def test_draft_envelope_health_is_not_persisted() -> None:
    result = await check_envelope_health(
        {
            "content_type": "application/vnd.spindrel.html+interactive",
            "display_label": "Draft",
            "body": "<div>ok</div>",
        },
        target_ref="draft-test",
        include_browser=False,
    )

    assert result["pin_id"] is None
    assert result["target_kind"] == "draft"
    assert result["target_ref"] == "draft-test"
    assert result["status"] == "unknown"
