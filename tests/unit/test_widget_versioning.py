from __future__ import annotations

from pathlib import Path

import pytest

from app.services import widget_versioning as wv


@pytest.mark.asyncio
async def test_record_widget_mutation_creates_commit_and_history(tmp_path):
    ws = tmp_path / "ws"
    file_path = ws / ".widget_library" / "home_control" / "index.html"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("<div>v1</div>")

    records = await wv.record_widget_mutation(
        operation="create",
        resolved_path=str(file_path),
        resolved_destination=None,
        ws_root=str(ws),
        shared_root=None,
        bot_id="test-bot",
    )

    assert len(records) == 1
    assert records[0]["widget_ref"] == "bot/home_control"
    history = wv.widget_version_history("bot/home_control", ws_root=str(ws), shared_root=None)
    assert len(history) == 1
    assert history[0]["revision"] == records[0]["revision"]


@pytest.mark.asyncio
async def test_rollback_widget_to_revision_restores_contents(tmp_path):
    ws = tmp_path / "ws"
    file_path = ws / ".widget_library" / "home_control" / "index.html"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("<div>v1</div>")

    first = await wv.record_widget_mutation(
        operation="create",
        resolved_path=str(file_path),
        resolved_destination=None,
        ws_root=str(ws),
        shared_root=None,
        bot_id="test-bot",
    )
    file_path.write_text("<div>v2</div>")
    second = await wv.record_widget_mutation(
        operation="overwrite",
        resolved_path=str(file_path),
        resolved_destination=None,
        ws_root=str(ws),
        shared_root=None,
        bot_id="test-bot",
    )

    restored = await wv.rollback_widget_to_revision(
        "bot/home_control",
        first[0]["revision"],
        ws_root=str(ws),
        shared_root=None,
        bot_id="test-bot",
    )

    assert restored["operation"] == "rollback"
    assert restored["revision"] != second[0]["revision"]
    assert Path(file_path).read_text() == "<div>v1</div>"
