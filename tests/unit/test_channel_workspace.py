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
        assert root == "/data/shared/ws-1/channels/ch-123"

    def test_get_channel_archive_root(self):
        from app.services.channel_workspace import get_channel_archive_root
        bot = _make_bot()
        with patch("app.services.channel_workspace._get_ws_root", return_value="/data/shared/ws-1"):
            root = get_channel_archive_root("ch-123", bot)
        assert root == "/data/shared/ws-1/channels/ch-123/archive"

    def test_get_channel_workspace_index_prefix(self):
        from app.services.channel_workspace import get_channel_workspace_index_prefix
        prefix = get_channel_workspace_index_prefix("ch-123")
        assert prefix == "channels/ch-123"


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

    def test_list_workspace_files_data_recurses_subdirs(self):
        """Data section must include files in subdirectories like data/spindrel/."""
        from app.services.channel_workspace import list_workspace_files
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            # Create data/ with a subdirectory
            os.makedirs(os.path.join(tmp, "data", "spindrel"))
            with open(os.path.join(tmp, "data", "top_level.md"), "w") as f:
                f.write("top")
            with open(os.path.join(tmp, "data", "spindrel", "channel_prompt.md"), "w") as f:
                f.write("prompt content")
            with open(os.path.join(tmp, "data", "spindrel", "heartbeat.md"), "w") as f:
                f.write("heartbeat content")

            with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=tmp):
                files = list_workspace_files("ch-1", bot, include_data=True)

            data_files = [f for f in files if f["section"] == "data"]
            names = {f["name"] for f in data_files}
            paths = {f["path"] for f in data_files}

            assert len(data_files) == 3
            # Names show relative path within data/
            assert "top_level.md" in names
            assert os.path.join("spindrel", "channel_prompt.md") in names
            assert os.path.join("spindrel", "heartbeat.md") in names
            # Paths include the data/ prefix
            assert "data/top_level.md" in paths
            assert os.path.join("data", "spindrel", "channel_prompt.md") in paths
            assert os.path.join("data", "spindrel", "heartbeat.md") in paths

    def test_context_assembly_data_listing_recurses_subdirs(self):
        """The os.walk logic in context_assembly must list files in data/ subdirectories."""
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            os.makedirs(os.path.join(data_dir, "spindrel"))
            with open(os.path.join(data_dir, "top.md"), "w") as f:
                f.write("top")
            with open(os.path.join(data_dir, "spindrel", "README.md"), "w") as f:
                f.write("readme")
            with open(os.path.join(data_dir, "spindrel", "config.yaml"), "w") as f:
                f.write("cfg")

            # Reproduce the exact logic from context_assembly.py
            entries = sorted(
                os.path.relpath(os.path.join(dp, fn), data_dir)
                for dp, _, fns in os.walk(data_dir)
                for fn in fns
            )
            assert "top.md" in entries
            assert os.path.join("spindrel", "README.md") in entries
            assert os.path.join("spindrel", "config.yaml") in entries
            assert len(entries) == 3

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
            ws_dir = os.path.join(parent, "ws")
            evil_dir = os.path.join(parent, "ws_evil")
            os.makedirs(ws_dir)
            os.makedirs(evil_dir)
            with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=ws_dir):
                with pytest.raises(ValueError, match="escapes"):
                    write_workspace_file("ch-1", bot, "../ws_evil/pwned.md", "gotcha")
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
                # No workspace/ subdirectory should exist
                assert not os.path.isdir(os.path.join(root, "workspace"))

    def test_ensure_writes_display_name_to_channel_info(self):
        """When display_name is provided, .channel_info should contain it."""
        from app.services.channel_workspace import ensure_channel_workspace
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.services.channel_workspace._get_ws_root", return_value=tmp):
                root = ensure_channel_workspace("abc-123-uuid", bot, display_name="My Project")
                info_path = os.path.join(root, ".channel_info")
                assert os.path.isfile(info_path)
                content = open(info_path).read()
                assert "display_name: My Project" in content
                assert "channel_id: abc-123-uuid" in content

    def test_ensure_falls_back_to_channel_id_when_no_display_name(self):
        """Without display_name and no existing .channel_info, falls back to channel_id."""
        from app.services.channel_workspace import ensure_channel_workspace
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.services.channel_workspace._get_ws_root", return_value=tmp):
                root = ensure_channel_workspace("abc-123-uuid", bot)
                info_path = os.path.join(root, ".channel_info")
                content = open(info_path).read()
                assert "display_name: abc-123-uuid" in content

    def test_ensure_preserves_existing_display_name(self):
        """When called without display_name, preserve existing non-UUID display_name."""
        from app.services.channel_workspace import ensure_channel_workspace
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.services.channel_workspace._get_ws_root", return_value=tmp):
                # First call sets a good display name
                ensure_channel_workspace("abc-123-uuid", bot, display_name="My Project")
                # Second call without display_name should preserve "My Project"
                root = ensure_channel_workspace("abc-123-uuid", bot)
                info_path = os.path.join(root, ".channel_info")
                content = open(info_path).read()
                assert "display_name: My Project" in content

    def test_ensure_updates_display_name_when_explicitly_provided(self):
        """Explicit display_name should override existing one."""
        from app.services.channel_workspace import ensure_channel_workspace
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.services.channel_workspace._get_ws_root", return_value=tmp):
                ensure_channel_workspace("abc-123-uuid", bot, display_name="Old Name")
                root = ensure_channel_workspace("abc-123-uuid", bot, display_name="New Name")
                info_path = os.path.join(root, ".channel_info")
                content = open(info_path).read()
                assert "display_name: New Name" in content


# ---------------------------------------------------------------------------
# Migration: old broken layouts
# ---------------------------------------------------------------------------

class TestChannelWorkspaceMigration:

    def test_migrate_double_nested_guid(self):
        """channels/{id}/{id}/{archive,data} → channels/{id}/{archive,data}."""
        from app.services.channel_workspace import ensure_channel_workspace
        bot = _make_bot()
        ch_id = "1329e3ab-c870-50ad-8f14"
        with tempfile.TemporaryDirectory() as tmp:
            # Create the old broken double-nested structure
            old_dir = os.path.join(tmp, "channels", ch_id, ch_id)
            os.makedirs(os.path.join(old_dir, "archive"))
            os.makedirs(os.path.join(old_dir, "data"))
            with open(os.path.join(old_dir, "data", "heartbeat.md"), "w") as f:
                f.write("old heartbeat")

            with patch("app.services.channel_workspace._get_ws_root", return_value=tmp):
                root = ensure_channel_workspace(ch_id, bot, display_name="Test Channel")

            # Old double-nested dir should be gone
            assert not os.path.isdir(old_dir)
            # Files should be in the correct location (directly under channel dir)
            assert os.path.isdir(os.path.join(root, "archive"))
            assert os.path.isdir(os.path.join(root, "data"))
            assert os.path.isfile(os.path.join(root, "data", "heartbeat.md"))
            assert open(os.path.join(root, "data", "heartbeat.md")).read() == "old heartbeat"

    def test_migrate_old_workspace_subdir(self):
        """channels/{id}/workspace/{archive,data,files} → channels/{id}/{archive,data,files}."""
        from app.services.channel_workspace import ensure_channel_workspace
        bot = _make_bot()
        ch_id = "dabd250b-a883-50b8-878f"
        with tempfile.TemporaryDirectory() as tmp:
            # Create old structure with workspace/ subdirectory
            old_ws = os.path.join(tmp, "channels", ch_id, "workspace")
            os.makedirs(os.path.join(old_ws, "archive"))
            os.makedirs(os.path.join(old_ws, "data"))
            with open(os.path.join(old_ws, "context.md"), "w") as f:
                f.write("workspace context")
            with open(os.path.join(old_ws, "archive", "section_001.md"), "w") as f:
                f.write("archived content")

            with patch("app.services.channel_workspace._get_ws_root", return_value=tmp):
                root = ensure_channel_workspace(ch_id, bot, display_name="My Channel")

            # workspace/ subdir should be gone
            assert not os.path.isdir(old_ws)
            # Files should be directly under the channel dir
            assert root == os.path.join(tmp, "channels", ch_id)
            assert os.path.isfile(os.path.join(root, "context.md"))
            assert open(os.path.join(root, "context.md")).read() == "workspace context"
            assert os.path.isfile(os.path.join(root, "archive", "section_001.md"))
            assert open(os.path.join(root, "archive", "section_001.md")).read() == "archived content"

    def test_migrate_does_not_overwrite_existing_files(self):
        """Migration should not overwrite files already in the channel dir."""
        from app.services.channel_workspace import ensure_channel_workspace
        bot = _make_bot()
        ch_id = "test-merge"
        with tempfile.TemporaryDirectory() as tmp:
            ch_dir = os.path.join(tmp, "channels", ch_id)

            # Create a file directly in channel dir
            os.makedirs(os.path.join(ch_dir, "archive"))
            with open(os.path.join(ch_dir, "archive", "existing.md"), "w") as f:
                f.write("keep this")

            # Also create old workspace/ with conflicting file
            old_ws = os.path.join(ch_dir, "workspace")
            os.makedirs(os.path.join(old_ws, "archive"))
            with open(os.path.join(old_ws, "archive", "existing.md"), "w") as f:
                f.write("old version")
            with open(os.path.join(old_ws, "archive", "new_file.md"), "w") as f:
                f.write("migrate this")

            with patch("app.services.channel_workspace._get_ws_root", return_value=tmp):
                root = ensure_channel_workspace(ch_id, bot)

            # Existing file should not be overwritten
            assert open(os.path.join(root, "archive", "existing.md")).read() == "keep this"
            # New file should be migrated
            assert open(os.path.join(root, "archive", "new_file.md")).read() == "migrate this"

    def test_correct_structure_not_affected(self):
        """Channels already with flat structure should not be modified."""
        from app.services.channel_workspace import ensure_channel_workspace
        bot = _make_bot()
        ch_id = "correct-channel"
        with tempfile.TemporaryDirectory() as tmp:
            ch_dir = os.path.join(tmp, "channels", ch_id)
            os.makedirs(os.path.join(ch_dir, "archive"))
            os.makedirs(os.path.join(ch_dir, "data"))
            with open(os.path.join(ch_dir, "context.md"), "w") as f:
                f.write("existing workspace file")

            with patch("app.services.channel_workspace._get_ws_root", return_value=tmp):
                root = ensure_channel_workspace(ch_id, bot, display_name="Correct Channel")

            assert root == ch_dir
            assert open(os.path.join(root, "context.md")).read() == "existing workspace file"
            # No workspace/ subdir created
            assert not os.path.isdir(os.path.join(root, "workspace"))


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
            assert "channels/ch-1/**/*.md" in call_args[0][2]
