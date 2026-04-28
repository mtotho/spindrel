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

    def test_list_workspace_files_data_single_level(self):
        """Data listing returns root files + folder stubs (not recursive)."""
        from app.services.channel_workspace import list_workspace_files
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "data", "spindrel"))
            with open(os.path.join(tmp, "data", "top_level.md"), "w") as f:
                f.write("top")
            with open(os.path.join(tmp, "data", "spindrel", "channel_prompt.md"), "w") as f:
                f.write("prompt content")
            with open(os.path.join(tmp, "data", "spindrel", "heartbeat.md"), "w") as f:
                f.write("heartbeat content")

            with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=tmp):
                files = list_workspace_files("ch-1", bot, include_data=True)

            data_items = [f for f in files if f["section"] == "data"]
            # Should be 1 root file + 1 folder stub, NOT 3 flat files
            assert len(data_items) == 2

            root_file = [f for f in data_items if f.get("type") != "folder"]
            assert len(root_file) == 1
            assert root_file[0]["name"] == "top_level.md"

            folders = [f for f in data_items if f.get("type") == "folder"]
            assert len(folders) == 1
            assert folders[0]["name"] == "spindrel"
            assert folders[0]["count"] == 2  # 2 files inside

    def test_list_workspace_files_data_prefix_drills_into_folder(self):
        """data_prefix parameter lists contents of a specific subfolder."""
        from app.services.channel_workspace import list_workspace_files
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "data", "spindrel", "sub"))
            with open(os.path.join(tmp, "data", "spindrel", "channel_prompt.md"), "w") as f:
                f.write("prompt")
            with open(os.path.join(tmp, "data", "spindrel", "sub", "deep.md"), "w") as f:
                f.write("deep")

            with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=tmp):
                files = list_workspace_files("ch-1", bot, include_data=True, data_prefix="spindrel")

            data_items = [f for f in files if f["section"] == "data"]
            assert len(data_items) == 2  # 1 file + 1 subfolder

            file_items = [f for f in data_items if f.get("type") != "folder"]
            assert len(file_items) == 1
            assert file_items[0]["name"] == "spindrel/channel_prompt.md"

            folder_items = [f for f in data_items if f.get("type") == "folder"]
            assert len(folder_items) == 1
            assert folder_items[0]["name"] == "spindrel/sub"
            assert folder_items[0]["count"] == 1

    def test_list_workspace_files_data_prefix_rejects_traversal(self):
        """data_prefix with .. must not escape data/ directory."""
        from app.services.channel_workspace import list_workspace_files
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "data"))
            with open(os.path.join(tmp, "secret.md"), "w") as f:
                f.write("secret")

            with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=tmp):
                files = list_workspace_files("ch-1", bot, include_data=True, data_prefix="../")

            # Should return nothing — traversal rejected
            data_items = [f for f in files if f["section"] == "data"]
            assert len(data_items) == 0

    def test_context_assembly_data_listing_is_root_only(self):
        """Context assembly lists only root-level data/ files (scandir, not walk)."""
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            os.makedirs(os.path.join(data_dir, "spindrel"))
            with open(os.path.join(data_dir, "top.md"), "w") as f:
                f.write("top")
            with open(os.path.join(data_dir, "spindrel", "README.md"), "w") as f:
                f.write("readme")

            # Reproduce the exact logic from context_assembly.py (scandir, root only)
            entries = sorted(
                e.name for e in os.scandir(data_dir)
                if e.is_file()
            )
            # Only root file, NOT nested files
            assert entries == ["top.md"]

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

    def test_write_workspace_file_binary(self):
        from app.services.channel_workspace import write_workspace_file_binary
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
            with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=tmp):
                result = write_workspace_file_binary("ch-1", bot, "data/image.png", png_data)
                assert result["path"] == "data/image.png"
                assert result["size"] == len(png_data)
                # Verify binary content preserved exactly
                with open(os.path.join(tmp, "data/image.png"), "rb") as f:
                    assert f.read() == png_data

    def test_write_workspace_file_binary_creates_subdirs(self):
        from app.services.channel_workspace import write_workspace_file_binary
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            data = b"\xff\xfe binary \x00 data"
            with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=tmp):
                write_workspace_file_binary("ch-1", bot, "data/deep/nested/file.bin", data)
                assert os.path.isfile(os.path.join(tmp, "data/deep/nested/file.bin"))
                with open(os.path.join(tmp, "data/deep/nested/file.bin"), "rb") as f:
                    assert f.read() == data

    def test_write_workspace_file_binary_path_escape(self):
        from app.services.channel_workspace import write_workspace_file_binary
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=tmp):
                with pytest.raises(ValueError, match="escapes"):
                    write_workspace_file_binary("ch-1", bot, "../../evil.bin", b"bad")

    def test_write_workspace_file_binary_overwrites(self):
        from app.services.channel_workspace import write_workspace_file_binary
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=tmp):
                write_workspace_file_binary("ch-1", bot, "data/f.bin", b"v1")
                write_workspace_file_binary("ch-1", bot, "data/f.bin", b"v2-longer")
                with open(os.path.join(tmp, "data/f.bin"), "rb") as f:
                    assert f.read() == b"v2-longer"

    def test_list_data_includes_binary_files(self):
        from app.services.channel_workspace import list_workspace_files, write_workspace_file_binary
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "data"))
            with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=tmp):
                write_workspace_file_binary("ch-1", bot, "data/image.png", b"\x89PNG" + b"\x00" * 50)
                files = list_workspace_files("ch-1", bot, include_data=True)
            data_files = [f for f in files if f["section"] == "data"]
            assert len(data_files) == 1
            assert data_files[0]["name"] == "image.png"
            assert data_files[0]["size"] == 54

    def test_delete_binary_file(self):
        from app.services.channel_workspace import delete_workspace_file, write_workspace_file_binary
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "data"))
            with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=tmp):
                write_workspace_file_binary("ch-1", bot, "data/img.png", b"\x89PNG")
                result = delete_workspace_file("ch-1", bot, "data/img.png")
                assert result["deleted"] is True
                assert not os.path.exists(os.path.join(tmp, "data/img.png"))

    def test_delete_workspace_file_not_found(self):
        """Deleting a non-existent file raises FileNotFoundError."""
        from app.services.channel_workspace import delete_workspace_file
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=tmp):
                with pytest.raises(FileNotFoundError):
                    delete_workspace_file("ch-1", bot, "nonexistent.md")

    def test_ensure_channel_workspace_creates_data_dir(self):
        """ensure_channel_workspace creates archive/, data/, and knowledge-base/ subdirs."""
        from app.services.channel_workspace import ensure_channel_workspace
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.services.channel_workspace._get_ws_root", return_value=tmp):
                root = ensure_channel_workspace("ch-1", bot)
                assert os.path.isdir(os.path.join(root, "data"))

    def test_ensure_channel_workspace_creates_knowledge_base_dir(self):
        """Every channel gets an auto-indexed knowledge-base/ folder by convention."""
        from app.services.channel_workspace import (
            ensure_channel_workspace,
            get_channel_knowledge_base_root,
            get_channel_knowledge_base_index_prefix,
        )
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.services.channel_workspace._get_ws_root", return_value=tmp):
                root = ensure_channel_workspace("ch-42", bot)
                kb_root = os.path.join(root, "knowledge-base")
                assert os.path.isdir(kb_root)
                assert get_channel_knowledge_base_root("ch-42", bot) == kb_root
        # Index prefix is relative, not host-absolute
        assert get_channel_knowledge_base_index_prefix("ch-42") == "channels/ch-42/knowledge-base"

    def test_ensure_channel_workspace(self):
        from app.services.channel_workspace import ensure_channel_workspace
        bot = _make_bot()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.services.channel_workspace._get_ws_root", return_value=tmp):
                root = ensure_channel_workspace("ch-1", bot)
                assert os.path.isdir(root)
                assert os.path.isdir(os.path.join(root, "archive"))
                assert os.path.isdir(os.path.join(root, "knowledge-base"))
                # No workspace/ subdirectory should exist
                assert not os.path.isdir(os.path.join(root, "workspace"))

    @pytest.mark.asyncio
    async def test_backfill_creates_kb_for_existing_channel_dir_without_one(self):
        """Backfill mkdirs knowledge-base/ for channels that pre-date the KB convention."""
        from app.services.channel_workspace import backfill_knowledge_base_dirs
        bot = _make_bot()

        with tempfile.TemporaryDirectory() as tmp:
            # Pre-create a channel dir WITHOUT a knowledge-base/ subdir,
            # mimicking the on-disk state of a channel created before
            # 2026-04-19.
            channel_dir = os.path.join(tmp, "channels", "legacy-ch")
            os.makedirs(os.path.join(channel_dir, "archive"), exist_ok=True)
            assert not os.path.isdir(os.path.join(channel_dir, "knowledge-base"))

            # Stub async_session to yield a session whose execute() returns
            # one channel row. Channel id is matched against the pre-created
            # dir above by `get_channel_workspace_root`.
            class _FakeCtx:
                async def __aenter__(self_inner):
                    sess = AsyncMock()
                    result = MagicMock()
                    result.all = MagicMock(return_value=[("legacy-ch", "test_bot")])
                    sess.execute = AsyncMock(return_value=result)
                    return sess
                async def __aexit__(self_inner, *a):
                    return None

            with patch("app.services.channel_workspace._get_ws_root", return_value=tmp), \
                 patch("app.db.engine.async_session", new=lambda: _FakeCtx()), \
                 patch("app.agent.bots.get_bot", return_value=bot):
                n = await backfill_knowledge_base_dirs()

            assert n == 1
            assert os.path.isdir(os.path.join(channel_dir, "knowledge-base"))

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
        resolved_indexing = {
            "patterns": ["**/*.md"],
            "similarity_threshold": 0.3,
            "top_k": 8,
            "watch": True,
            "cooldown_seconds": 300,
            "include_bots": [],
            "embedding_model": "text-embedding-3-small",
            "segments": [],
            "segments_source": "default",
        }
        with patch("app.agent.fs_indexer.index_directory", new_callable=AsyncMock, return_value=mock_stats) as mock_idx, \
             patch("app.services.channel_workspace._get_ws_root", return_value="/data/shared/ws-1"), \
             patch("app.services.workspace_indexing.resolve_indexing", return_value=resolved_indexing):
            stats = await index_channel_workspace("ch-1", bot)
            assert stats == mock_stats
            mock_idx.assert_called_once()
            call_args = mock_idx.call_args
            assert call_args[0][1] == "channel:ch-1"  # sentinel bot_id
            assert "channels/ch-1/**/*.md" in call_args[0][2]
