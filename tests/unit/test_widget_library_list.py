"""Tests for ``widget_library_list`` — Phase 1 of the Widget Library track.

The tool walks the in-repo core widget directory and returns structured
metadata per bundle.  ``bot`` / ``workspace`` scopes are placeholders for
later phases — asserting they currently return empty locks in the contract.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from app.tools.local.widget_library import widget_library_list


def _parse(result: str) -> dict:
    return json.loads(result)


@pytest.mark.asyncio
async def test_lists_core_widgets():
    raw = await widget_library_list()
    data = _parse(raw)
    assert data["count"] > 0
    names = {w["name"] for w in data["widgets"]}
    # ``notes_native`` is the supported Notes library entry; the older HTML
    # bundle stays on disk for compatibility but should no longer surface in
    # the discoverable library.
    assert "notes" not in names
    assert "notes_native" in names
    # Every entry carries the required fields.
    for widget in data["widgets"]:
        assert widget["scope"] == "core"
        assert widget["format"] in {"html", "template", "suite", "native_app"}
        assert "name" in widget


@pytest.mark.asyncio
async def test_native_widget_entries_surface_action_schema():
    raw = await widget_library_list(q="native")
    data = _parse(raw)
    by_name = {w["name"]: w for w in data["widgets"] if w["widget_kind"] == "native_app"}
    assert {"notes_native", "todo_native"} <= set(by_name)

    notes_actions = by_name["notes_native"].get("actions") or []
    assert {action["id"] for action in notes_actions} >= {"replace_body", "append_text", "clear"}

    todo_actions = by_name["todo_native"].get("actions") or []
    assert {action["id"] for action in todo_actions} >= {
        "add_item",
        "toggle_item",
        "rename_item",
        "delete_item",
        "reorder_items",
        "clear_completed",
    }


@pytest.mark.asyncio
async def test_skips_non_widget_directories():
    raw = await widget_library_list()
    names = {w["name"] for w in _parse(raw)["widgets"]}
    # ``suites/`` is a container directory, not a widget bundle — the scan
    # must skip it.  ``examples/`` likewise.
    assert "suites" not in names
    assert "examples" not in names


@pytest.mark.asyncio
async def test_format_filter_narrows_results():
    all_raw = await widget_library_list()
    all_widgets = _parse(all_raw)["widgets"]
    html_only = _parse(await widget_library_list(format="html"))["widgets"]
    assert all(w["format"] == "html" for w in html_only)
    # If there are non-html widgets, the html filter must shrink the list.
    non_html = [w for w in all_widgets if w["format"] != "html"]
    if non_html:
        assert len(html_only) < len(all_widgets)


@pytest.mark.asyncio
async def test_q_filter_matches_name():
    raw = await widget_library_list(q="notes")
    data = _parse(raw)
    # At least one entry whose name or label/description contains "notes".
    assert data["count"] >= 1
    assert any("notes" in w["name"].lower() for w in data["widgets"])


@pytest.mark.asyncio
async def test_bot_scope_empty_without_bot_context():
    # No bot context bound → bot scope resolves to no directory → empty list.
    # This locks in the "degrade gracefully outside a channel" behavior.
    data = _parse(await widget_library_list(scope="bot"))
    assert data["count"] == 0
    assert data["widgets"] == []


@pytest.mark.asyncio
async def test_workspace_scope_empty_without_bot_context():
    data = _parse(await widget_library_list(scope="workspace"))
    assert data["count"] == 0


@pytest.mark.asyncio
async def test_bot_scope_lists_authored_widgets(tmp_path, monkeypatch):
    """When a bot has authored widgets under <ws_root>/.widget_library/, the
    bot scope returns metadata for each bundle."""
    from app.tools.local import widget_library as wl

    # Build a fake ws_root with one authored widget.
    ws = tmp_path / "ws"
    (ws / ".widget_library" / "my_toggle").mkdir(parents=True)
    (ws / ".widget_library" / "my_toggle" / "index.html").write_text(
        "<div id=t>toggle</div>"
    )
    (ws / ".widget_library" / "my_toggle" / "widget.yaml").write_text(
        "display_label: My Toggle\n"
        "description: flip the thing\n"
    )

    monkeypatch.setattr(
        wl, "_resolve_scope_roots", lambda: (str(ws), None),
    )

    data = _parse(await widget_library_list(scope="bot"))
    assert data["count"] == 1
    widget = data["widgets"][0]
    assert widget["name"] == "my_toggle"
    assert widget["scope"] == "bot"
    assert widget["format"] == "html"
    assert widget["display_label"] == "My Toggle"
    assert widget["description"] == "flip the thing"


@pytest.mark.asyncio
async def test_bot_scope_surfaces_head_revision(tmp_path, monkeypatch):
    from app.tools.local import widget_library as wl

    ws = tmp_path / "ws"
    bundle = ws / ".widget_library" / "my_toggle"
    bundle.mkdir(parents=True)
    (bundle / "index.html").write_text("<div>toggle</div>")
    subprocess.run(
        ["git", "-C", str(ws / ".widget_library"), "init"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(ws / ".widget_library"), "config", "user.name", "Widget Bot"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(ws / ".widget_library"), "config", "user.email", "widget-bot@example.com"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(ws / ".widget_library"), "add", "my_toggle/index.html"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(ws / ".widget_library"), "commit", "-m", "seed widget"],
        check=True,
        capture_output=True,
        text=True,
    )
    head = subprocess.run(
        ["git", "-C", str(ws / ".widget_library"), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    monkeypatch.setattr(wl, "_resolve_scope_roots", lambda: (str(ws), None))

    data = _parse(await widget_library_list(scope="bot"))
    assert data["count"] == 1
    assert data["widgets"][0]["versioned"] is True
    assert data["widgets"][0]["head_revision"] == head


@pytest.mark.asyncio
async def test_workspace_scope_lists_shared_widgets(tmp_path, monkeypatch):
    from app.tools.local import widget_library as wl

    shared = tmp_path / "shared"
    (shared / ".widget_library" / "team_board").mkdir(parents=True)
    (shared / ".widget_library" / "team_board" / "index.html").write_text("<x/>")
    (shared / ".widget_library" / "team_board" / "widget.yaml").write_text(
        "display_label: Team Board\n"
    )

    monkeypatch.setattr(
        wl, "_resolve_scope_roots", lambda: (str(shared / "bots" / "b1"), str(shared)),
    )

    data = _parse(await widget_library_list(scope="workspace"))
    assert data["count"] == 1
    assert data["widgets"][0]["name"] == "team_board"
    assert data["widgets"][0]["scope"] == "workspace"


@pytest.mark.asyncio
async def test_all_scope_merges_core_bot_and_workspace(tmp_path, monkeypatch):
    from app.tools.local import widget_library as wl

    shared = tmp_path / "shared"
    ws = shared / "bots" / "b1"
    (ws / ".widget_library" / "private").mkdir(parents=True)
    (ws / ".widget_library" / "private" / "index.html").write_text("<x/>")
    (shared / ".widget_library" / "team").mkdir(parents=True)
    (shared / ".widget_library" / "team" / "index.html").write_text("<x/>")

    monkeypatch.setattr(
        wl, "_resolve_scope_roots", lambda: (str(ws), str(shared)),
    )

    data = _parse(await widget_library_list(scope="all"))
    names_by_scope = {(w["name"], w["scope"]) for w in data["widgets"]}
    assert ("private", "bot") in names_by_scope
    assert ("team", "workspace") in names_by_scope
    # core still present — `notes` ships in-repo.
    assert any(scope == "core" for _name, scope in names_by_scope)


@pytest.mark.asyncio
async def test_envelope_summary_present():
    raw = await widget_library_list()
    env = _parse(raw)["_envelope"]
    assert env["content_type"] == "text/markdown"
    assert "Widget library" in env["body"]
    assert env["display"] == "inline"
