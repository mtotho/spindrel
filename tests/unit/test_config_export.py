"""Unit tests for app.services.config_export."""
import ast
import json
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.config_export import (
    _DEBOUNCE_SECONDS,
    _provider_model_snapshot,
    _provider_snapshot,
    _bot_snapshot,
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


class TestConfigSnapshotShape:
    def test_provider_snapshot_preserves_billing_fields(self):
        provider = MagicMock(
            id="provider-1",
            display_name="Provider",
            provider_type="openai-compatible",
            is_enabled=True,
            base_url="https://example.test",
            api_key="secret",
            tpm_limit=100,
            rpm_limit=10,
            config={"extra_headers": {"X-Test": "1"}},
            billing_type="plan",
            plan_cost=20.0,
            plan_period="monthly",
            models=[],
        )

        snapshot = _provider_snapshot(provider)

        assert snapshot["billing_type"] == "plan"
        assert snapshot["plan_cost"] == 20.0
        assert snapshot["plan_period"] == "monthly"

    def test_provider_model_snapshot_preserves_runtime_capability_fields(self):
        model = MagicMock(
            id=7,
            provider_id="provider-1",
            model_id="gpt-test",
            display_name="GPT Test",
            max_tokens=128000,
            context_window=128000,
            max_output_tokens=8192,
            input_cost_per_1m="1.00",
            output_cost_per_1m="4.00",
            cached_input_cost_per_1m="0.10",
            no_system_messages=True,
            supports_tools=False,
            supports_vision=False,
            supports_reasoning=True,
            supports_prompt_caching=True,
            supports_structured_output=True,
            supports_image_generation=True,
            prompt_style="xml",
            extra_body={"reasoning": {"effort": "medium"}},
        )

        snapshot = _provider_model_snapshot(model)

        assert snapshot == {
            "id": 7,
            "provider_id": "provider-1",
            "model_id": "gpt-test",
            "display_name": "GPT Test",
            "max_tokens": 128000,
            "context_window": 128000,
            "max_output_tokens": 8192,
            "input_cost_per_1m": "1.00",
            "output_cost_per_1m": "4.00",
            "cached_input_cost_per_1m": "0.10",
            "no_system_messages": True,
            "supports_tools": False,
            "supports_vision": False,
            "supports_reasoning": True,
            "supports_prompt_caching": True,
            "supports_structured_output": True,
            "supports_image_generation": True,
            "prompt_style": "xml",
            "extra_body": {"reasoning": {"effort": "medium"}},
        }

    def test_bot_snapshot_preserves_provider_companion_fields(self):
        bot = MagicMock(
            id="bot-1",
            name="Bot",
            model="gpt-test",
            model_provider_id="provider-1",
            system_prompt="",
            local_tools=[],
            mcp_servers=[],
            client_tools=[],
            pinned_tools=[],
            skills=[],
            docker_sandbox_profiles=[],
            tool_retrieval=True,
            tool_similarity_threshold=None,
            persona=False,
            context_compaction=True,
            compaction_interval=None,
            compaction_keep_turns=None,
            compaction_model="gpt-compact",
            compaction_model_provider_id="provider-compact",
            memory_knowledge_compaction_prompt=None,
            compaction_prompt_template_id=None,
            audio_input="transcribe",
            memory_config={},
            filesystem_indexes=[],
            host_exec_config={"enabled": False},
            filesystem_access=[],
            display_name=None,
            avatar_url=None,
            avatar_emoji=None,
            integration_config={},
            tool_result_config={},
            memory_max_inject_chars=None,
            delegation_config={},
            model_params={},
            bot_sandbox={},
            workspace={"enabled": False},
            attachment_summarization_enabled=True,
            attachment_summary_model="gpt-vision",
            attachment_summary_model_provider_id="provider-vision",
            attachment_text_max_chars=1000,
            attachment_vision_concurrency=2,
            fallback_models=[],
            user_id=None,
            api_key_id=None,
            memory_scheme="workspace-files",
            history_mode="file",
            context_pruning=True,
        )

        snapshot = _bot_snapshot(bot)

        assert snapshot["compaction_model_provider_id"] == "provider-compact"
        assert snapshot["attachment_summary_model_provider_id"] == "provider-vision"

    def test_assemble_config_state_remains_coordinator_sized(self):
        source = Path(config_export_mod.__file__).read_text()
        tree = ast.parse(source)
        fn = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "assemble_config_state"
        )

        assert fn.end_lineno - fn.lineno + 1 <= 45


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
