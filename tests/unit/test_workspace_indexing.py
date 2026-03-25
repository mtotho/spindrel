"""Unit tests for workspace indexing resolution service."""
import os
from unittest.mock import patch, MagicMock

import pytest

from app.agent.bots import BotConfig, IndexSegment, WorkspaceConfig, WorkspaceIndexingConfig
from app.services.workspace_indexing import resolve_indexing, _resolve_segments, get_all_roots


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

    def test_include_bots_from_config(self):
        """include_bots is passed through from bot config."""
        bot_indexing = WorkspaceIndexingConfig(include_bots=["baking-bot", "olivia-bot"])
        result = resolve_indexing(bot_indexing, {}, None)
        assert result["include_bots"] == ["baking-bot", "olivia-bot"]

    def test_include_bots_defaults_empty(self):
        """include_bots defaults to empty list."""
        result = resolve_indexing(self._defaults(), {}, None)
        assert result["include_bots"] == []

    def test_embedding_model_defaults_to_global(self):
        """When no bot or workspace override, uses global EMBEDDING_MODEL."""
        result = resolve_indexing(self._defaults(), {}, None)
        assert result["embedding_model"] == "text-embedding-3-small"

    def test_embedding_model_workspace_overrides_global(self):
        """Workspace embedding_model overrides global."""
        ws_cfg = {"embedding_model": "text-embedding-3-large"}
        result = resolve_indexing(self._defaults(), {}, ws_cfg)
        assert result["embedding_model"] == "text-embedding-3-large"

    def test_embedding_model_bot_overrides_workspace(self):
        """Bot embedding_model overrides workspace."""
        bot_indexing = WorkspaceIndexingConfig(embedding_model="custom-model")
        ws_cfg = {"embedding_model": "text-embedding-3-large"}
        result = resolve_indexing(bot_indexing, {}, ws_cfg)
        assert result["embedding_model"] == "custom-model"

    def test_embedding_model_bot_none_falls_to_workspace(self):
        """Bot embedding_model=None falls through to workspace."""
        bot_indexing = WorkspaceIndexingConfig(embedding_model=None)
        ws_cfg = {"embedding_model": "text-embedding-3-large"}
        result = resolve_indexing(bot_indexing, {}, ws_cfg)
        assert result["embedding_model"] == "text-embedding-3-large"

    def test_embedding_model_custom_global(self):
        """Custom global EMBEDDING_MODEL when nothing else set."""
        with patch("app.services.workspace_indexing.settings") as mock:
            mock.EMBEDDING_MODEL = "my-custom-embed"
            mock.FS_INDEX_SIMILARITY_THRESHOLD = 0.30
            mock.FS_INDEX_TOP_K = 8
            mock.FS_INDEX_COOLDOWN_SECONDS = 300
            result = resolve_indexing(self._defaults(), {}, None)
        assert result["embedding_model"] == "my-custom-embed"

    def test_segments_empty_by_default(self):
        """Segments default to empty list."""
        result = resolve_indexing(self._defaults(), {}, None)
        assert result["segments"] == []

    def test_segments_inherit_base_values(self):
        """Segment with all None fields inherits everything from base."""
        bot_indexing = WorkspaceIndexingConfig(
            embedding_model="base-model",
            segments=[IndexSegment(path_prefix="src/")],
        )
        result = resolve_indexing(bot_indexing, {}, None)
        assert len(result["segments"]) == 1
        seg = result["segments"][0]
        assert seg["path_prefix"] == "src/"
        assert seg["embedding_model"] == "base-model"
        assert seg["patterns"] == result["patterns"]
        assert seg["similarity_threshold"] == result["similarity_threshold"]
        assert seg["top_k"] == result["top_k"]

    def test_segments_override_base_values(self):
        """Segment with explicit fields overrides base."""
        bot_indexing = WorkspaceIndexingConfig(
            embedding_model="base-model",
            segments=[
                IndexSegment(
                    path_prefix="docs/",
                    embedding_model="docs-model",
                    similarity_threshold=0.5,
                    top_k=3,
                ),
            ],
        )
        result = resolve_indexing(bot_indexing, {}, None)
        seg = result["segments"][0]
        assert seg["embedding_model"] == "docs-model"
        assert seg["similarity_threshold"] == 0.5
        assert seg["top_k"] == 3
        # patterns not overridden → inherits base
        assert seg["patterns"] == result["patterns"]


class TestResolveSegments:
    """Test _resolve_segments helper directly."""

    def test_empty_segments(self):
        assert _resolve_segments([], {}) == []

    def test_full_inheritance(self):
        base = {
            "embedding_model": "m1",
            "patterns": ["**/*.py"],
            "similarity_threshold": 0.3,
            "top_k": 8,
            "watch": True,
        }
        segs = [IndexSegment(path_prefix="lib/")]
        result = _resolve_segments(segs, base)
        assert result == [{
            "path_prefix": "lib/",
            "embedding_model": "m1",
            "patterns": ["**/*.py"],
            "similarity_threshold": 0.3,
            "top_k": 8,
            "watch": True,
        }]

    def test_partial_override(self):
        base = {
            "embedding_model": "m1",
            "patterns": ["**/*.py"],
            "similarity_threshold": 0.3,
            "top_k": 8,
            "watch": True,
        }
        segs = [IndexSegment(path_prefix="src/", embedding_model="m2", top_k=20)]
        result = _resolve_segments(segs, base)
        assert result[0]["embedding_model"] == "m2"
        assert result[0]["top_k"] == 20
        assert result[0]["patterns"] == ["**/*.py"]  # inherited
        assert result[0]["similarity_threshold"] == 0.3  # inherited


class TestGetAllRoots:
    """Test root directory resolution including include_bots."""

    def test_single_root_no_include_bots(self):
        """Without include_bots, returns only the bot's own root."""
        bot = BotConfig(
            id="sag-bot", name="Sag", model="m", system_prompt="",
            workspace=WorkspaceConfig(enabled=True),
            shared_workspace_id="ws-123",
        )
        mock_ws = MagicMock()
        mock_ws.get_workspace_root.return_value = "/data/shared/ws-123/bots/sag-bot"
        roots = get_all_roots(bot, mock_ws)
        assert roots == ["/data/shared/ws-123/bots/sag-bot"]

    def test_include_bots_adds_extra_roots(self):
        """include_bots expands to additional bots/{id} roots."""
        bot = BotConfig(
            id="sag-bot", name="Sag", model="m", system_prompt="",
            workspace=WorkspaceConfig(
                enabled=True,
                indexing=WorkspaceIndexingConfig(include_bots=["baking-bot", "olivia-bot"]),
            ),
            shared_workspace_id="ws-123",
        )
        mock_ws = MagicMock()
        mock_ws.get_workspace_root.return_value = "/data/shared/ws-123/bots/sag-bot"
        with patch("app.services.shared_workspace.shared_workspace_service") as mock_sws:
            mock_sws.get_host_root.return_value = "/data/shared/ws-123"
            roots = get_all_roots(bot, mock_ws)
        assert roots == [
            "/data/shared/ws-123/bots/sag-bot",
            "/data/shared/ws-123/bots/baking-bot",
            "/data/shared/ws-123/bots/olivia-bot",
        ]

    def test_include_bots_no_shared_workspace(self):
        """include_bots is ignored when bot has no shared_workspace_id."""
        bot = BotConfig(
            id="sag-bot", name="Sag", model="m", system_prompt="",
            workspace=WorkspaceConfig(
                enabled=True,
                indexing=WorkspaceIndexingConfig(include_bots=["baking-bot"]),
            ),
        )
        mock_ws = MagicMock()
        mock_ws.get_workspace_root.return_value = "/data/sag-bot"
        roots = get_all_roots(bot, mock_ws)
        assert roots == ["/data/sag-bot"]

    def test_no_duplicate_roots(self):
        """Own root is not duplicated if it appears in include_bots."""
        bot = BotConfig(
            id="sag-bot", name="Sag", model="m", system_prompt="",
            workspace=WorkspaceConfig(
                enabled=True,
                indexing=WorkspaceIndexingConfig(include_bots=["sag-bot", "baking-bot"]),
            ),
            shared_workspace_id="ws-123",
        )
        mock_ws = MagicMock()
        mock_ws.get_workspace_root.return_value = "/data/shared/ws-123/bots/sag-bot"
        with patch("app.services.shared_workspace.shared_workspace_service") as mock_sws:
            mock_sws.get_host_root.return_value = "/data/shared/ws-123"
            roots = get_all_roots(bot, mock_ws)
        assert roots == [
            "/data/shared/ws-123/bots/sag-bot",
            "/data/shared/ws-123/bots/baking-bot",
        ]
