from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.local import memory_files
from app.tools.local.memory_files import _resolve_memory_write_path


def test_resolve_memory_write_path_is_memory_rooted(tmp_path):
    resolved = _resolve_memory_write_path("reference/project", str(tmp_path))

    assert resolved == str(tmp_path / "reference" / "project.md")


def test_resolve_memory_write_path_accepts_memory_prefix(tmp_path):
    resolved = _resolve_memory_write_path("memory/logs/2026-04-29.md", str(tmp_path))

    assert resolved == str(tmp_path / "logs" / "2026-04-29.md")


def test_resolve_memory_write_path_rejects_escape(tmp_path):
    with pytest.raises(ValueError):
        _resolve_memory_write_path("../project/MEMORY.md", str(tmp_path))


@pytest.mark.asyncio
async def test_memory_replace_section_emits_tool_result_envelope(tmp_path):
    bot = SimpleNamespace(id="bot-1", memory_scheme="workspace-files")
    memory_root = tmp_path / "memory"
    token = memory_files.current_bot_id.set("bot-1")
    try:
        with (
            patch("app.agent.bots.get_bot", return_value=bot),
            patch("app.services.workspace.workspace_service.get_workspace_root", return_value=str(tmp_path)),
            patch("app.services.memory_scheme.get_memory_root", return_value=str(memory_root)),
            patch("app.services.bot_hooks.schedule_after_write", MagicMock()) as schedule_after_write,
            patch("app.tools.local.memory_files._schedule_memory_reindex", MagicMock()) as schedule_reindex,
        ):
            result = await memory_files.memory(
                operation="replace_section",
                path="MEMORY.md",
                heading="Project",
                content="Shared Project workspace facts.",
            )
    finally:
        memory_files.current_bot_id.reset(token)

    data = json.loads(result)
    assert data["path"] == "memory/MEMORY.md"
    assert data["message"] == "replace_section complete"
    assert data["llm"] == json.dumps(
        {"path": "memory/MEMORY.md", "message": "replace_section complete"},
        ensure_ascii=False,
    )
    assert data["_envelope"]["content_type"] == "application/vnd.spindrel.diff+text"
    assert data["_envelope"]["display"] == "inline"
    assert data["_envelope"]["plain_body"] == "Replace Section memory/MEMORY.md: +1 -0 lines"
    assert "+++ b/memory/MEMORY.md" in data["_envelope"]["body"]
    assert "## Project\nShared Project workspace facts." in (memory_root / "MEMORY.md").read_text()
    schedule_after_write.assert_called_once_with("bot-1", "memory/MEMORY.md")
    schedule_reindex.assert_called_once_with(bot)


@pytest.mark.asyncio
async def test_memory_append_emits_diff_envelope(tmp_path):
    bot = SimpleNamespace(id="bot-1", memory_scheme="workspace-files")
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    (memory_root / "logs").mkdir()
    (memory_root / "logs" / "2026-04-30.md").write_text("# Log\n")
    token = memory_files.current_bot_id.set("bot-1")
    try:
        with (
            patch("app.agent.bots.get_bot", return_value=bot),
            patch("app.services.workspace.workspace_service.get_workspace_root", return_value=str(tmp_path)),
            patch("app.services.memory_scheme.get_memory_root", return_value=str(memory_root)),
            patch("app.services.bot_hooks.schedule_after_write", MagicMock()) as schedule_after_write,
            patch("app.tools.local.memory_files._schedule_memory_reindex", MagicMock()) as schedule_reindex,
        ):
            result = await memory_files.memory(
                operation="append",
                path="logs/2026-04-30.md",
                content="- Walk Clarence at 4.\n",
            )
    finally:
        memory_files.current_bot_id.reset(token)

    data = json.loads(result)
    assert data["path"] == "memory/logs/2026-04-30.md"
    assert data["_envelope"]["content_type"] == "application/vnd.spindrel.diff+text"
    assert data["_envelope"]["display"] == "inline"
    assert data["_envelope"]["plain_body"] == "Append memory/logs/2026-04-30.md: +1 -0 lines"
    assert "+- Walk Clarence at 4." in data["_envelope"]["body"]
    schedule_after_write.assert_called_once_with("bot-1", "memory/logs/2026-04-30.md")
    schedule_reindex.assert_called_once_with(bot)


@pytest.mark.asyncio
async def test_memory_append_rejects_leaked_tool_call_transcript(tmp_path):
    bot = SimpleNamespace(id="bot-1", memory_scheme="workspace-files")
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    (memory_root / "logs").mkdir()
    target = memory_root / "logs" / "2026-05-02.md"
    target.write_text("# Log\n")
    token = memory_files.current_bot_id.set("bot-1")
    try:
        with (
            patch("app.agent.bots.get_bot", return_value=bot),
            patch("app.services.workspace.workspace_service.get_workspace_root", return_value=str(tmp_path)),
            patch("app.services.memory_scheme.get_memory_root", return_value=str(memory_root)),
            patch("app.services.bot_hooks.schedule_after_write", MagicMock()) as schedule_after_write,
            patch("app.tools.local.memory_files._schedule_memory_reindex", MagicMock()) as schedule_reindex,
        ):
            result = await memory_files.memory(
                operation="append",
                path="logs/2026-05-02.md",
                content=(
                    "- 12:48 PM: Assessed attachment "
                    "}}}} to=functions.describe_attachment 天天中奖 to=functions.memory\n"
                ),
            )
    finally:
        memory_files.current_bot_id.reset(token)

    data = json.loads(result)
    assert "error" in data
    assert "tool-call transcript" in data["error"]
    assert target.read_text() == "# Log\n"
    schedule_after_write.assert_not_called()
    schedule_reindex.assert_not_called()


@pytest.mark.asyncio
async def test_memory_write_reindexes_only_current_bot_memory(tmp_path):
    bot = SimpleNamespace(id="bot-1", memory_scheme="workspace-files")

    with patch("app.services.bot_indexing.reindex_bot", new_callable=AsyncMock) as reindex_bot:
        await memory_files._reindex_bot_memory_after_write(bot)

    reindex_bot.assert_called_once_with(
        bot,
        include_workspace=False,
        include_memory=True,
        force=True,
    )


@pytest.mark.asyncio
async def test_memory_read_envelope_renders_markdown_body(tmp_path):
    bot = SimpleNamespace(id="bot-1", memory_scheme="workspace-files")
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    (memory_root / "MEMORY.md").write_text("# Memory\n\nFact.")
    token = memory_files.current_bot_id.set("bot-1")
    try:
        with (
            patch("app.agent.bots.get_bot", return_value=bot),
            patch("app.services.workspace.workspace_service.get_workspace_root", return_value=str(tmp_path)),
            patch("app.services.memory_scheme.get_memory_root", return_value=str(memory_root)),
        ):
            result = await memory_files.memory(operation="read", path="MEMORY.md")
    finally:
        memory_files.current_bot_id.reset(token)

    data = json.loads(result)
    assert data["content"] == "# Memory\n\nFact."
    assert data["_envelope"]["content_type"] == "text/markdown"
    assert data["_envelope"]["body"] == "# Memory\n\nFact."
    assert data["_envelope"]["plain_body"] == "Read memory/MEMORY.md"
