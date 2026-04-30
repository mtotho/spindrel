from __future__ import annotations

import pytest

from app.agent.context import current_bot_id
from app.services.html_widget_authoring_check import run_html_widget_authoring_check


@pytest.mark.asyncio
async def test_html_authoring_check_passes_static_inline_without_runtime() -> None:
    result = await run_html_widget_authoring_check(
        html="<div>ok</div>",
        display_label="Demo",
        include_runtime=False,
    )

    assert result["ok"] is True
    assert result["readiness"] == "ready"
    assert [phase["name"] for phase in result["phases"]] == [
        "preview",
        "static",
        "debug_events",
        "browser_smoke",
    ]
    assert result["envelope"]["display_label"] == "Demo"
    assert result["next_actions"][0]["tool"] == "emit_html_widget"


@pytest.mark.asyncio
async def test_html_authoring_check_blocks_preview_errors() -> None:
    result = await run_html_widget_authoring_check(
        html="<div>ok</div>",
        library_ref="bot/other",
        include_runtime=False,
    )

    assert result["ok"] is False
    assert result["readiness"] == "blocked"
    assert result["envelope"] is None
    assert any(issue["phase"] == "input" for issue in result["issues"])


@pytest.mark.asyncio
async def test_html_authoring_check_requires_runtime_when_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.widget_health.settings.BASE_URL", "")

    result = await run_html_widget_authoring_check(
        html="<div>ok</div>",
        display_label="Demo",
        include_runtime=True,
    )

    assert result["ok"] is False
    assert result["readiness"] == "needs_runtime"


@pytest.mark.asyncio
async def test_html_authoring_check_accepts_successful_runtime_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_browser_smoke(envelope, *, include_browser: bool, include_screenshot: bool = False):
        assert include_browser is True
        assert include_screenshot is True
        return (
            {"name": "browser_smoke", "status": "healthy", "message": "Runtime loaded."},
            [],
            {"bounds": {"width": 320, "height": 180, "top": 0, "left": 0}},
        )

    monkeypatch.setattr(
        "app.services.widget_health._browser_smoke_check_envelope",
        fake_browser_smoke,
    )

    result = await run_html_widget_authoring_check(
        html="<div>ok</div>",
        display_label="Demo",
        include_runtime=True,
        include_screenshot=True,
    )

    assert result["ok"] is True
    assert result["readiness"] == "ready"
    assert result["artifacts"]["bounds"]["width"] == 320


@pytest.mark.asyncio
async def test_html_authoring_check_returns_pin_next_action_for_library(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tools.local import emit_html_widget as ehw

    bundle = tmp_path / ".widget_library" / "scratchpad"
    bundle.mkdir(parents=True)
    (bundle / "index.html").write_text("<div>scratch</div>")
    monkeypatch.setattr(ehw, "_resolve_scope_roots", lambda: (str(tmp_path), None))

    token = current_bot_id.set("crumb")
    try:
        result = await run_html_widget_authoring_check(
            library_ref="bot/scratchpad",
            include_runtime=False,
        )
    finally:
        current_bot_id.reset(token)

    assert result["ok"] is True
    assert result["next_actions"][0]["tool"] == "pin_widget"
    assert result["next_actions"][0]["args"] == {
        "widget": "bot/scratchpad",
        "source_kind": "library",
    }
