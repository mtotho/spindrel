"""Unit tests for workspace indexing resolution service."""
from unittest.mock import patch

import pytest

from app.agent.bots import WorkspaceIndexingConfig
from app.services.workspace_indexing import resolve_indexing


class TestResolveIndexing:
    """Test the three-tier cascade: bot-explicit > workspace default > global env."""

    def _defaults(self):
        return WorkspaceIndexingConfig()

    def test_all_defaults_uses_global(self):
        """When no bot or workspace overrides, uses global defaults."""
        result = resolve_indexing(self._defaults(), {}, None)
        assert result["patterns"] == ["**/*.py", "**/*.md", "**/*.yaml"]
        assert result["similarity_threshold"] == 0.30
        assert result["top_k"] == 8
        assert result["watch"] is True
        assert result["cooldown_seconds"] == 300

    def test_workspace_overrides_global(self):
        """Workspace-level config overrides global defaults."""
        ws_cfg = {
            "patterns": ["**/*.ts", "**/*.tsx"],
            "similarity_threshold": 0.20,
            "top_k": 15,
            "watch": False,
            "cooldown_seconds": 120,
        }
        result = resolve_indexing(self._defaults(), {}, ws_cfg)
        assert result["patterns"] == ["**/*.ts", "**/*.tsx"]
        assert result["similarity_threshold"] == 0.20
        assert result["top_k"] == 15
        assert result["watch"] is False
        assert result["cooldown_seconds"] == 120

    def test_bot_explicit_overrides_workspace(self):
        """Bot-explicit values override workspace defaults."""
        bot_indexing = WorkspaceIndexingConfig(
            patterns=["**/*.py"],
            similarity_threshold=0.10,
            top_k=5,
            watch=False,
            cooldown_seconds=60,
        )
        bot_raw = {
            "indexing": {
                "patterns": ["**/*.py"],
                "similarity_threshold": 0.10,
                "top_k": 5,
                "watch": False,
                "cooldown_seconds": 60,
            }
        }
        ws_cfg = {
            "patterns": ["**/*.ts"],
            "similarity_threshold": 0.25,
            "top_k": 12,
        }
        result = resolve_indexing(bot_indexing, bot_raw, ws_cfg)
        assert result["patterns"] == ["**/*.py"]
        assert result["similarity_threshold"] == 0.10
        assert result["top_k"] == 5
        assert result["watch"] is False
        assert result["cooldown_seconds"] == 60

    def test_partial_bot_override_falls_through(self):
        """Bot overrides only specific keys; others fall through to workspace/global."""
        bot_indexing = WorkspaceIndexingConfig(
            patterns=["**/*.py"],
            similarity_threshold=None,  # not overridden
            top_k=None,  # not overridden
        )
        bot_raw = {"indexing": {"patterns": ["**/*.py"]}}  # only patterns explicit
        ws_cfg = {"similarity_threshold": 0.22, "top_k": 10}
        result = resolve_indexing(bot_indexing, bot_raw, ws_cfg)
        assert result["patterns"] == ["**/*.py"]  # bot explicit
        assert result["similarity_threshold"] == 0.22  # workspace
        assert result["top_k"] == 10  # workspace
        assert result["watch"] is True  # global default
        assert result["cooldown_seconds"] == 300  # global default

    def test_partial_workspace_falls_to_global(self):
        """Workspace sets some keys; others fall through to global."""
        ws_cfg = {"patterns": ["**/*.md"]}
        result = resolve_indexing(self._defaults(), {}, ws_cfg)
        assert result["patterns"] == ["**/*.md"]
        assert result["similarity_threshold"] == 0.30  # global
        assert result["top_k"] == 8  # global

    def test_empty_bot_raw_no_explicit(self):
        """Empty bot workspace raw means no explicit overrides."""
        ws_cfg = {"patterns": ["**/*.rs"], "top_k": 20}
        result = resolve_indexing(self._defaults(), {}, ws_cfg)
        assert result["patterns"] == ["**/*.rs"]
        assert result["top_k"] == 20

    def test_none_ws_indexing_config(self):
        """None workspace config (no workspace-level overrides)."""
        result = resolve_indexing(self._defaults(), {}, None)
        assert result["similarity_threshold"] == 0.30
        assert result["top_k"] == 8

    def test_bot_none_threshold_falls_to_workspace(self):
        """Bot similarity_threshold=None falls through to workspace."""
        bot_indexing = WorkspaceIndexingConfig(similarity_threshold=None, top_k=None)
        ws_cfg = {"similarity_threshold": 0.15}
        result = resolve_indexing(bot_indexing, {}, ws_cfg)
        assert result["similarity_threshold"] == 0.15

    def test_bot_zero_threshold_is_explicit(self):
        """Bot similarity_threshold=0 is an explicit value, not None."""
        bot_indexing = WorkspaceIndexingConfig(similarity_threshold=0.0)
        bot_raw = {"indexing": {"similarity_threshold": 0.0}}
        ws_cfg = {"similarity_threshold": 0.25}
        result = resolve_indexing(bot_indexing, bot_raw, ws_cfg)
        # similarity_threshold checks `is not None`, so 0.0 is explicit
        assert result["similarity_threshold"] == 0.0

    def test_custom_global_settings(self):
        """Global settings override when nothing else is set."""
        with patch("app.services.workspace_indexing.settings") as mock:
            mock.FS_INDEX_SIMILARITY_THRESHOLD = 0.50
            mock.FS_INDEX_TOP_K = 20
            mock.FS_INDEX_COOLDOWN_SECONDS = 600
            result = resolve_indexing(self._defaults(), {}, None)
        assert result["similarity_threshold"] == 0.50
        assert result["top_k"] == 20
        assert result["cooldown_seconds"] == 600
