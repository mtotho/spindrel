"""Tests for channel workspace service, indexing, and context assembly integration."""
import os
import tempfile
from unittest.mock import patch, AsyncMock, MagicMock, PropertyMock
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# Helper: mock bot config
# ---------------------------------------------------------------------------

def _make_bot(shared_workspace_id="ws-1"):
    """Create a minimal mock BotConfig for channel workspace tests."""
    ws_indexing = SimpleNamespace(
        enabled=True,
        patterns=["**/*.md"],
        similarity_threshold=0.3,
        top_k=10,
        watch=False,
        cooldown_seconds=60,
        embedding_model=None,
        segments=None,
    )
    ws = SimpleNamespace(enabled=True, indexing=ws_indexing)
    return SimpleNamespace(
        id="test_bot",
        shared_workspace_id=shared_workspace_id,
        shared_workspace_role="worker",
        workspace=ws,
        _workspace_raw={"indexing": {}},
        _ws_indexing_config=None,
        memory_scheme="workspace-files",
        local_tools=["exec_command"],
        pinned_tools=[],
        skills=[],
        skill_ids=[],
        client_tools=[],
        mcp_servers=[],
    )


# ---------------------------------------------------------------------------
# Service: path resolution
# ---------------------------------------------------------------------------

class TestChannelWorkspacePaths:
    def test_get_channel_workspace_root(self):
        from app.services.channel_workspace import get_channel_workspace_root
        bot = _make_bot()
        with patch("app.services.channel_workspace._get_ws_root", return_value="/data/shared/ws-1"):
            root = get_channel_workspace_root("ch-123", bot)
        assert root == "/data/shared/ws-1/channels/ch-123/workspace"

    def test_get_channel_archive_root(self):
        from app.services.channel_workspace import get_channel_archive_root
        bot = _make_bot()
        with patch("app.services.channel_workspace._get_ws_root", return_value="/data/shared/ws-1"):
            root = get_channel_archive_root("ch-123", bot)
        assert root == "/data/shared/ws-1/channels/ch-123/workspace/archive"

    def test_get_channel_workspace_index_prefix(self):
        from app.services.channel_workspace import get_channel_workspace_index_prefix
        prefix = get_channel_workspace_index_prefix("ch-123")
        assert prefix == "channels/ch-123/workspace"


# ---------------------------------------------------------------------------
# Service: file operations
# ---------------------------------------------------------------------------

class TestChannelWorkspaceFileOps:
    def test_list_workspace_files_empty(self):
        from app.services.channel_workspace import list_workspace_files
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=tmp):
                files = list_workspace_files("ch-1", bot)
        assert files == []

    def test_list_workspace_files_with_files(self):
        from app.services.channel_workspace import list_workspace_files
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            # Create some .md files
            with open(os.path.join(tmp, "orders.md"), "w") as f:
                f.write("# Orders")
            with open(os.path.join(tmp, "notes.txt"), "w") as f:
                f.write("not markdown")
            os.makedirs(os.path.join(tmp, "archive"), exist_ok=True)
            with open(os.path.join(tmp, "archive", "old.md"), "w") as f:
                f.write("# Old")

            with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=tmp):
                # Without archive
                files = list_workspace_files("ch-1", bot, include_archive=False)
                assert len(files) == 1
                assert files[0]["name"] == "orders.md"
                assert files[0]["section"] == "active"

                # With archive
                files = list_workspace_files("ch-1", bot, include_archive=True)
                assert len(files) == 2
                archived = [f for f in files if f["section"] == "archive"]
                assert len(archived) == 1
                assert archived[0]["name"] == "old.md"

    def test_read_workspace_file(self):
        from app.services.channel_workspace import read_workspace_file
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "test.md"), "w") as f:
                f.write("hello world")
            with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=tmp):
                content = read_workspace_file("ch-1", bot, "test.md")
                assert content == "hello world"

    def test_read_workspace_file_path_escape(self):
        from app.services.channel_workspace import read_workspace_file
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=tmp):
                content = read_workspace_file("ch-1", bot, "../../etc/passwd")
                assert content is None

    def test_write_workspace_file(self):
        from app.services.channel_workspace import write_workspace_file
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=tmp):
                result = write_workspace_file("ch-1", bot, "new.md", "content here")
                assert result["path"] == "new.md"
                assert os.path.isfile(os.path.join(tmp, "new.md"))
                with open(os.path.join(tmp, "new.md")) as f:
                    assert f.read() == "content here"

    def test_write_workspace_file_path_escape(self):
        from app.services.channel_workspace import write_workspace_file
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=tmp):
                with pytest.raises(ValueError, match="escapes"):
                    write_workspace_file("ch-1", bot, "../../evil.md", "bad")

    def test_delete_workspace_file(self):
        from app.services.channel_workspace import delete_workspace_file
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            fpath = os.path.join(tmp, "doomed.md")
            with open(fpath, "w") as f:
                f.write("bye")
            with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=tmp):
                result = delete_workspace_file("ch-1", bot, "doomed.md")
                assert result["deleted"] is True
                assert not os.path.exists(fpath)

    def test_write_workspace_file_path_escape_prefix_trick(self):
        """Regression: workspace root /tmp/ws must not match /tmp/ws_evil via startswith."""
        from app.services.channel_workspace import write_workspace_file
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as parent:
            # Create two dirs: ws (the real workspace) and ws_evil (attacker-controlled)
            ws_dir = os.path.join(parent, "ws")
            evil_dir = os.path.join(parent, "ws_evil")
            os.makedirs(ws_dir)
            os.makedirs(evil_dir)
            with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=ws_dir):
                # "../ws_evil/pwned.md" resolves to /parent/ws_evil/pwned.md
                # which starts with /parent/ws (without trailing sep) — old bug
                with pytest.raises(ValueError, match="escapes"):
                    write_workspace_file("ch-1", bot, "../ws_evil/pwned.md", "gotcha")
            # Ensure nothing was written
            assert not os.path.exists(os.path.join(evil_dir, "pwned.md"))

    def test_read_workspace_file_path_escape_prefix_trick(self):
        """Regression: read must also reject paths that match via prefix without separator."""
        from app.services.channel_workspace import read_workspace_file
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as parent:
            ws_dir = os.path.join(parent, "ws")
            evil_dir = os.path.join(parent, "ws_evil")
            os.makedirs(ws_dir)
            os.makedirs(evil_dir)
            # Put a file in the evil dir
            with open(os.path.join(evil_dir, "secret.md"), "w") as f:
                f.write("secret data")
            with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=ws_dir):
                content = read_workspace_file("ch-1", bot, "../ws_evil/secret.md")
                assert content is None

    def test_delete_workspace_file_path_escape(self):
        """Delete must reject path traversal attempts."""
        from app.services.channel_workspace import delete_workspace_file
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=tmp):
                with pytest.raises(ValueError, match="escapes"):
                    delete_workspace_file("ch-1", bot, "../../etc/passwd")

    def test_delete_workspace_file_path_escape_prefix_trick(self):
        """Regression: delete must also reject the prefix trick."""
        from app.services.channel_workspace import delete_workspace_file
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as parent:
            ws_dir = os.path.join(parent, "ws")
            evil_dir = os.path.join(parent, "ws_evil")
            os.makedirs(ws_dir)
            os.makedirs(evil_dir)
            target = os.path.join(evil_dir, "victim.md")
            with open(target, "w") as f:
                f.write("don't delete me")
            with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=ws_dir):
                with pytest.raises(ValueError, match="escapes"):
                    delete_workspace_file("ch-1", bot, "../ws_evil/victim.md")
            assert os.path.exists(target)

    def test_delete_workspace_file_not_found(self):
        """Deleting a non-existent file raises FileNotFoundError."""
        from app.services.channel_workspace import delete_workspace_file
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=tmp):
                with pytest.raises(FileNotFoundError):
                    delete_workspace_file("ch-1", bot, "nonexistent.md")

    def test_ensure_channel_workspace_creates_data_dir(self):
        """ensure_channel_workspace creates both archive/ and data/ subdirs."""
        from app.services.channel_workspace import ensure_channel_workspace
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.services.channel_workspace._get_ws_root", return_value=tmp):
                root = ensure_channel_workspace("ch-1", bot)
                assert os.path.isdir(os.path.join(root, "data"))

    def test_ensure_channel_workspace(self):
        from app.services.channel_workspace import ensure_channel_workspace
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.services.channel_workspace._get_ws_root", return_value=tmp):
                root = ensure_channel_workspace("ch-1", bot)
                assert os.path.isdir(root)
                assert os.path.isdir(os.path.join(root, "archive"))


# ---------------------------------------------------------------------------
# Indexing: sentinel bot_id
# ---------------------------------------------------------------------------

class TestChannelWorkspaceIndexing:
    def test_sentinel_bot_id(self):
        from app.services.channel_workspace_indexing import _get_channel_index_bot_id
        assert _get_channel_index_bot_id("abc-123") == "channel:abc-123"

    @pytest.mark.asyncio
    async def test_index_channel_workspace_calls_index_directory(self):
        from app.services.channel_workspace_indexing import index_channel_workspace
        bot = _make_bot()
        mock_stats = {"indexed": 2, "skipped": 0, "removed": 0, "errors": 0}
        with patch("app.agent.fs_indexer.index_directory", new_callable=AsyncMock, return_value=mock_stats) as mock_idx, \
             patch("app.services.channel_workspace._get_ws_root", return_value="/data/shared/ws-1"), \
             patch("app.services.workspace_indexing.resolve_indexing", return_value={"embedding_model": "text-embedding-3-small"}):
            stats = await index_channel_workspace("ch-1", bot)
            assert stats == mock_stats
            mock_idx.assert_called_once()
            call_args = mock_idx.call_args
            assert call_args[0][1] == "channel:ch-1"  # sentinel bot_id
            assert "channels/ch-1/workspace/**/*.md" in call_args[0][2]
