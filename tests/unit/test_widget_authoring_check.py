from __future__ import annotations

import json

import pytest

from app.services.widget_authoring_check import run_widget_authoring_check


RICH_YAML = (
    "display: inline\n"
    "display_label: 'Hello {{name}}'\n"
    "template:\n"
    "  v: 1\n"
    "  components:\n"
    "    - type: heading\n"
    "      text: 'Hi {{name}}'\n"
    "      level: 3\n"
)


@pytest.mark.asyncio
async def test_authoring_check_renders_valid_draft_without_runtime() -> None:
    result = await run_widget_authoring_check(
        yaml_template=RICH_YAML,
        sample_payload={"name": "World"},
        tool_name="demo_tool",
        include_runtime=False,
    )

    assert result["ok"] is True
    assert result["readiness"] == "ready"
    assert [phase["name"] for phase in result["phases"]] == [
        "validation",
        "preview",
        "static",
        "debug_events",
        "browser_smoke",
    ]
    body = json.loads(result["envelope"]["body"])
    assert body["components"][0]["text"] == "Hi World"


@pytest.mark.asyncio
async def test_authoring_check_blocks_invalid_yaml() -> None:
    result = await run_widget_authoring_check(
        yaml_template="template:\n  v: 1\n  components:\n    - : bad\n",
        include_runtime=False,
    )

    assert result["ok"] is False
    assert result["readiness"] == "blocked"
    assert result["envelope"] is None
    assert any(issue["phase"] == "yaml" for issue in result["issues"])


@pytest.mark.asyncio
async def test_authoring_check_blocks_preview_module_import_error() -> None:
    result = await run_widget_authoring_check(
        yaml_template=RICH_YAML,
        python_code="raise RuntimeError('module failed')\n",
        sample_payload={"name": "World"},
        include_runtime=False,
    )

    assert result["ok"] is False
    assert result["readiness"] == "blocked"
    assert result["envelope"] is None
    assert any(
        issue["phase"] == "preview" and "module failed" in issue["message"]
        for issue in result["issues"]
    )


@pytest.mark.asyncio
async def test_authoring_check_requires_reliable_runtime_when_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.widget_health.settings.BASE_URL", "")

    result = await run_widget_authoring_check(
        yaml_template=RICH_YAML,
        sample_payload={"name": "World"},
        include_runtime=True,
    )

    assert result["ok"] is False
    assert result["readiness"] == "needs_runtime"
    browser_phase = next(phase for phase in result["phases"] if phase["name"] == "browser_smoke")
    assert browser_phase["status"] == "unknown"


@pytest.mark.asyncio
async def test_authoring_check_accepts_successful_runtime_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_browser_smoke(envelope, *, include_browser: bool, include_screenshot: bool = False):
        assert include_browser is True
        return (
            {"name": "browser_smoke", "status": "healthy", "message": "Runtime loaded."},
            [],
            {"bounds": {"width": 320, "height": 180, "top": 0, "left": 0}},
        )

    monkeypatch.setattr(
        "app.services.widget_health._browser_smoke_check_envelope",
        fake_browser_smoke,
    )

    result = await run_widget_authoring_check(
        yaml_template=RICH_YAML,
        sample_payload={"name": "World"},
        include_runtime=True,
    )

    assert result["ok"] is True
    assert result["readiness"] == "ready"
    assert result["artifacts"]["bounds"]["width"] == 320


@pytest.mark.asyncio
async def test_authoring_check_blocks_failed_runtime_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_browser_smoke(envelope, *, include_browser: bool, include_screenshot: bool = False):
        return (
            {"name": "browser_smoke", "status": "failing", "message": "Runtime failed."},
            [{"phase": "browser_smoke", "severity": "error", "message": "Console exploded."}],
            {},
        )

    monkeypatch.setattr(
        "app.services.widget_health._browser_smoke_check_envelope",
        fake_browser_smoke,
    )

    result = await run_widget_authoring_check(
        yaml_template=RICH_YAML,
        sample_payload={"name": "World"},
        include_runtime=True,
    )

    assert result["ok"] is False
    assert result["readiness"] == "blocked"
    assert result["summary"] == "Console exploded."
