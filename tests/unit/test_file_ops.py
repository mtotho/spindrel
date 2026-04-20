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
    _op_create,
    _op_overwrite,
    _op_json_patch,
    _op_history,
    _op_restore,
    _op_append,
    _op_edit,
    _op_list,
    _op_delete,
    _op_mkdir,
    _op_move,
    _op_grep,
    _op_glob,
    _normalize_include,
    _whitespace_flex_pattern,
    _find_closest_hint,
    _save_backup,
    _note_read,
    _RECENT_READS,
    _retention_for,
    file as file_tool,
    MAX_CONTENT_BYTES,
    MAX_READ_LINES,
    DEFAULT_READ_LINES,
    DEFAULT_GREP_MATCHES,
    GREP_LINE_MAX_CHARS,
    MAX_GREP_FILE_BYTES,
    MAX_BACKUP_VERSIONS,
    MAX_BACKUP_VERSIONS_DEFAULT,
    MAX_BACKUP_VERSIONS_DATA,
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


class TestResolvePathWidgetUri:
    """widget:// virtual paths resolve outside the normal workspace boundary.

    Phase 1b of the Widget Library track: ``widget://core/<name>/...`` points
    at the in-repo core library (read-only at dispatch time), while
    ``widget://bot/<name>/...`` and ``widget://workspace/<name>/...`` resolve
    under the corresponding workspace's ``.widget_library/`` dir.
    """

    def test_widget_bot_uri_resolves_under_ws_widget_library(self, ws):
        result = _resolve_path("widget://bot/my_widget/index.html", str(ws))
        assert result == os.path.realpath(
            str(ws / ".widget_library" / "my_widget" / "index.html")
        )

    def test_widget_core_uri_resolves_to_in_repo_dir(self, ws):
        result = _resolve_path("widget://core/notes/index.html", str(ws))
        assert result.endswith("/widgets/notes/index.html")
        # Lives under the in-repo tree, not the bot workspace.
        assert "/app/tools/local/widgets/" in result

    def test_widget_workspace_uri_requires_shared_workspace(self, ws):
        bot = _mock_bot(str(ws), workspace_type="host")  # no shared_workspace_id
        with pytest.raises(ValueError, match="shared workspace"):
            _resolve_path("widget://workspace/foo/index.html", str(ws), bot)

    def test_widget_bot_traversal_blocked(self, ws):
        with pytest.raises(ValueError, match="escapes bundle"):
            _resolve_path("widget://bot/foo/../bar", str(ws))


class TestFileToolWidgetUri:
    """End-to-end: the `file` tool honors widget:// URIs, enforces core's
    read-only status, and lets a bot author a bundle that widget_library_list
    can then discover."""

    @pytest.fixture
    def bot_ctx(self, ws):
        from app.agent.context import current_bot_id
        bot = _mock_bot(str(ws), workspace_type="host", bot_id="crumb")
        token = current_bot_id.set("crumb")
        with patch("app.agent.bots.get_bot", return_value=bot), \
             patch("app.services.workspace.workspace_service.get_workspace_root", return_value=str(ws)):
            yield bot
        current_bot_id.reset(token)

    @pytest.mark.asyncio
    async def test_create_under_widget_bot_scope(self, ws, bot_ctx):
        result = await file_tool(
            operation="create",
            path="widget://bot/my_toggle/index.html",
            content="<div>toggle</div>",
        )
        parsed = json.loads(result)
        assert parsed.get("ok") is True
        on_disk = ws / ".widget_library" / "my_toggle" / "index.html"
        assert on_disk.read_text() == "<div>toggle</div>"

    @pytest.mark.asyncio
    async def test_create_under_widget_core_scope_blocked(self, ws, bot_ctx):
        result = await file_tool(
            operation="create",
            path="widget://core/hacked/index.html",
            content="evil",
        )
        parsed = json.loads(result)
        assert "error" in parsed
        assert "read-only" in parsed["error"]

    @pytest.mark.asyncio
    async def test_read_from_widget_core_scope_allowed(self, ws, bot_ctx):
        # Read is allowed — bots can study core widgets as examples.
        # Uses the real in-repo `notes` widget.
        result = await file_tool(
            operation="read",
            path="widget://core/notes/index.html",
        )
        parsed = json.loads(result)
        # Either returned the envelope (wrapped) or the raw numbered text —
        # both branches signal a successful read.
        assert "error" not in parsed

    @pytest.mark.asyncio
    async def test_move_into_widget_core_blocked(self, ws, bot_ctx):
        # First create a bot-scope file, then try to move it INTO core.
        (ws / ".widget_library" / "tmp").mkdir(parents=True)
        (ws / ".widget_library" / "tmp" / "index.html").write_text("<x/>")
        result = await file_tool(
            operation="move",
            path="widget://bot/tmp/index.html",
            destination="widget://core/injected/index.html",
        )
        parsed = json.loads(result)
        assert "error" in parsed
        assert "read-only" in parsed["error"]


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
# Create / Overwrite — exercising the file-writing surface
# ---------------------------------------------------------------------------


class TestFileWriting:
    def test_create_new_file(self, ws):
        path = str(ws / "new.txt")
        result = json.loads(_op_create(path, "hello"))
        assert result["ok"] is True
        assert Path(path).read_text() == "hello"

    def test_create_creates_parent_dirs(self, ws):
        path = str(ws / "a" / "b" / "c.txt")
        result = json.loads(_op_create(path, "deep"))
        assert result["ok"] is True
        assert Path(path).read_text() == "deep"

    def test_overwrite_replaces_existing(self, ws):
        path = str(ws / "hello.txt")
        _note_read("bot-a", path)
        _op_overwrite(path, "replaced", bot_id="bot-a")
        assert Path(path).read_text() == "replaced"

    def test_create_no_content(self, ws):
        result = json.loads(_op_create(str(ws / "x.txt"), None))
        assert "error" in result

    def test_create_size_limit(self, ws):
        big = "x" * (MAX_CONTENT_BYTES + 1)
        result = json.loads(_op_create(str(ws / "big.txt"), big))
        assert "error" in result
        assert "limit" in result["error"]

    def test_create_shell_metacharacters(self, ws):
        """Content with shell metacharacters should be written verbatim."""
        content = "Bennie's last $HOME run `backtick` $(cmd) && rm -rf /"
        path = str(ws / "meta.txt")
        _op_create(path, content)
        assert Path(path).read_text() == content

    def test_create_apostrophe(self, ws):
        """The original bug: apostrophe in content."""
        content = "Bennie's last visit was great. She'll be back."
        path = str(ws / "notes.md")
        _op_create(path, content)
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

    def test_edit_file_not_found(self, ws):
        result = json.loads(_op_edit(str(ws / "nope.txt"), "a", "b", False))
        assert "error" in result

    def test_edit_no_find(self, ws):
        result = json.loads(_op_edit(str(ws / "hello.txt"), None, "x", False))
        assert "error" in result

    def test_edit_no_replace(self, ws):
        result = json.loads(_op_edit(str(ws / "hello.txt"), "Hello", None, False))
        assert "error" in result

    # --- Whitespace-normalized matching ---

    def test_edit_ws_flex_leading_trailing_spaces(self, ws):
        """Extra leading/trailing whitespace in find still matches."""
        path = str(ws / "hello.txt")
        result = json.loads(_op_edit(path, "  Hello world  ", "Goodbye", False))
        assert result["ok"] is True
        assert result["matched"] == "whitespace-normalized"
        assert "Goodbye" in Path(path).read_text()

    def test_edit_ws_flex_extra_spaces(self, ws):
        """Multiple spaces collapsed to single space in matching."""
        path = str(ws / "multi.txt")
        Path(path).write_text("key:   value   here\n")
        result = json.loads(_op_edit(path, "key: value here", "replaced", False))
        assert result["ok"] is True
        assert result["matched"] == "whitespace-normalized"
        assert Path(path).read_text() == "replaced\n"

    def test_edit_ws_flex_tabs_vs_spaces(self, ws):
        """Tab characters match spaces."""
        path = str(ws / "tabs.txt")
        Path(path).write_text("col1\tcol2\tcol3\n")
        result = json.loads(_op_edit(path, "col1 col2 col3", "replaced", False))
        assert result["ok"] is True
        assert result["matched"] == "whitespace-normalized"

    def test_edit_ws_flex_newline_differences(self, ws):
        """Find with newlines matches text with different whitespace."""
        path = str(ws / "lines.txt")
        Path(path).write_text("line one\nline two\nline three\n")
        # LLM sends find with extra space instead of newline
        result = json.loads(_op_edit(path, "line one line two", "merged", False))
        assert result["ok"] is True
        assert result["matched"] == "whitespace-normalized"
        assert Path(path).read_text() == "merged\nline three\n"

    def test_edit_ws_flex_replace_all(self, ws):
        """Whitespace-flex works with replace_all."""
        path = str(ws / "rall.txt")
        Path(path).write_text("a  b\nc  d\na  b\n")
        result = json.loads(_op_edit(path, "a b", "X", replace_all=True))
        assert result["ok"] is True
        assert result["replacements"] == 2
        assert result["matched"] == "whitespace-normalized"

    def test_edit_ws_flex_exact_preferred(self, ws):
        """Exact match is used when available (no 'matched' key)."""
        path = str(ws / "hello.txt")
        result = json.loads(_op_edit(path, "Hello world", "Goodbye", False))
        assert result["ok"] is True
        assert "matched" not in result

    def test_edit_ws_flex_preserves_non_ws_precision(self, ws):
        """Whitespace-flex does NOT match different words."""
        path = str(ws / "hello.txt")
        result = json.loads(_op_edit(path, "Hello earth", "x", False))
        assert "error" in result

    def test_edit_ws_flex_rejects_runaway_span(self, ws):
        """Whitespace-flex rejects matches that span far more text than find."""
        path = str(ws / "spread.txt")
        # Tokens "alpha" and "beta" appear but separated by tons of blank lines
        Path(path).write_text("alpha" + "\n" * 500 + "beta\n")
        result = json.loads(_op_edit(path, "alpha beta", "x", False))
        assert "error" in result

    # --- Closest-match hints ---

    def test_edit_closest_match_hint(self, ws):
        """When nothing matches, error shows closest text from file."""
        path = str(ws / "plants.txt")
        Path(path).write_text(
            "- First germination: chamomile and thyme have emerged.\n"
            "- Seedlings look healthy.\n"
        )
        result = json.loads(_op_edit(
            path,
            "- First germination: chamomile and thyme have appeared.",
            "replaced",
            False,
        ))
        assert "error" in result
        assert "closest matching text" in result["error"].lower()
        # The hint should contain the actual file text
        assert "emerged" in result["error"]

    def test_edit_no_hint_for_unrelated_text(self, ws):
        """No hint when find is completely unrelated to file content."""
        path = str(ws / "hello.txt")
        result = json.loads(_op_edit(path, "quantum flux capacitor", "x", False))
        assert "error" in result
        assert "closest" not in result["error"].lower()


class TestOpEditAutoRecovery:
    """Tests for LLM-friendly auto-recovery when edit is called with wrong params."""

    def test_edit_content_no_find_routes_to_overwrite(self, ws):
        """edit with content but no find routes to overwrite — requires prior read."""
        path = str(ws / "hello.txt")
        # Without a prior read, the overwrite precondition blocks the write
        result = json.loads(_op_edit(path, None, None, False, content="new content",
                                     bot_id="bot-a"))
        assert "error" in result
        assert "read" in result["error"].lower()
        # With a prior read, the auto-recover succeeds
        _note_read("bot-a", path)
        result = json.loads(_op_edit(path, None, None, False, content="new content",
                                     bot_id="bot-a"))
        assert result["ok"] is True
        assert Path(path).read_text() == "new content"

    def test_edit_content_and_same_replace_routes_to_overwrite(self, ws):
        """edit with content == replace (confused LLM) routes to overwrite."""
        path = str(ws / "hello.txt")
        _note_read("bot-a", path)
        result = json.loads(_op_edit(path, None, "same text", False, content="same text",
                                     bot_id="bot-a"))
        assert result["ok"] is True
        assert Path(path).read_text() == "same text"

    def test_edit_content_as_find_when_replace_differs(self, ws):
        """edit with content (old) + replace (new) but no find should treat content as find."""
        path = str(ws / "hello.txt")
        result = json.loads(_op_edit(path, None, "Goodbye world", False, content="Hello world"))
        assert result["ok"] is True
        assert "Goodbye world" in Path(path).read_text()

    def test_edit_content_as_find_not_found(self, ws):
        """content-as-find that doesn't match should return not-found error."""
        path = str(ws / "hello.txt")
        result = json.loads(_op_edit(path, None, "replacement", False, content="NONEXISTENT"))
        assert "error" in result
        assert "not found" in result["error"]

    def test_edit_no_find_no_content(self, ws):
        """edit with neither find nor content should return error."""
        path = str(ws / "hello.txt")
        result = json.loads(_op_edit(path, None, "x", False))
        assert "error" in result
        assert "find is required" in result["error"]
        # The error should point at overwrite / json_patch, not at `edit` alone
        assert "overwrite" in result["error"] or "json_patch" in result["error"]

    def test_edit_find_provided_content_ignored(self, ws):
        """When find is provided, content parameter is ignored (normal path)."""
        path = str(ws / "hello.txt")
        result = json.loads(_op_edit(path, "Hello world", "Goodbye", False, content="ignored"))
        assert result["ok"] is True
        assert "Goodbye" in Path(path).read_text()

    def test_edit_no_find_no_replace_with_content_routes_to_overwrite(self, ws):
        """edit with only content (no find, no replace) routes to overwrite (requires read)."""
        path = str(ws / "memory" / "MEMORY.md")
        new_content = "# Updated Memory\n\n## New Facts\n- Fact A\n"
        _note_read("bot-a", path)
        result = json.loads(_op_edit(path, None, None, False, content=new_content,
                                     bot_id="bot-a"))
        assert result["ok"] is True
        assert Path(path).read_text() == new_content

    def test_edit_content_fallback_to_replace_when_find_given(self, ws):
        """When find is given but replace is None, content is used as replace."""
        path = str(ws / "hello.txt")
        result = json.loads(_op_edit(path, "Hello world", None, False, content="Goodbye world"))
        assert result["ok"] is True
        assert "Goodbye world" in Path(path).read_text()


class TestWhitespaceFlexPattern:
    def test_basic_pattern(self):
        pat = _whitespace_flex_pattern("hello world")
        assert pat is not None
        assert pat.search("hello  world") is not None
        assert pat.search("hello\tworld") is not None
        assert pat.search("hello\nworld") is not None

    def test_empty_string(self):
        assert _whitespace_flex_pattern("") is None
        assert _whitespace_flex_pattern("   ") is None

    def test_single_token(self):
        pat = _whitespace_flex_pattern("hello")
        assert pat is not None
        assert pat.search("hello") is not None

    def test_regex_chars_escaped(self):
        """Special regex characters in find are escaped."""
        pat = _whitespace_flex_pattern("price: $10.00 (USD)")
        assert pat is not None
        assert pat.search("price:  $10.00  (USD)") is not None
        # Should NOT match different text
        assert pat.search("price: X10Y00 ZUSDZ") is None


class TestFindClosestHint:
    def test_similar_line(self):
        text = "The quick brown fox jumps over the lazy dog\n"
        hint = _find_closest_hint("The quick brown fox jumps over the lazy cat", text)
        assert "quick brown fox" in hint

    def test_no_match(self):
        text = "Hello world\n"
        hint = _find_closest_hint("quantum flux capacitor", text)
        assert hint == ""

    def test_empty_inputs(self):
        assert _find_closest_hint("", "hello") == ""
        assert _find_closest_hint("hello", "") == ""


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
# Move
# ---------------------------------------------------------------------------


class TestOpMove:
    @pytest.mark.asyncio
    async def test_move_file(self, ws):
        src = str(ws / "hello.txt")
        dest = str(ws / "moved.txt")
        bot = _mock_bot(str(ws))
        result = json.loads(await _op_move(src, "moved.txt", str(ws), bot))
        assert result["ok"] is True
        assert not os.path.exists(src)
        assert os.path.isfile(dest)
        assert Path(dest).read_text() == "Hello world\n"

    @pytest.mark.asyncio
    async def test_move_into_directory(self, ws):
        """Moving a file into an existing directory (like mv)."""
        (ws / "target_dir").mkdir()
        src = str(ws / "hello.txt")
        bot = _mock_bot(str(ws))
        result = json.loads(await _op_move(src, "target_dir", str(ws), bot))
        assert result["ok"] is True
        assert os.path.isfile(str(ws / "target_dir" / "hello.txt"))
        assert not os.path.exists(src)

    @pytest.mark.asyncio
    async def test_move_creates_parent_dirs(self, ws):
        src = str(ws / "hello.txt")
        bot = _mock_bot(str(ws))
        result = json.loads(await _op_move(src, "a/b/moved.txt", str(ws), bot))
        assert result["ok"] is True
        assert os.path.isfile(str(ws / "a" / "b" / "moved.txt"))

    @pytest.mark.asyncio
    async def test_move_no_destination(self, ws):
        src = str(ws / "hello.txt")
        bot = _mock_bot(str(ws))
        result = json.loads(await _op_move(src, None, str(ws), bot))
        assert "error" in result
        assert "destination" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_move_source_not_found(self, ws):
        bot = _mock_bot(str(ws))
        result = json.loads(await _op_move(str(ws / "nope.txt"), "dest.txt", str(ws), bot))
        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_move_dest_already_exists(self, ws):
        (ws / "existing.txt").write_text("taken")
        src = str(ws / "hello.txt")
        bot = _mock_bot(str(ws))
        result = json.loads(await _op_move(src, "existing.txt", str(ws), bot))
        assert "error" in result
        assert "already exists" in result["error"].lower()
        # Source should still exist
        assert os.path.exists(src)

    @pytest.mark.asyncio
    async def test_move_directory(self, ws):
        """Can move entire directories."""
        src = str(ws / "subdir")
        bot = _mock_bot(str(ws))
        result = json.loads(await _op_move(src, "renamed_dir", str(ws), bot))
        assert result["ok"] is True
        assert os.path.isdir(str(ws / "renamed_dir"))
        assert os.path.isfile(str(ws / "renamed_dir" / "nested.md"))
        assert not os.path.exists(src)


# ---------------------------------------------------------------------------
# Grep
# ---------------------------------------------------------------------------


@pytest.fixture
def grep_ws(tmp_path):
    """Workspace seeded with a small tree for grep/glob tests."""
    (tmp_path / "app.py").write_text(
        "def handler():\n    return 'hello world'\n\ndef other():\n    pass\n"
    )
    (tmp_path / "README.md").write_text("# Project\n\nUses the `handler` function.\n")
    sub = tmp_path / "src" / "pkg"
    sub.mkdir(parents=True)
    (sub / "deep.py").write_text("class Handler:\n    pass\n\ndef make_handler():\n    return Handler()\n")
    (sub / "notes.md").write_text("deep notes here\n")
    # Junk dirs — must be pruned
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\nhandler\n")
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text("function handler() {}\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "cached.pyc").write_text("handler bytecode\n")
    # Binary file — grep must skip
    (tmp_path / "blob.bin").write_bytes(b"handler\x00\x00binary content\n")
    return tmp_path


class TestOpGrep:
    def test_grep_literal_match(self, grep_ws):
        result = json.loads(_op_grep(str(grep_ws), "handler", None, str(grep_ws), None))
        assert result["count"] >= 3
        files = {m["file"] for m in result["matches"]}
        assert "app.py" in files
        assert "README.md" in files
        # Recurses into src/pkg/
        assert any(f.endswith("deep.py") for f in files)

    def test_grep_regex(self, grep_ws):
        # Match def-name pattern
        result = json.loads(_op_grep(str(grep_ws), r"def \w+_handler", None, str(grep_ws), None))
        assert result["count"] == 1
        m = result["matches"][0]
        assert m["file"].endswith("deep.py")
        assert "make_handler" in m["text"]

    def test_grep_returns_line_numbers(self, grep_ws):
        result = json.loads(_op_grep(str(grep_ws), "handler", None, str(grep_ws), None))
        app_matches = [m for m in result["matches"] if m["file"] == "app.py"]
        assert app_matches
        assert app_matches[0]["line"] == 1

    def test_grep_skips_junk_dirs(self, grep_ws):
        result = json.loads(_op_grep(str(grep_ws), "handler", None, str(grep_ws), None))
        files = {m["file"] for m in result["matches"]}
        # None of the junk-dir hits should appear
        assert not any(".git" in f for f in files)
        assert not any("node_modules" in f for f in files)
        assert not any("__pycache__" in f for f in files)

    def test_grep_skips_binary(self, grep_ws):
        result = json.loads(_op_grep(str(grep_ws), "handler", None, str(grep_ws), None))
        assert not any("blob.bin" in m["file"] for m in result["matches"])

    def test_grep_include_filter(self, grep_ws):
        result = json.loads(_op_grep(str(grep_ws), "handler", "*.py", str(grep_ws), None))
        files = {m["file"] for m in result["matches"]}
        assert all(f.endswith(".py") for f in files)
        assert "README.md" not in files

    def test_grep_single_file_root(self, grep_ws):
        result = json.loads(_op_grep(str(grep_ws / "app.py"), "handler", None, str(grep_ws), None))
        assert result["count"] == 1
        assert result["matches"][0]["file"] == "app.py"

    def test_grep_no_matches(self, grep_ws):
        result = json.loads(_op_grep(str(grep_ws), "zzznevermatches", None, str(grep_ws), None))
        assert result["count"] == 0
        assert result["matches"] == []

    def test_grep_invalid_regex(self, grep_ws):
        result = json.loads(_op_grep(str(grep_ws), "[unclosed", None, str(grep_ws), None))
        assert "error" in result
        assert "regex" in result["error"].lower()

    def test_grep_missing_pattern(self, grep_ws):
        result = json.loads(_op_grep(str(grep_ws), None, None, str(grep_ws), None))
        assert "error" in result
        assert "pattern" in result["error"].lower()

    def test_grep_nonexistent_path(self, grep_ws):
        result = json.loads(_op_grep(str(grep_ws / "nope"), "handler", None, str(grep_ws), None))
        assert "error" in result

    def test_grep_limit_truncates(self, grep_ws):
        # Seed a file with many matches
        (grep_ws / "many.txt").write_text("\n".join(["hit"] * 50) + "\n")
        result = json.loads(_op_grep(str(grep_ws / "many.txt"), "hit", None, str(grep_ws), 10))
        assert result["count"] == 10
        assert result["truncated"] is True

    def test_grep_include_strips_recursive_prefix(self, grep_ws):
        """Bots habitually write include='**/*.py' — treat it as '*.py'."""
        result = json.loads(_op_grep(str(grep_ws), "handler", "**/*.py", str(grep_ws), None))
        files = {m["file"] for m in result["matches"]}
        assert files, "include='**/*.py' should match .py files, not zero results"
        assert all(f.endswith(".py") for f in files)

    def test_grep_limit_zero_returns_empty(self, grep_ws):
        """limit=0 means 'I want no results' — don't coerce to DEFAULT."""
        result = json.loads(_op_grep(str(grep_ws), "handler", None, str(grep_ws), 0))
        assert result["count"] == 0
        assert result["matches"] == []

    def test_grep_skips_files_over_size_cap(self, grep_ws, monkeypatch):
        """Huge files are skipped to protect context + runtime."""
        huge = grep_ws / "huge.txt"
        monkeypatch.setattr("app.tools.local.file_ops.MAX_GREP_FILE_BYTES", 100)
        huge.write_text("handler " * 200)  # > 100 bytes
        result = json.loads(_op_grep(str(grep_ws), "handler", None, str(grep_ws), None))
        assert not any("huge.txt" in m["file"] for m in result["matches"])
        assert result.get("files_skipped_large", 0) >= 1

    def test_grep_symlink_escape_blocked(self, grep_ws, tmp_path_factory):
        """A symlink inside the workspace pointing OUTSIDE must be ignored."""
        # Use a factory-created dir so it's a genuine sibling of grep_ws.
        elsewhere = tmp_path_factory.mktemp("outside")
        secret = elsewhere / "outside_secret.txt"
        secret.write_text("handler secret\n")
        link = grep_ws / "link_to_outside.txt"
        try:
            os.symlink(str(secret), str(link))
        except (OSError, NotImplementedError):
            pytest.skip("Platform does not support symlinks")
        result = json.loads(_op_grep(str(grep_ws), "handler", None, str(grep_ws), None))
        assert not any("link_to_outside.txt" in m["file"] for m in result["matches"])
        assert not any("outside_secret" in m.get("text", "") for m in result["matches"])

    def test_grep_long_line_truncated(self, grep_ws):
        long_line = "x" * (GREP_LINE_MAX_CHARS + 200) + "needle" + "y" * 100
        (grep_ws / "wide.txt").write_text(long_line + "\n")
        result = json.loads(_op_grep(str(grep_ws / "wide.txt"), "needle", None, str(grep_ws), None))
        assert result["count"] == 1
        # Text is capped; trailing ellipsis marker present
        assert len(result["matches"][0]["text"]) <= GREP_LINE_MAX_CHARS + 1
        assert result["matches"][0]["text"].endswith("…")


# ---------------------------------------------------------------------------
# Glob
# ---------------------------------------------------------------------------


class TestOpGlob:
    def test_glob_recursive_py(self, grep_ws):
        result = json.loads(_op_glob(str(grep_ws), "**/*.py", str(grep_ws), None))
        paths = set(result["paths"])
        assert "app.py" in paths
        assert any(p.endswith("deep.py") for p in paths)

    def test_glob_flat_pattern(self, grep_ws):
        result = json.loads(_op_glob(str(grep_ws), "*.py", str(grep_ws), None))
        assert "app.py" in result["paths"]
        # Flat *.py shouldn't recurse
        assert not any("deep.py" in p for p in result["paths"])

    def test_glob_skips_junk_dirs(self, grep_ws):
        result = json.loads(_op_glob(str(grep_ws), "**/*", str(grep_ws), None))
        paths = result["paths"]
        assert not any(".git" in p for p in paths)
        assert not any("node_modules" in p for p in paths)
        assert not any("__pycache__" in p for p in paths)

    def test_glob_no_matches(self, grep_ws):
        result = json.loads(_op_glob(str(grep_ws), "**/*.xyz", str(grep_ws), None))
        assert result["count"] == 0
        assert result["paths"] == []

    def test_glob_sorted_by_mtime(self, grep_ws):
        import time
        (grep_ws / "old.py").write_text("old\n")
        time.sleep(0.01)
        (grep_ws / "new.py").write_text("new\n")
        # Ensure mtimes differ enough
        os.utime(grep_ws / "old.py", (1_600_000_000, 1_600_000_000))
        os.utime(grep_ws / "new.py", (1_700_000_000, 1_700_000_000))
        result = json.loads(_op_glob(str(grep_ws), "*.py", str(grep_ws), None))
        paths = result["paths"]
        assert paths.index("new.py") < paths.index("old.py")

    def test_glob_missing_pattern(self, grep_ws):
        result = json.loads(_op_glob(str(grep_ws), None, str(grep_ws), None))
        assert "error" in result
        assert "pattern" in result["error"].lower()

    def test_glob_not_a_directory(self, grep_ws):
        result = json.loads(_op_glob(str(grep_ws / "app.py"), "*.py", str(grep_ws), None))
        assert "error" in result
        assert "director" in result["error"].lower()

    def test_glob_limit_truncates(self, grep_ws):
        for i in range(20):
            (grep_ws / f"gen_{i}.tmp").write_text(str(i))
        result = json.loads(_op_glob(str(grep_ws), "gen_*.tmp", str(grep_ws), 5))
        assert result["count"] == 5
        assert result["truncated"] is True

    def test_glob_limit_returns_newest_not_walk_order(self, grep_ws):
        """limit=N must return the N most-recently-modified — not walk order.

        Regression: previous impl broke on max_results *before* sorting by
        mtime, so the returned set was the first N encountered in directory
        order, then sorted among themselves.
        """
        # Create 10 files with interleaved mtimes.
        # The "newest" 3 should be new_0, new_1, new_2 (distinctly newest).
        for i in range(7):
            p = grep_ws / f"old_{i}.tmp"
            p.write_text("old")
            os.utime(p, (1_600_000_000 + i, 1_600_000_000 + i))
        newest_names = []
        for i in range(3):
            p = grep_ws / f"new_{i}.tmp"
            p.write_text("new")
            os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))
            newest_names.append(p.name)

        result = json.loads(_op_glob(str(grep_ws), "*.tmp", str(grep_ws), 3))
        returned = set(result["paths"])
        assert returned == set(newest_names), (
            f"expected the 3 newest files, got {returned}"
        )
        assert result["truncated"] is True

    def test_glob_limit_zero_returns_empty(self, grep_ws):
        result = json.loads(_op_glob(str(grep_ws), "**/*.py", str(grep_ws), 0))
        assert result["count"] == 0
        assert result["paths"] == []

    def test_glob_symlink_escape_blocked(self, grep_ws, tmp_path_factory):
        """Glob must not return symlinks pointing outside the workspace."""
        elsewhere = tmp_path_factory.mktemp("glob_outside")
        outside = elsewhere / "outside.py"
        outside.write_text("# outside\n")
        link = grep_ws / "escape.py"
        try:
            os.symlink(str(outside), str(link))
        except (OSError, NotImplementedError):
            pytest.skip("Platform does not support symlinks")
        result = json.loads(_op_glob(str(grep_ws), "*.py", str(grep_ws), None))
        assert not any("escape.py" in p for p in result["paths"])


# ---------------------------------------------------------------------------
# _normalize_include
# ---------------------------------------------------------------------------


class TestNormalizeInclude:
    def test_strips_recursive_prefix(self):
        assert _normalize_include("**/*.py") == "*.py"

    def test_strips_single_segment_prefix(self):
        assert _normalize_include("*/test_*.py") == "test_*.py"

    def test_strips_chained_prefixes(self):
        assert _normalize_include("**/**/*.py") == "*.py"

    def test_plain_basename_unchanged(self):
        assert _normalize_include("*.py") == "*.py"
        assert _normalize_include("test_*.md") == "test_*.md"

    def test_none_passthrough(self):
        assert _normalize_include(None) is None

    def test_empty_passthrough(self):
        assert _normalize_include("") == ""


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
    async def test_create(self, mock_ctx):
        ws, _ = mock_ctx
        result = await file_tool(operation="create", path="out.txt", content="hi")
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
    async def test_move(self, mock_ctx):
        ws, _ = mock_ctx
        result = await file_tool(
            operation="move", path="hello.txt", destination="moved.txt",
        )
        parsed = json.loads(result)
        assert parsed["ok"] is True
        assert not (ws / "hello.txt").exists()
        assert (ws / "moved.txt").read_text() == "Hello world\n"

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

    @pytest.mark.asyncio
    async def test_grep_via_file_tool(self, mock_ctx):
        ws, _ = mock_ctx
        result = await file_tool(operation="grep", path=".", pattern="Hello")
        parsed = json.loads(result)
        assert parsed["count"] >= 1
        assert any(m["file"] == "hello.txt" for m in parsed["matches"])

    @pytest.mark.asyncio
    async def test_grep_via_file_tool_missing_pattern(self, mock_ctx):
        result = await file_tool(operation="grep", path=".")
        parsed = json.loads(result)
        assert "error" in parsed

    @pytest.mark.asyncio
    async def test_glob_via_file_tool(self, mock_ctx):
        ws, _ = mock_ctx
        result = await file_tool(operation="glob", path=".", pattern="**/*.md")
        parsed = json.loads(result)
        assert parsed["count"] >= 1
        assert any(p.endswith("MEMORY.md") for p in parsed["paths"])


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
                            operation="create",
                            path=f"/workspace/channels/{self.CHANNEL_ID}/notes.md",
                            content="# Notes\nNew note from orchestrator",
                        )

        parsed = json.loads(result)
        assert parsed["ok"] is True
        written = (cross_ws / "baking-bot" / "channels" / self.CHANNEL_ID / "notes.md").read_text()
        assert "orchestrator" in written


# ---------------------------------------------------------------------------
# Write-safety: versioned backups + size-drop guard
# ---------------------------------------------------------------------------


class TestBackupsAndHiding:
    """`.versions/` backup creation, pruning, and being hidden from bot-facing tools."""

    def test_backup_created_on_overwrite(self, ws):
        target = str(ws / "hello.txt")
        original = Path(target).read_text()
        _note_read("bot-a", target)
        _op_overwrite(target, "replacement content", bot_id="bot-a")
        versions_dir = ws / ".versions"
        backups = list(versions_dir.glob("hello.txt.*.bak"))
        assert len(backups) == 1
        assert backups[0].read_text() == original

    def test_backup_prunes_old_versions(self, ws):
        """Only MAX_BACKUP_VERSIONS backups are kept for non-data files."""
        target = str(ws / "hello.txt")
        import time as _time
        for i in range(MAX_BACKUP_VERSIONS + 3):
            Path(target).write_text(f"version {i}")
            _save_backup(target)
            _time.sleep(0.01)  # ensure distinct mtimes
        versions_dir = ws / ".versions"
        backups = list(versions_dir.glob("hello.txt.*.bak"))
        assert len(backups) == MAX_BACKUP_VERSIONS

    def test_no_backup_on_new_file(self, ws):
        target = str(ws / "brand_new.txt")
        _op_create(target, "hello")
        versions_dir = ws / ".versions"
        assert not versions_dir.exists()

    # `.versions/` must be hidden from list/grep/glob so it never pollutes the
    # bot's context with its own backups.
    def test_versions_hidden_from_list(self, ws):
        target = str(ws / "hello.txt")
        _note_read("bot-a", target)
        _op_overwrite(target, "updated", bot_id="bot-a")
        assert (ws / ".versions").exists()

        result = _op_list(str(ws), str(ws))
        parsed = json.loads(result)
        names = [e["name"] for e in parsed["entries"]]
        assert ".versions" not in names

    def test_versions_hidden_from_grep(self, ws):
        target = str(ws / "hello.txt")
        _note_read("bot-a", target)
        _op_overwrite(target, "FINDME_UNIQUE_TOKEN", bot_id="bot-a")
        backup_dir = ws / ".versions"
        assert backup_dir.exists()
        (backup_dir / "planted.txt").write_text("FINDME_UNIQUE_TOKEN in backup")

        result = _op_grep(str(ws), "FINDME_UNIQUE_TOKEN", None, str(ws), None)
        parsed = json.loads(result)
        matched_files = [m["file"] for m in parsed.get("matches", [])]
        assert not any(".versions" in f for f in matched_files)

    def test_versions_hidden_from_glob(self, ws):
        target = str(ws / "hello.txt")
        _note_read("bot-a", target)
        _op_overwrite(target, "updated", bot_id="bot-a")

        result = _op_glob(str(ws), "**/*.bak", str(ws), None)
        parsed = json.loads(result)
        assert parsed["count"] == 0


# ---------------------------------------------------------------------------
# New ops: create / overwrite / json_patch / history / restore
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_recent_reads():
    """Each test starts with a fresh read-tracker cache."""
    _RECENT_READS.clear()
    yield
    _RECENT_READS.clear()


class TestCreateOp:
    def test_create_new_file(self, ws):
        target = str(ws / "brand_new.md")
        result = _op_create(target, "# Hi\n")
        parsed = json.loads(result)
        assert parsed["ok"] is True
        assert parsed["created"] is True
        assert Path(target).read_text() == "# Hi\n"

    def test_create_errors_on_existing_file(self, ws):
        target = str(ws / "hello.txt")
        result = _op_create(target, "other")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "already exists" in parsed["error"]
        assert "overwrite" in parsed["error"]
        # Original content untouched
        assert Path(target).read_text() == "Hello world\n"

    def test_create_errors_without_content(self, ws):
        target = str(ws / "new.md")
        parsed = json.loads(_op_create(target, None))
        assert "error" in parsed

    def test_create_does_not_touch_backups(self, ws):
        target = str(ws / "brand_new.txt")
        _op_create(target, "hi")
        assert not (ws / ".versions").exists()


class TestOverwriteOp:
    def test_overwrite_requires_prior_read(self, ws):
        target = str(ws / "hello.txt")
        original = Path(target).read_text()
        result = _op_overwrite(target, "replacement", bot_id="bot-a")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "read" in parsed["error"].lower()
        # File untouched
        assert Path(target).read_text() == original

    def test_overwrite_succeeds_after_read(self, ws):
        target = str(ws / "hello.txt")
        _note_read("bot-a", target)
        result = _op_overwrite(target, "replacement\n", bot_id="bot-a")
        parsed = json.loads(result)
        assert parsed["ok"] is True
        assert Path(target).read_text() == "replacement\n"

    def test_overwrite_always_creates_backup(self, ws):
        target = str(ws / "hello.txt")
        _note_read("bot-a", target)
        result = _op_overwrite(target, "replacement\n", bot_id="bot-a")
        parsed = json.loads(result)
        backups = list((ws / ".versions").glob("hello.txt.*.bak"))
        assert len(backups) == 1
        assert parsed["backup"] is not None

    def test_overwrite_errors_on_missing_file(self, ws):
        target = str(ws / "ghost.md")
        parsed = json.loads(_op_overwrite(target, "x", bot_id="bot-a"))
        assert "error" in parsed
        assert "create" in parsed["error"]

    def test_overwrite_bot_id_isolated(self, ws):
        """bot-a's read does not unlock bot-b's overwrite."""
        target = str(ws / "hello.txt")
        _note_read("bot-a", target)
        parsed = json.loads(_op_overwrite(target, "x", bot_id="bot-b"))
        assert "error" in parsed


class TestJsonPatchOp:
    def _seed_shows(self, ws):
        data = {
            f"show-{i}": {"title": f"Show {i}", "last_check": "2026-04-16"}
            for i in range(10)
        }
        target = ws / "data" / "tracked-shows.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, indent=2) + "\n")
        return str(target), data

    def test_json_patch_applies_replace(self, ws):
        target, _ = self._seed_shows(ws)
        patch = [{"op": "replace", "path": "/show-3/last_check", "value": "2026-04-17"}]
        parsed = json.loads(_op_json_patch(target, patch))
        assert parsed["ok"] is True
        assert parsed["applied"] == 1
        doc = json.loads(Path(target).read_text())
        assert doc["show-3"]["last_check"] == "2026-04-17"

    def test_json_patch_applies_add(self, ws):
        target, _ = self._seed_shows(ws)
        patch = [{"op": "add", "path": "/show-999", "value": {"title": "New"}}]
        parsed = json.loads(_op_json_patch(target, patch))
        assert parsed["ok"] is True
        doc = json.loads(Path(target).read_text())
        assert doc["show-999"]["title"] == "New"

    def test_json_patch_applies_remove(self, ws):
        target, _ = self._seed_shows(ws)
        patch = [{"op": "remove", "path": "/show-0"}]
        parsed = json.loads(_op_json_patch(target, patch))
        assert parsed["ok"] is True
        doc = json.loads(Path(target).read_text())
        assert "show-0" not in doc

    def test_json_patch_preserves_unchanged_keys(self, ws):
        """Regression test for the arr-stack-heartbeat incident class.

        The LLM constructed a *new* JSON with only the shows it had touched
        in that cycle, then wrote it over the existing file — silently
        dropping every show it didn't mention. With json_patch, unmentioned
        keys survive by construction: the agent never holds the whole file.
        """
        target, original = self._seed_shows(ws)
        patch = [
            {"op": "replace", "path": "/show-1/last_check", "value": "2026-04-17"},
            {"op": "replace", "path": "/show-2/last_check", "value": "2026-04-17"},
        ]
        parsed = json.loads(_op_json_patch(target, patch))
        assert parsed["ok"] is True
        doc = json.loads(Path(target).read_text())
        # The other 8 shows survive byte-for-byte
        for i in (0, 3, 4, 5, 6, 7, 8, 9):
            key = f"show-{i}"
            assert key in doc
            assert doc[key] == original[key]

    def test_json_patch_fails_on_missing_path_for_replace(self, ws):
        target, _ = self._seed_shows(ws)
        patch = [{"op": "replace", "path": "/show-missing/last_check", "value": "x"}]
        parsed = json.loads(_op_json_patch(target, patch))
        assert "error" in parsed
        # File untouched
        doc = json.loads(Path(target).read_text())
        assert "show-missing" not in doc

    def test_json_patch_creates_backup(self, ws):
        target, _ = self._seed_shows(ws)
        patch = [{"op": "replace", "path": "/show-0/last_check", "value": "x"}]
        parsed = json.loads(_op_json_patch(target, patch))
        assert parsed["backup"] is not None
        backups = list((ws / "data" / ".versions").glob("tracked-shows.json.*.bak"))
        assert len(backups) == 1

    def test_json_patch_errors_on_invalid_json_file(self, ws):
        target = ws / "broken.json"
        target.write_text("{not valid json")
        patch = [{"op": "add", "path": "/k", "value": 1}]
        parsed = json.loads(_op_json_patch(str(target), patch))
        assert "error" in parsed
        assert "valid JSON" in parsed["error"]

    def test_json_patch_errors_without_patch(self, ws):
        target, _ = self._seed_shows(ws)
        parsed = json.loads(_op_json_patch(target, None))
        assert "error" in parsed
        parsed = json.loads(_op_json_patch(target, []))
        assert "error" in parsed

    def test_json_patch_preserves_indent(self, ws):
        target = ws / "formatted.json"
        target.write_text('{\n    "a": 1,\n    "b": 2\n}\n')
        patch = [{"op": "replace", "path": "/a", "value": 99}]
        _op_json_patch(str(target), patch)
        # Indent of 4 spaces should be preserved
        text = target.read_text()
        assert '\n    "a": 99' in text
        assert text.endswith("\n")


class TestHistoryOp:
    def test_history_empty_when_no_versions(self, ws):
        target = str(ws / "hello.txt")
        parsed = json.loads(_op_history(target, str(ws)))
        assert parsed["ok"] is True
        assert parsed["versions"] == []

    def test_history_lists_backups(self, ws):
        target = str(ws / "hello.txt")
        for i in range(3):
            Path(target).write_text(f"v{i}")
            _save_backup(target)
        parsed = json.loads(_op_history(target, str(ws)))
        assert parsed["ok"] is True
        assert len(parsed["versions"]) == 3
        for v in parsed["versions"]:
            assert "version" in v and "bytes" in v and "modified_at" in v


class TestRestoreOp:
    def test_restore_recovers_previous_version(self, ws):
        target = str(ws / "hello.txt")
        Path(target).write_text("original\n")
        _save_backup(target)
        backups = list((ws / ".versions").glob("hello.txt.*.bak"))
        version = backups[0].name

        Path(target).write_text("mutated\n")
        parsed = json.loads(_op_restore(target, version))
        assert parsed["ok"] is True
        assert Path(target).read_text() == "original\n"

    def test_restore_backs_up_current_state_first(self, ws):
        """Restore is itself undoable."""
        target = str(ws / "hello.txt")
        Path(target).write_text("state-a\n")
        _save_backup(target)
        version = next(iter((ws / ".versions").glob("hello.txt.*.bak"))).name
        Path(target).write_text("state-b\n")

        parsed = json.loads(_op_restore(target, version))
        assert parsed["ok"] is True
        assert parsed["prior_backup"] is not None
        # There should now be 2 backups: state-a (original) and state-b (from restore)
        all_backups = list((ws / ".versions").glob("hello.txt.*.bak"))
        contents = sorted(b.read_text() for b in all_backups)
        assert "state-a\n" in contents
        assert "state-b\n" in contents

    def test_restore_errors_without_version(self, ws):
        target = str(ws / "hello.txt")
        parsed = json.loads(_op_restore(target, None))
        assert "error" in parsed

    def test_restore_rejects_path_in_version(self, ws):
        target = str(ws / "hello.txt")
        parsed = json.loads(_op_restore(target, "../other.bak"))
        assert "error" in parsed

    def test_restore_rejects_wrong_basename(self, ws):
        target = str(ws / "hello.txt")
        Path(target).write_text("x")
        _save_backup(target)
        # Plant a backup that belongs to a different file
        (ws / ".versions" / "other.txt.1234-5678.bak").write_text("foreign")
        parsed = json.loads(_op_restore(target, "other.txt.1234-5678.bak"))
        assert "error" in parsed
        assert "does not belong" in parsed["error"]


class TestBackupRetention:
    def test_data_files_keep_more_versions(self):
        assert _retention_for("/x/y/tracked-shows.json") == MAX_BACKUP_VERSIONS_DATA
        assert _retention_for("/x/y/config.yaml") == MAX_BACKUP_VERSIONS_DATA
        assert _retention_for("/x/y/pyproject.toml") == MAX_BACKUP_VERSIONS_DATA

    def test_non_data_files_keep_default(self):
        assert _retention_for("/x/y/MEMORY.md") == MAX_BACKUP_VERSIONS_DEFAULT
        assert _retention_for("/x/y/hello.txt") == MAX_BACKUP_VERSIONS_DEFAULT

    def test_data_file_retention_applied(self, ws):
        target = str(ws / "data.json")
        import time as _time
        for i in range(MAX_BACKUP_VERSIONS_DATA + 3):
            Path(target).write_text(json.dumps({"v": i}))
            _save_backup(target)
            _time.sleep(0.005)
        backups = list((ws / ".versions").glob("data.json.*.bak"))
        assert len(backups) == MAX_BACKUP_VERSIONS_DATA


class TestEditAutoRecoverRouting:
    """When `edit` is called with only `content` (no `find`), it auto-recovers
    by routing to `overwrite` if the file exists, or `create` if not. The
    read-before-write precondition still applies.
    """

    def test_edit_without_find_routes_to_create_for_new_file(self, ws):
        target = str(ws / "newfile.md")
        parsed = json.loads(_op_edit(target, find=None, replace=None,
                                     replace_all=False, content="# New\n",
                                     bot_id="bot-a"))
        assert parsed["ok"] is True
        assert parsed.get("created") is True

    def test_edit_without_find_routes_to_overwrite_blocks_without_read(self, ws):
        target = str(ws / "hello.txt")
        parsed = json.loads(_op_edit(target, find=None, replace=None,
                                     replace_all=False, content="new",
                                     bot_id="bot-a"))
        # Should error because bot-a has not read the file first
        assert "error" in parsed
        assert "read" in parsed["error"].lower()

    def test_edit_without_find_routes_to_overwrite_allows_after_read(self, ws):
        target = str(ws / "hello.txt")
        _note_read("bot-a", target)
        parsed = json.loads(_op_edit(target, find=None, replace=None,
                                     replace_all=False, content="new\n",
                                     bot_id="bot-a"))
        assert parsed["ok"] is True
        assert Path(target).read_text() == "new\n"
