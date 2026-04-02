"""Unit tests for app/tools/local/file_ops.py — the `file` tool."""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.tools.local.file_ops import (
    _resolve_path,
    _maybe_resolve_cross_channel,
    _op_read,
    _op_write,
    _op_append,
    _op_edit,
    _op_list,
    _op_delete,
    _op_mkdir,
    file as file_tool,
    MAX_CONTENT_BYTES,
    MAX_READ_LINES,
    DEFAULT_READ_LINES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def ws(tmp_path):
    """Create a temp workspace root with some files."""
    (tmp_path / "hello.txt").write_text("Hello world\n")
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "nested.md").write_text("# Nested\nLine 2\nLine 3\n")
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "MEMORY.md").write_text("# Memory\n\n## Facts\n- Fact 1\n")
    return tmp_path


def _mock_bot(ws_root: str, workspace_type="host", shared_workspace_id=None, bot_id="test_bot", shared_workspace_role=None):
    """Create a minimal mock bot."""
    bot = MagicMock()
    bot.id = bot_id
    bot.shared_workspace_id = shared_workspace_id
    bot.shared_workspace_role = shared_workspace_role
    bot.workspace = MagicMock()
    bot.workspace.type = workspace_type
    bot.workspace.enabled = True
    bot.cross_workspace_access = False
    return bot


# ---------------------------------------------------------------------------
# Path Resolution
# ---------------------------------------------------------------------------


class TestResolvePath:
    def test_relative_path(self, ws):
        result = _resolve_path("hello.txt", str(ws))
        assert result == str(ws / "hello.txt")

    def test_relative_nested(self, ws):
        result = _resolve_path("subdir/nested.md", str(ws))
        assert result == str(ws / "subdir" / "nested.md")

    def test_absolute_within_workspace(self, ws):
        result = _resolve_path(str(ws / "hello.txt"), str(ws))
        assert result == str(ws / "hello.txt")

    def test_traversal_blocked_dotdot(self, ws):
        with pytest.raises(ValueError, match="escapes workspace"):
            _resolve_path("../etc/passwd", str(ws))

    def test_traversal_blocked_absolute(self, ws):
        with pytest.raises(ValueError, match="escapes workspace"):
            _resolve_path("/etc/passwd", str(ws))

    def test_empty_path(self, ws):
        with pytest.raises(ValueError, match="Empty path"):
            _resolve_path("", str(ws))

    def test_workspace_prefix_host(self, ws):
        bot = _mock_bot(str(ws), workspace_type="host")
        with patch("app.services.workspace.WorkspaceService.get_workspace_root", return_value=str(ws)):
            result = _resolve_path("/workspace/hello.txt", str(ws), bot)
        assert result == str(ws / "hello.txt")

    def test_workspace_root_only(self, ws):
        bot = _mock_bot(str(ws), workspace_type="host")
        with patch("app.services.workspace.WorkspaceService.get_workspace_root", return_value=str(ws)):
            result = _resolve_path("/workspace", str(ws), bot)
        assert os.path.realpath(str(ws)) == result

    def test_traversal_via_symlink(self, ws):
        """Symlink pointing outside workspace should be blocked."""
        link = ws / "escape"
        link.symlink_to("/tmp")
        with pytest.raises(ValueError, match="escapes workspace"):
            _resolve_path("escape/secret", str(ws))

    def test_bare_memory_md_resolves_to_root(self, ws):
        """Bare 'MEMORY.md' resolves to workspace root, NOT memory/ subdir.

        This documents the behavior that caused the memory path bug —
        the prompt must tell bots to use 'memory/MEMORY.md', not bare 'MEMORY.md'.
        """
        result = _resolve_path("MEMORY.md", str(ws))
        assert result == str(ws / "MEMORY.md")
        # This is NOT the same as memory/MEMORY.md:
        assert result != str(ws / "memory" / "MEMORY.md")

    def test_prefixed_memory_md_resolves_to_subdir(self, ws):
        """'memory/MEMORY.md' correctly resolves to the memory subdirectory."""
        result = _resolve_path("memory/MEMORY.md", str(ws))
        assert result == os.path.realpath(str(ws / "memory" / "MEMORY.md"))

    def test_prefixed_memory_log_resolves_to_subdir(self, ws):
        """'memory/logs/2026-04-01.md' resolves into the logs subdirectory."""
        result = _resolve_path("memory/logs/2026-04-01.md", str(ws))
        assert result == os.path.realpath(str(ws / "memory" / "logs" / "2026-04-01.md"))


class TestResolvePathSharedWorkspace:
    """Test _resolve_path for shared workspace bots.

    Shared workspace layout:
        {shared_root}/
        ├── bots/
        │   ├── my_bot/memory/MEMORY.md
        │   └── other_bot/memory/MEMORY.md
        ├── channels/
        │   └── abc-123/tasks.md
        └── common/
    """

    @pytest.fixture
    def shared_ws(self, tmp_path):
        """Build a shared workspace directory tree."""
        root = tmp_path / "shared"
        (root / "bots" / "my_bot" / "memory").mkdir(parents=True)
        (root / "bots" / "my_bot" / "memory" / "MEMORY.md").write_text("# My Memory\n")
        (root / "bots" / "other_bot" / "memory").mkdir(parents=True)
        (root / "bots" / "other_bot" / "memory" / "MEMORY.md").write_text("# Other\n")
        (root / "channels" / "abc-123").mkdir(parents=True)
        (root / "channels" / "abc-123" / "tasks.md").write_text("# Tasks\n")
        (root / "common").mkdir()
        (root / "common" / "spec.md").write_text("# Spec\n")
        return root

    def _make_bot(self, shared_ws):
        bot = _mock_bot(
            str(shared_ws / "bots" / "my_bot"),
            workspace_type="docker",
            shared_workspace_id="ws-123",
            bot_id="my_bot",
        )
        return bot

    def test_relative_resolves_to_bot_dir(self, shared_ws):
        """Relative paths resolve to bots/{bot_id}/ — for memory etc."""
        bot = self._make_bot(shared_ws)
        ws_root = str(shared_ws / "bots" / "my_bot")
        with patch("app.services.shared_workspace.shared_workspace_service") as mock_sw:
            mock_sw.get_host_root.return_value = str(shared_ws)
            result = _resolve_path("memory/MEMORY.md", ws_root, bot)
        assert result == os.path.realpath(str(shared_ws / "bots" / "my_bot" / "memory" / "MEMORY.md"))

    def test_absolute_channel_path_allowed(self, shared_ws):
        """Absolute /workspace/channels/... paths are allowed for shared workspace bots."""
        bot = self._make_bot(shared_ws)
        ws_root = str(shared_ws / "bots" / "my_bot")
        with patch("app.services.shared_workspace.shared_workspace_service") as mock_sw:
            mock_sw.get_host_root.return_value = str(shared_ws)
            mock_sw.translate_path.return_value = str(shared_ws / "channels" / "abc-123" / "tasks.md")
            with patch("app.services.workspace.workspace_service") as mock_ws:
                mock_ws.translate_path.side_effect = lambda bid, p, w, bot: mock_sw.translate_path("ws-123", p)
                result = _resolve_path("/workspace/channels/abc-123/tasks.md", ws_root, bot)
        assert result == os.path.realpath(str(shared_ws / "channels" / "abc-123" / "tasks.md"))

    def test_absolute_common_path_allowed(self, shared_ws):
        """Absolute /workspace/common/... paths are allowed."""
        bot = self._make_bot(shared_ws)
        ws_root = str(shared_ws / "bots" / "my_bot")
        with patch("app.services.shared_workspace.shared_workspace_service") as mock_sw:
            mock_sw.get_host_root.return_value = str(shared_ws)
            mock_sw.translate_path.return_value = str(shared_ws / "common" / "spec.md")
            with patch("app.services.workspace.workspace_service") as mock_ws:
                mock_ws.translate_path.side_effect = lambda bid, p, w, bot: mock_sw.translate_path("ws-123", p)
                result = _resolve_path("/workspace/common/spec.md", ws_root, bot)
        assert result == os.path.realpath(str(shared_ws / "common" / "spec.md"))

    def test_other_bot_dir_blocked(self, shared_ws):
        """Cannot access another bot's directory."""
        bot = self._make_bot(shared_ws)
        ws_root = str(shared_ws / "bots" / "my_bot")
        with patch("app.services.shared_workspace.shared_workspace_service") as mock_sw:
            mock_sw.get_host_root.return_value = str(shared_ws)
            mock_sw.translate_path.return_value = str(shared_ws / "bots" / "other_bot" / "memory" / "MEMORY.md")
            with patch("app.services.workspace.workspace_service") as mock_ws:
                mock_ws.translate_path.side_effect = lambda bid, p, w, bot: mock_sw.translate_path("ws-123", p)
                with pytest.raises(ValueError, match="another bot"):
                    _resolve_path("/workspace/bots/other_bot/memory/MEMORY.md", ws_root, bot)

    def test_orchestrator_can_access_other_bot_dirs(self, shared_ws):
        """Orchestrator role can read other bots' directories."""
        bot = _mock_bot(
            str(shared_ws / "bots" / "my_bot"),
            workspace_type="docker",
            shared_workspace_id="ws-123",
            bot_id="my_bot",
            shared_workspace_role="orchestrator",
        )
        ws_root = str(shared_ws / "bots" / "my_bot")
        # Create the target file
        other_dir = shared_ws / "bots" / "other_bot" / "memory"
        other_dir.mkdir(parents=True, exist_ok=True)
        (other_dir / "MEMORY.md").write_text("other bot memory")

        with patch("app.services.shared_workspace.shared_workspace_service") as mock_sw:
            mock_sw.get_host_root.return_value = str(shared_ws)
            mock_sw.translate_path.return_value = str(shared_ws / "bots" / "other_bot" / "memory" / "MEMORY.md")
            with patch("app.services.workspace.workspace_service") as mock_ws:
                mock_ws.translate_path.side_effect = lambda bid, p, w, bot: mock_sw.translate_path("ws-123", p)
                result = _resolve_path("/workspace/bots/other_bot/memory/MEMORY.md", ws_root, bot)
        assert result == os.path.realpath(str(shared_ws / "bots" / "other_bot" / "memory" / "MEMORY.md"))

    def test_member_cannot_access_other_bot_dirs(self, shared_ws):
        """Member role (default) cannot access other bots' directories."""
        bot = _mock_bot(
            str(shared_ws / "bots" / "my_bot"),
            workspace_type="docker",
            shared_workspace_id="ws-123",
            bot_id="my_bot",
            shared_workspace_role="member",
        )
        ws_root = str(shared_ws / "bots" / "my_bot")
        with patch("app.services.shared_workspace.shared_workspace_service") as mock_sw:
            mock_sw.get_host_root.return_value = str(shared_ws)
            mock_sw.translate_path.return_value = str(shared_ws / "bots" / "other_bot" / "memory" / "MEMORY.md")
            with patch("app.services.workspace.workspace_service") as mock_ws:
                mock_ws.translate_path.side_effect = lambda bid, p, w, bot: mock_sw.translate_path("ws-123", p)
                with pytest.raises(ValueError, match="another bot"):
                    _resolve_path("/workspace/bots/other_bot/memory/MEMORY.md", ws_root, bot)

    def test_own_bot_dir_via_absolute_allowed(self, shared_ws):
        """Absolute path to own bot dir is allowed."""
        bot = self._make_bot(shared_ws)
        ws_root = str(shared_ws / "bots" / "my_bot")
        with patch("app.services.shared_workspace.shared_workspace_service") as mock_sw:
            mock_sw.get_host_root.return_value = str(shared_ws)
            mock_sw.translate_path.return_value = str(shared_ws / "bots" / "my_bot" / "memory" / "MEMORY.md")
            with patch("app.services.workspace.workspace_service") as mock_ws:
                mock_ws.translate_path.side_effect = lambda bid, p, w, bot: mock_sw.translate_path("ws-123", p)
                result = _resolve_path("/workspace/bots/my_bot/memory/MEMORY.md", ws_root, bot)
        assert result == os.path.realpath(str(shared_ws / "bots" / "my_bot" / "memory" / "MEMORY.md"))

    def test_escape_shared_root_blocked(self, shared_ws):
        """Paths outside the shared workspace root are blocked."""
        bot = self._make_bot(shared_ws)
        ws_root = str(shared_ws / "bots" / "my_bot")
        with patch("app.services.shared_workspace.shared_workspace_service") as mock_sw:
            mock_sw.get_host_root.return_value = str(shared_ws)
            # Path that resolves outside shared root
            with pytest.raises(ValueError, match="escapes workspace"):
                _resolve_path("/etc/passwd", ws_root, bot)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


class TestOpRead:
    def test_read_file(self, ws):
        result = _op_read(str(ws / "hello.txt"), str(ws), None, None)
        assert "Hello world" in result
        assert "1 lines" in result

    def test_read_with_line_numbers(self, ws):
        result = _op_read(str(ws / "subdir" / "nested.md"), str(ws), None, None)
        assert "1\t# Nested" in result
        assert "2\tLine 2" in result

    def test_read_offset_and_limit(self, ws):
        result = _op_read(str(ws / "subdir" / "nested.md"), str(ws), 2, 1)
        assert "Line 2" in result
        assert "# Nested" not in result  # line 1 skipped
        assert "showing 2-2" in result

    def test_read_nonexistent(self, ws):
        result = _op_read(str(ws / "nope.txt"), str(ws), None, None)
        parsed = json.loads(result)
        assert "error" in parsed

    def test_read_large_offset(self, ws):
        result = _op_read(str(ws / "hello.txt"), str(ws), 999, None)
        # Should return header but no content lines
        assert "1 lines" in result

    def test_read_limit_capped(self, ws):
        """Limit should be capped at MAX_READ_LINES."""
        # Create a file with many lines
        big = ws / "big.txt"
        big.write_text("\n".join(f"Line {i}" for i in range(3000)))
        result = _op_read(str(big), str(ws), 1, 5000)
        # Should only show MAX_READ_LINES lines
        lines = [l for l in result.split("\n") if l.strip() and not l.startswith("#")]
        assert len(lines) <= MAX_READ_LINES


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


class TestOpWrite:
    def test_write_new_file(self, ws):
        path = str(ws / "new.txt")
        result = json.loads(_op_write(path, "hello"))
        assert result["ok"] is True
        assert Path(path).read_text() == "hello"

    def test_write_creates_parent_dirs(self, ws):
        path = str(ws / "a" / "b" / "c.txt")
        result = json.loads(_op_write(path, "deep"))
        assert result["ok"] is True
        assert Path(path).read_text() == "deep"

    def test_write_overwrites(self, ws):
        path = str(ws / "hello.txt")
        _op_write(path, "replaced")
        assert Path(path).read_text() == "replaced"

    def test_write_no_content(self, ws):
        result = json.loads(_op_write(str(ws / "x.txt"), None))
        assert "error" in result

    def test_write_size_limit(self, ws):
        big = "x" * (MAX_CONTENT_BYTES + 1)
        result = json.loads(_op_write(str(ws / "big.txt"), big))
        assert "error" in result
        assert "limit" in result["error"]

    def test_write_shell_metacharacters(self, ws):
        """Content with shell metacharacters should be written verbatim."""
        content = "Bennie's last $HOME run `backtick` $(cmd) && rm -rf /"
        path = str(ws / "meta.txt")
        _op_write(path, content)
        assert Path(path).read_text() == content

    def test_write_apostrophe(self, ws):
        """The original bug: apostrophe in content."""
        content = "Bennie's last visit was great. She'll be back."
        path = str(ws / "notes.md")
        _op_write(path, content)
        assert Path(path).read_text() == content


# ---------------------------------------------------------------------------
# Append
# ---------------------------------------------------------------------------


class TestOpAppend:
    def test_append_to_existing(self, ws):
        path = str(ws / "hello.txt")
        _op_append(path, "appended")
        content = Path(path).read_text()
        assert content == "Hello world\nappended"

    def test_append_creates_file(self, ws):
        path = str(ws / "new_append.txt")
        _op_append(path, "first line")
        assert Path(path).read_text() == "first line"

    def test_append_adds_newline_if_missing(self, ws):
        path = str(ws / "no_newline.txt")
        Path(path).write_text("no trailing newline")
        _op_append(path, "appended")
        content = Path(path).read_text()
        assert content == "no trailing newline\nappended"

    def test_append_no_extra_newline(self, ws):
        """If file already ends with newline, don't add another."""
        path = str(ws / "hello.txt")  # ends with \n
        _op_append(path, "appended")
        content = Path(path).read_text()
        assert content == "Hello world\nappended"
        assert "\n\n" not in content

    def test_append_no_content(self, ws):
        result = json.loads(_op_append(str(ws / "x.txt"), None))
        assert "error" in result

    def test_append_shell_metacharacters(self, ws):
        content = "Don't forget $PATH `eval` $(rm -rf /)"
        path = str(ws / "meta_append.txt")
        _op_append(path, content)
        assert Path(path).read_text() == content


# ---------------------------------------------------------------------------
# Edit
# ---------------------------------------------------------------------------


class TestOpEdit:
    def test_edit_replace_first(self, ws):
        path = str(ws / "memory" / "MEMORY.md")
        result = json.loads(_op_edit(path, "Fact 1", "Fact ONE", False))
        assert result["ok"] is True
        assert result["replacements"] == 1
        assert "Fact ONE" in Path(path).read_text()

    def test_edit_replace_all(self, ws):
        path = str(ws / "dups.txt")
        Path(path).write_text("aaa bbb aaa ccc aaa")
        result = json.loads(_op_edit(path, "aaa", "XXX", replace_all=True))
        assert result["replacements"] == 3
        assert Path(path).read_text() == "XXX bbb XXX ccc XXX"

    def test_edit_not_found(self, ws):
        path = str(ws / "hello.txt")
        result = json.loads(_op_edit(path, "NONEXISTENT", "x", False))
        assert "error" in result
        assert "not found" in result["error"]

    def test_edit_whitespace_hint(self, ws):
        """If text exists but with different whitespace, provide a hint."""
        path = str(ws / "hello.txt")
        result = json.loads(_op_edit(path, "  Hello world  ", "x", False))
        assert "error" in result
        assert "whitespace" in result["error"].lower()

    def test_edit_file_not_found(self, ws):
        result = json.loads(_op_edit(str(ws / "nope.txt"), "a", "b", False))
        assert "error" in result

    def test_edit_no_find(self, ws):
        result = json.loads(_op_edit(str(ws / "hello.txt"), None, "x", False))
        assert "error" in result

    def test_edit_no_replace(self, ws):
        result = json.loads(_op_edit(str(ws / "hello.txt"), "Hello", None, False))
        assert "error" in result


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


class TestOpList:
    def test_list_dir(self, ws):
        result = json.loads(_op_list(str(ws), str(ws)))
        entries = result["entries"]
        names = [e["name"] for e in entries]
        assert "hello.txt" in names
        assert "subdir" in names
        assert "memory" in names

    def test_list_dirs_first(self, ws):
        result = json.loads(_op_list(str(ws), str(ws)))
        entries = result["entries"]
        dir_idx = [i for i, e in enumerate(entries) if e["type"] == "dir"]
        file_idx = [i for i, e in enumerate(entries) if e["type"] == "file"]
        if dir_idx and file_idx:
            assert max(dir_idx) < min(file_idx)

    def test_list_file_has_size(self, ws):
        result = json.loads(_op_list(str(ws), str(ws)))
        files = [e for e in result["entries"] if e["type"] == "file"]
        for f in files:
            assert "size" in f

    def test_list_not_a_dir(self, ws):
        result = json.loads(_op_list(str(ws / "hello.txt"), str(ws)))
        assert "error" in json.loads(result) if isinstance(result, str) else "error" in result


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class TestOpDelete:
    def test_delete_file(self, ws):
        path = str(ws / "hello.txt")
        result = json.loads(_op_delete(path))
        assert result["ok"] is True
        assert not os.path.exists(path)

    def test_delete_directory_refused(self, ws):
        result = json.loads(_op_delete(str(ws / "subdir")))
        assert "error" in result
        assert "director" in result["error"].lower()

    def test_delete_nonexistent(self, ws):
        result = json.loads(_op_delete(str(ws / "nope.txt")))
        assert "error" in result


# ---------------------------------------------------------------------------
# Mkdir
# ---------------------------------------------------------------------------


class TestOpMkdir:
    def test_mkdir_new(self, ws):
        path = str(ws / "newdir")
        result = json.loads(_op_mkdir(path))
        assert result["ok"] is True
        assert os.path.isdir(path)

    def test_mkdir_nested(self, ws):
        path = str(ws / "a" / "b" / "c")
        result = json.loads(_op_mkdir(path))
        assert result["ok"] is True
        assert os.path.isdir(path)

    def test_mkdir_idempotent(self, ws):
        path = str(ws / "subdir")
        result = json.loads(_op_mkdir(path))
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# Integration: file() dispatch with mocked bot context
# ---------------------------------------------------------------------------


class TestFileTool:
    """Test the top-level file() function with mocked bot context."""

    @pytest.fixture
    def mock_ctx(self, ws):
        bot = _mock_bot(str(ws))
        with patch("app.tools.local.file_ops.current_bot_id") as mock_bid:
            mock_bid.get.return_value = "test_bot"
            with patch("app.tools.local.file_ops._get_bot_and_workspace_root") as mock_get:
                mock_get.return_value = (bot, "test_bot", str(ws))
                yield ws, bot

    @pytest.mark.asyncio
    async def test_read(self, mock_ctx):
        ws, _ = mock_ctx
        result = await file_tool(operation="read", path="hello.txt")
        assert "Hello world" in result

    @pytest.mark.asyncio
    async def test_write(self, mock_ctx):
        ws, _ = mock_ctx
        result = await file_tool(operation="write", path="out.txt", content="hi")
        parsed = json.loads(result)
        assert parsed["ok"] is True
        assert (ws / "out.txt").read_text() == "hi"

    @pytest.mark.asyncio
    async def test_append(self, mock_ctx):
        ws, _ = mock_ctx
        result = await file_tool(operation="append", path="hello.txt", content="more")
        parsed = json.loads(result)
        assert parsed["ok"] is True

    @pytest.mark.asyncio
    async def test_edit(self, mock_ctx):
        ws, _ = mock_ctx
        result = await file_tool(
            operation="edit", path="hello.txt",
            find="Hello world", replace="Goodbye world",
        )
        parsed = json.loads(result)
        assert parsed["ok"] is True
        assert (ws / "hello.txt").read_text().startswith("Goodbye world")

    @pytest.mark.asyncio
    async def test_list(self, mock_ctx):
        ws, _ = mock_ctx
        result = await file_tool(operation="list", path=".")
        parsed = json.loads(result)
        assert "entries" in parsed

    @pytest.mark.asyncio
    async def test_delete(self, mock_ctx):
        ws, _ = mock_ctx
        (ws / "deleteme.txt").write_text("bye")
        result = await file_tool(operation="delete", path="deleteme.txt")
        parsed = json.loads(result)
        assert parsed["ok"] is True
        assert not (ws / "deleteme.txt").exists()

    @pytest.mark.asyncio
    async def test_mkdir(self, mock_ctx):
        ws, _ = mock_ctx
        result = await file_tool(operation="mkdir", path="newdir")
        parsed = json.loads(result)
        assert parsed["ok"] is True
        assert (ws / "newdir").is_dir()

    @pytest.mark.asyncio
    async def test_no_bot_context(self):
        with patch("app.tools.local.file_ops._get_bot_and_workspace_root") as mock_get:
            mock_get.return_value = (None, None, None)
            result = await file_tool(operation="read", path="hello.txt")
            parsed = json.loads(result)
            assert "error" in parsed

    @pytest.mark.asyncio
    async def test_traversal_blocked(self, mock_ctx):
        result = await file_tool(operation="read", path="../../etc/passwd")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "escapes" in parsed["error"]

    @pytest.mark.asyncio
    async def test_unknown_operation(self, mock_ctx):
        result = await file_tool(operation="foobar", path="hello.txt")
        parsed = json.loads(result)
        assert "error" in parsed


# ---------------------------------------------------------------------------
# Cross-workspace channel access
# ---------------------------------------------------------------------------


class TestCrossWorkspaceAccess:
    """Test that bots with cross_workspace_access can read/write other bots' channel workspaces."""

    CHANNEL_ID = "131f42b0-a7a4-5be5-848d-04fed708cd6a"

    @pytest.fixture
    def cross_ws(self, tmp_path):
        """Build two separate bot workspace trees:
        - orchestrator at {tmp}/orchestrator/
        - baking-bot at {tmp}/baking-bot/channels/{CHANNEL_ID}/
        """
        orch_root = tmp_path / "orchestrator"
        orch_root.mkdir()
        (orch_root / "channels" / "orch-channel").mkdir(parents=True)

        baking_root = tmp_path / "baking-bot"
        (baking_root / "channels" / self.CHANNEL_ID).mkdir(parents=True)
        (baking_root / "channels" / self.CHANNEL_ID / "recipe.md").write_text("# Sourdough\n")

        return tmp_path

    def _orch_bot(self):
        bot = _mock_bot("", bot_id="orchestrator")
        bot.cross_workspace_access = True
        return bot

    def _baking_bot(self, ws_root):
        bot = _mock_bot(ws_root, bot_id="baking-bot")
        bot.cross_workspace_access = False
        return bot

    @pytest.mark.asyncio
    async def test_resolve_cross_channel_switches_ws_root(self, cross_ws):
        """_maybe_resolve_cross_channel should return the owning bot's ws_root."""
        orch_root = str(cross_ws / "orchestrator")
        baking_root = str(cross_ws / "baking-bot")
        orch_bot = self._orch_bot()
        baking_bot = self._baking_bot(baking_root)

        with patch("app.tools.local.channel_workspace._resolve_channel_owner_bot") as mock_resolve:
            mock_resolve.return_value = baking_bot
            with patch("app.services.channel_workspace._get_ws_root", return_value=baking_root):

                effective_root, effective_bot = await _maybe_resolve_cross_channel(
                    f"/workspace/channels/{self.CHANNEL_ID}/recipe.md",
                    orch_bot, orch_root,
                )

        assert effective_root == baking_root
        assert effective_bot.id == "baking-bot"

    @pytest.mark.asyncio
    async def test_resolve_cross_channel_same_bot_no_switch(self, cross_ws):
        """When channel belongs to the calling bot, no switch occurs."""
        orch_root = str(cross_ws / "orchestrator")
        orch_bot = self._orch_bot()

        with patch("app.tools.local.channel_workspace._resolve_channel_owner_bot") as mock_resolve:
            mock_resolve.return_value = None  # same bot

            effective_root, effective_bot = await _maybe_resolve_cross_channel(
                f"/workspace/channels/{self.CHANNEL_ID}/file.md",
                orch_bot, orch_root,
            )

        assert effective_root == orch_root
        assert effective_bot.id == "orchestrator"

    @pytest.mark.asyncio
    async def test_resolve_cross_channel_no_flag(self, cross_ws):
        """Bot without cross_workspace_access never switches."""
        baking_root = str(cross_ws / "baking-bot")
        bot = self._baking_bot(baking_root)

        effective_root, effective_bot = await _maybe_resolve_cross_channel(
            f"/workspace/channels/{self.CHANNEL_ID}/recipe.md",
            bot, baking_root,
        )

        assert effective_root == baking_root
        assert effective_bot.id == "baking-bot"

    @pytest.mark.asyncio
    async def test_resolve_non_channel_path_no_switch(self, cross_ws):
        """Non-channel paths are never switched, even with cross_workspace_access."""
        orch_root = str(cross_ws / "orchestrator")
        orch_bot = self._orch_bot()

        effective_root, _ = await _maybe_resolve_cross_channel(
            "/workspace/memory/MEMORY.md", orch_bot, orch_root,
        )
        assert effective_root == orch_root

    @pytest.mark.asyncio
    async def test_file_tool_cross_channel_read(self, cross_ws):
        """End-to-end: orchestrator reads a file in baking-bot's channel workspace."""
        orch_root = str(cross_ws / "orchestrator")
        baking_root = str(cross_ws / "baking-bot")
        orch_bot = self._orch_bot()
        baking_bot = self._baking_bot(baking_root)

        def _mock_ws_root(bot_id, bot=None):
            return orch_root if bot_id == "orchestrator" else baking_root

        with patch("app.tools.local.file_ops._get_bot_and_workspace_root") as mock_get:
            mock_get.return_value = (orch_bot, "orchestrator", orch_root)
            with patch("app.tools.local.channel_workspace._resolve_channel_owner_bot") as mock_resolve:
                mock_resolve.return_value = baking_bot
                with patch("app.services.channel_workspace._get_ws_root", return_value=baking_root):
                    with patch("app.services.workspace.WorkspaceService.get_workspace_root", side_effect=_mock_ws_root):

                        result = await file_tool(
                            operation="read",
                            path=f"/workspace/channels/{self.CHANNEL_ID}/recipe.md",
                        )

        assert "Sourdough" in result

    @pytest.mark.asyncio
    async def test_file_tool_cross_channel_list(self, cross_ws):
        """End-to-end: orchestrator lists another bot's channel directory."""
        orch_root = str(cross_ws / "orchestrator")
        baking_root = str(cross_ws / "baking-bot")
        orch_bot = self._orch_bot()
        baking_bot = self._baking_bot(baking_root)

        def _mock_ws_root(bot_id, bot=None):
            return orch_root if bot_id == "orchestrator" else baking_root

        with patch("app.tools.local.file_ops._get_bot_and_workspace_root") as mock_get:
            mock_get.return_value = (orch_bot, "orchestrator", orch_root)
            with patch("app.tools.local.channel_workspace._resolve_channel_owner_bot") as mock_resolve:
                mock_resolve.return_value = baking_bot
                with patch("app.services.channel_workspace._get_ws_root", return_value=baking_root):
                    with patch("app.services.workspace.WorkspaceService.get_workspace_root", side_effect=_mock_ws_root):

                        result = await file_tool(
                            operation="list",
                            path=f"/workspace/channels/{self.CHANNEL_ID}",
                        )

        parsed = json.loads(result)
        assert "entries" in parsed
        names = [e["name"] for e in parsed["entries"]]
        assert "recipe.md" in names

    @pytest.mark.asyncio
    async def test_file_tool_cross_channel_write(self, cross_ws):
        """End-to-end: orchestrator writes to another bot's channel workspace."""
        orch_root = str(cross_ws / "orchestrator")
        baking_root = str(cross_ws / "baking-bot")
        orch_bot = self._orch_bot()
        baking_bot = self._baking_bot(baking_root)

        def _mock_ws_root(bot_id, bot=None):
            return orch_root if bot_id == "orchestrator" else baking_root

        with patch("app.tools.local.file_ops._get_bot_and_workspace_root") as mock_get:
            mock_get.return_value = (orch_bot, "orchestrator", orch_root)
            with patch("app.tools.local.channel_workspace._resolve_channel_owner_bot") as mock_resolve:
                mock_resolve.return_value = baking_bot
                with patch("app.services.channel_workspace._get_ws_root", return_value=baking_root):
                    with patch("app.services.workspace.WorkspaceService.get_workspace_root", side_effect=_mock_ws_root):

                        result = await file_tool(
                            operation="write",
                            path=f"/workspace/channels/{self.CHANNEL_ID}/notes.md",
                            content="# Notes\nNew note from orchestrator",
                        )

        parsed = json.loads(result)
        assert parsed["ok"] is True
        written = (cross_ws / "baking-bot" / "channels" / self.CHANNEL_ID / "notes.md").read_text()
        assert "orchestrator" in written
