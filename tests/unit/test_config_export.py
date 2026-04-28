"""Unit tests for app.services.config_export."""
import json
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.config_export import (
    _DEBOUNCE_SECONDS,
    is_config_mutation,
    mark_config_dirty,
    restore_from_file,
    write_config_file,
)
import app.services.config_export as config_export_mod


class TestMarkConfigDirty:
    def setup_method(self):
        config_export_mod._dirty = False
        config_export_mod._dirty_since = 0.0

    def test_sets_dirty_flag(self):
        with patch.object(config_export_mod, "settings", MagicMock(CONFIG_STATE_FILE="config.json")):
            mark_config_dirty()
            assert config_export_mod._dirty is True
            assert config_export_mod._dirty_since > 0

    def test_noop_when_disabled(self):
        with patch.object(config_export_mod, "settings", MagicMock(CONFIG_STATE_FILE="")):
            mark_config_dirty()
            assert config_export_mod._dirty is False

    def test_preserves_first_dirty_timestamp(self):
        with patch.object(config_export_mod, "settings", MagicMock(CONFIG_STATE_FILE="config.json")):
            mark_config_dirty()
            first_ts = config_export_mod._dirty_since
            mark_config_dirty()
            assert config_export_mod._dirty_since == first_ts


class TestIsConfigMutation:
    def test_post_admin_path(self):
        assert is_config_mutation("POST", "/api/v1/admin/bots") is True

    def test_put_admin_path(self):
        assert is_config_mutation("PUT", "/api/v1/admin/bots/my-bot") is True

    def test_patch_admin_path(self):
        assert is_config_mutation("PATCH", "/api/v1/admin/channels/abc") is True

    def test_delete_admin_path(self):
        assert is_config_mutation("DELETE", "/api/v1/admin/bots/my-bot") is True

    def test_get_ignored(self):
        assert is_config_mutation("GET", "/api/v1/admin/bots") is False

    def test_non_admin_path(self):
        assert is_config_mutation("POST", "/api/v1/chat") is False

    def test_channels_path(self):
        assert is_config_mutation("POST", "/api/v1/channels/abc/heartbeat") is True

    def test_excluded_fire_suffix(self):
        assert is_config_mutation("POST", "/api/v1/admin/tasks/fire") is False

    def test_excluded_infer_suffix(self):
        assert is_config_mutation("POST", "/api/v1/admin/infer") is False

    def test_excluded_reindex_suffix(self):
        assert is_config_mutation("POST", "/api/v1/admin/reindex") is False

    def test_excluded_test_suffix(self):
        assert is_config_mutation("POST", "/api/v1/admin/test") is False

    def test_excluded_diagnostics_suffix(self):
        assert is_config_mutation("POST", "/api/v1/admin/diagnostics") is False

    def test_excluded_server_logs_suffix(self):
        assert is_config_mutation("DELETE", "/api/v1/admin/server-logs") is False

    def test_excluded_config_state_suffix(self):
        assert is_config_mutation("POST", "/api/v1/admin/config-state") is False

    def test_excluded_download_suffix(self):
        assert is_config_mutation("POST", "/api/v1/admin/embedding-models/download") is False

    def test_excluded_file_sync_suffix(self):
        assert is_config_mutation("POST", "/api/v1/admin/file-sync") is False

    def test_excluded_log_level_suffix(self):
        assert is_config_mutation("PUT", "/api/v1/admin/log-level") is False


class TestWriteConfigFile:
    @pytest.mark.asyncio
    async def test_writes_valid_json(self, tmp_path):
        out_file = tmp_path / "config-state.json"
        mock_state = {"bots": [{"id": "test"}], "channels": []}

        mock_db = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(config_export_mod, "settings", MagicMock(CONFIG_STATE_FILE=str(out_file))),
            patch("app.services.config_export.assemble_config_state", new_callable=AsyncMock, return_value=mock_state),
            patch("app.db.engine.async_session", return_value=mock_session_ctx),
        ):
            await write_config_file()

        assert out_file.exists()
        data = json.loads(out_file.read_text())
        assert data == mock_state

    @pytest.mark.asyncio
    async def test_noop_when_disabled(self):
        with patch.object(config_export_mod, "settings", MagicMock(CONFIG_STATE_FILE="")):
            # Should return without doing anything
            await write_config_file()

    @pytest.mark.asyncio
    async def test_atomic_write_no_partial(self, tmp_path):
        """If assemble fails, the file should not exist."""
        out_file = tmp_path / "config-state.json"

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock()
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(config_export_mod, "settings", MagicMock(CONFIG_STATE_FILE=str(out_file))),
            patch("app.services.config_export.assemble_config_state", new_callable=AsyncMock, side_effect=RuntimeError("boom")),
            patch("app.db.engine.async_session", return_value=mock_session_ctx),
        ):
            with pytest.raises(RuntimeError):
                await write_config_file()

        assert not out_file.exists()


class TestRestoreFromFile:
    @pytest.mark.asyncio
    async def test_missing_file_graceful(self, tmp_path):
        with patch.object(config_export_mod, "settings", MagicMock(CONFIG_STATE_FILE=str(tmp_path / "nope.json"))):
            # Should not raise
            await restore_from_file()

    @pytest.mark.asyncio
    async def test_disabled_when_empty(self):
        with patch.object(config_export_mod, "settings", MagicMock(CONFIG_STATE_FILE="")):
            await restore_from_file()

    @pytest.mark.asyncio
    async def test_invalid_json_graceful(self, tmp_path):
        bad_file = tmp_path / "config-state.json"
        bad_file.write_text("not json {{{")
        with patch.object(config_export_mod, "settings", MagicMock(CONFIG_STATE_FILE=str(bad_file))):
            # Should log error but not raise
            await restore_from_file()

    @pytest.mark.asyncio
    async def test_calls_do_restore(self, tmp_path):
        config_file = tmp_path / "config-state.json"
        payload = {"bots": [{"id": "test", "name": "Test", "model": "gpt-4"}]}
        config_file.write_text(json.dumps(payload))

        mock_db = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_restore = AsyncMock(return_value={"bots": {"created": 0, "updated": 1}})

        with (
            patch.object(config_export_mod, "settings", MagicMock(CONFIG_STATE_FILE=str(config_file))),
            patch("app.db.engine.async_session", return_value=mock_session_ctx),
            patch("app.services.config_state_restore.restore_config_state_snapshot", mock_restore),
        ):
            await restore_from_file()

        mock_restore.assert_called_once_with(payload, mock_db)
        mock_db.commit.assert_called_once()
