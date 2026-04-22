from __future__ import annotations

import subprocess
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_enriched_pins_surfaces_bundle_revision(tmp_path, monkeypatch):
    from app.agent.context import current_bot_id
    from app.tools.local import dashboard_tools

    bundle = tmp_path / ".widget_library" / "home_control"
    bundle.mkdir(parents=True)
    (bundle / "index.html").write_text("<div>home</div>")
    subprocess.run(
        ["git", "-C", str(tmp_path / ".widget_library"), "init"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path / ".widget_library"), "config", "user.name", "Widget Bot"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path / ".widget_library"), "config", "user.email", "widget-bot@example.com"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path / ".widget_library"), "add", "home_control/index.html"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path / ".widget_library"), "commit", "-m", "seed widget"],
        check=True,
        capture_output=True,
        text=True,
    )
    head = subprocess.run(
        ["git", "-C", str(tmp_path / ".widget_library"), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    @asynccontextmanager
    async def _fake_session():
        yield object()

    async def _fake_list_widget_handler_tools(_db, *, bot_id, channel_id):
        return [], {}

    monkeypatch.setattr("app.db.engine.async_session", _fake_session)
    monkeypatch.setattr("app.agent.bots.get_bot", lambda _bot_id: SimpleNamespace(id="test-bot", shared_workspace_id=None))
    monkeypatch.setattr("app.services.workspace.workspace_service.get_workspace_root", lambda _bot_id, _bot: str(tmp_path))
    monkeypatch.setattr("app.services.widget_handler_tools.list_widget_handler_tools", _fake_list_widget_handler_tools)

    token = current_bot_id.set("test-bot")
    try:
        enriched = await dashboard_tools._enriched_pins([
            {
                "id": "pin-1",
                "zone": "grid",
                "envelope": {"source_library_ref": "bot/home_control"},
            }
        ])
    finally:
        current_bot_id.reset(token)

    assert enriched[0]["bundle_revision"] == head
