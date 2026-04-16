"""Tests for model tiers — named tier resolution and delegation integration.

Covers:
- Global tier resolution: resolve_model_tier with global tiers
- Channel override precedence: channel overrides take priority over global
- Missing tier returns None
- Delegate tool: explicit model_tier param works, delegate entry default used, no tier = no override
- Deferred delegation: Task gets model_override from tier resolution
- Carapace delegate entry model_tier parsing
"""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig
from app.agent.carapaces import (
    DelegateEntry,
    ResolvedCarapace,
    _registry,
    resolve_carapaces,
)
from app.services.server_config import resolve_model_tier


@pytest.fixture(autouse=True)
def clear_registry():
    """Ensure a clean carapace registry for each test."""
    _registry.clear()
    yield
    _registry.clear()


def _make_bot(**overrides):
    defaults = dict(
        id="parent-bot",
        name="Parent",
        model="gpt-4",
        system_prompt="You are a parent bot.",
        delegate_bots=["child-bot"],
        memory=MemoryConfig(),
        carapaces=["orchestrator"],
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


def _make_carapace(id, *, delegates=None, includes=None, **kwargs):
    return {
        "id": id,
        "name": id,
        "description": f"Description of {id}",
        "skills": [],
        "local_tools": [],
        "mcp_tools": [],
        "pinned_tools": [],
        "system_prompt_fragment": None,
        "includes": includes or [],
        "delegates": delegates or [],
        "tags": [],
        "source_path": None,
        "source_type": "manual",
        "content_hash": None,
    }


# ---------------------------------------------------------------------------
# Tier resolution
# ---------------------------------------------------------------------------

class TestTierResolution:
    def test_global_tier_resolves(self):
        """Global tier mapping resolves to (model, provider_id)."""
        with patch(
            "app.services.server_config._model_tiers",
            {"fast": {"model": "gemini/gemini-2.5-flash-lite", "provider_id": None}},
        ):
            result = resolve_model_tier("fast")
            assert result == ("gemini/gemini-2.5-flash-lite", None)

    def test_global_tier_with_provider(self):
        """Global tier with explicit provider_id."""
        with patch(
            "app.services.server_config._model_tiers",
            {"frontier": {"model": "claude-sonnet-4-6", "provider_id": "anthropic-1"}},
        ):
            result = resolve_model_tier("frontier")
            assert result == ("claude-sonnet-4-6", "anthropic-1")

    def test_channel_override_takes_precedence(self):
        """Channel-level override wins over global tier mapping."""
        with patch(
            "app.services.server_config._model_tiers",
            {"fast": {"model": "gemini/gemini-2.5-flash-lite", "provider_id": None}},
        ):
            channel_overrides = {"fast": {"model": "gpt-4.1-nano", "provider_id": "openai-1"}}
            result = resolve_model_tier("fast", channel_overrides)
            assert result == ("gpt-4.1-nano", "openai-1")

    def test_channel_override_partial(self):
        """Channel overrides only apply to the tier they override; others fall through to global."""
        with patch(
            "app.services.server_config._model_tiers",
            {
                "fast": {"model": "gemini/gemini-2.5-flash-lite", "provider_id": None},
                "standard": {"model": "gemini/gemini-2.5-flash", "provider_id": None},
            },
        ):
            channel_overrides = {"fast": {"model": "gpt-4.1-nano", "provider_id": None}}
            # fast is overridden
            assert resolve_model_tier("fast", channel_overrides) == ("gpt-4.1-nano", None)
            # standard falls through to global
            assert resolve_model_tier("standard", channel_overrides) == ("gemini/gemini-2.5-flash", None)

    def test_missing_tier_returns_none(self):
        """Unconfigured tier returns None."""
        with patch("app.services.server_config._model_tiers", {}):
            assert resolve_model_tier("fast") is None

    def test_empty_model_in_tier_returns_none(self):
        """Tier with empty model string returns None."""
        with patch(
            "app.services.server_config._model_tiers",
            {"fast": {"model": "", "provider_id": None}},
        ):
            assert resolve_model_tier("fast") is None

    def test_channel_override_empty_model_falls_through(self):
        """Channel override with empty model falls through to global."""
        with patch(
            "app.services.server_config._model_tiers",
            {"fast": {"model": "gemini/gemini-2.5-flash-lite", "provider_id": None}},
        ):
            channel_overrides = {"fast": {"model": "", "provider_id": None}}
            result = resolve_model_tier("fast", channel_overrides)
            assert result == ("gemini/gemini-2.5-flash-lite", None)


# ---------------------------------------------------------------------------
# Carapace delegate entry model_tier
# ---------------------------------------------------------------------------

class TestDelegateEntryModelTier:
    def test_model_tier_parsed_from_delegate(self):
        """model_tier is parsed from carapace delegate entries."""
        _registry["orch"] = _make_carapace(
            "orch",
            delegates=[
                {"id": "qa", "type": "carapace", "description": "QA", "model_tier": "standard"},
                {"id": "bug-fix", "type": "carapace", "description": "Fix bugs"},
            ],
        )
        resolved = resolve_carapaces(["orch"])
        qa_delegate = next(d for d in resolved.delegates if d.id == "qa")
        bugfix_delegate = next(d for d in resolved.delegates if d.id == "bug-fix")
        assert qa_delegate.model_tier == "standard"
        assert bugfix_delegate.model_tier is None

    def test_model_tier_preserved_through_includes(self):
        """model_tier on delegate entries survives includes resolution."""
        _registry["inner"] = _make_carapace(
            "inner",
            delegates=[{"id": "helper", "type": "carapace", "description": "Help", "model_tier": "fast"}],
        )
        _registry["outer"] = _make_carapace("outer", includes=["inner"])
        resolved = resolve_carapaces(["outer"])
        helper = next(d for d in resolved.delegates if d.id == "helper")
        assert helper.model_tier == "fast"


# ---------------------------------------------------------------------------
# Delegate tool — tier resolution
# ---------------------------------------------------------------------------

class TestDelegateToolTierResolution:
    """Test delegate_to_agent tool's model_tier handling."""

    @pytest.mark.asyncio
    async def test_explicit_tier_passed_to_run_deferred(self):
        """Explicit model_tier param is forwarded to run_deferred."""
        from app.tools.local.delegation import delegate_to_agent

        _registry["orchestrator"] = _make_carapace(
            "orchestrator",
            delegates=[{"id": "qa", "type": "carapace", "description": "QA"}],
        )

        mock_run_deferred = AsyncMock(return_value="task-123")

        with patch("app.tools.local.delegation.current_session_id") as m_sid, \
             patch("app.tools.local.delegation.current_client_id") as m_cid, \
             patch("app.tools.local.delegation.current_channel_id") as m_chid, \
             patch("app.tools.local.delegation.current_bot_id") as m_bid, \
             patch("app.tools.local.delegation.current_dispatch_type") as m_dt, \
             patch("app.tools.local.delegation.current_dispatch_config") as m_dc, \
             patch("app.agent.bots.get_bot", return_value=_make_bot()), \
             patch("app.agent.bots.resolve_bot_id", return_value=None), \
             patch("app.agent.carapaces.get_carapace", return_value={"id": "qa"}), \
             patch("app.services.delegation.delegation_service") as mock_svc:
            m_sid.get.return_value = uuid.uuid4()
            m_cid.get.return_value = None
            m_chid.get.return_value = uuid.uuid4()
            m_bid.get.return_value = "parent-bot"
            m_dt.get.return_value = None
            m_dc.get.return_value = {}
            mock_svc.run_deferred = mock_run_deferred

            result = await delegate_to_agent(
                bot_id="qa",
                prompt="run tests",
                model_tier="fast",
            )

            assert "task-123" in result
            call_kwargs = mock_run_deferred.call_args.kwargs
            assert call_kwargs["model_tier"] == "fast"

    @pytest.mark.asyncio
    async def test_delegate_entry_tier_used_as_default(self):
        """When no explicit tier, the delegate entry's model_tier is used."""
        from app.tools.local.delegation import delegate_to_agent

        _registry["orchestrator"] = _make_carapace(
            "orchestrator",
            delegates=[
                {"id": "qa", "type": "carapace", "description": "QA", "model_tier": "standard"},
            ],
        )

        mock_run_deferred = AsyncMock(return_value="task-456")

        with patch("app.tools.local.delegation.current_session_id") as m_sid, \
             patch("app.tools.local.delegation.current_client_id") as m_cid, \
             patch("app.tools.local.delegation.current_channel_id") as m_chid, \
             patch("app.tools.local.delegation.current_bot_id") as m_bid, \
             patch("app.tools.local.delegation.current_dispatch_type") as m_dt, \
             patch("app.tools.local.delegation.current_dispatch_config") as m_dc, \
             patch("app.agent.bots.get_bot", return_value=_make_bot()), \
             patch("app.agent.bots.resolve_bot_id", return_value=None), \
             patch("app.agent.carapaces.get_carapace", return_value={"id": "qa"}), \
             patch("app.services.delegation.delegation_service") as mock_svc:
            m_sid.get.return_value = uuid.uuid4()
            m_cid.get.return_value = None
            m_chid.get.return_value = uuid.uuid4()
            m_bid.get.return_value = "parent-bot"
            m_dt.get.return_value = None
            m_dc.get.return_value = {}
            mock_svc.run_deferred = mock_run_deferred

            result = await delegate_to_agent(
                bot_id="qa",
                prompt="run tests",
            )

            assert "task-456" in result
            call_kwargs = mock_run_deferred.call_args.kwargs
            assert call_kwargs["model_tier"] == "standard"

    @pytest.mark.asyncio
    async def test_no_tier_passes_none(self):
        """When no explicit tier and no delegate entry tier, model_tier is None."""
        from app.tools.local.delegation import delegate_to_agent

        _registry["orchestrator"] = _make_carapace(
            "orchestrator",
            delegates=[
                {"id": "qa", "type": "carapace", "description": "QA"},
            ],
        )

        mock_run_deferred = AsyncMock(return_value="task-789")

        with patch("app.tools.local.delegation.current_session_id") as m_sid, \
             patch("app.tools.local.delegation.current_client_id") as m_cid, \
             patch("app.tools.local.delegation.current_channel_id") as m_chid, \
             patch("app.tools.local.delegation.current_bot_id") as m_bid, \
             patch("app.tools.local.delegation.current_dispatch_type") as m_dt, \
             patch("app.tools.local.delegation.current_dispatch_config") as m_dc, \
             patch("app.agent.bots.get_bot", return_value=_make_bot()), \
             patch("app.agent.bots.resolve_bot_id", return_value=None), \
             patch("app.agent.carapaces.get_carapace", return_value={"id": "qa"}), \
             patch("app.services.delegation.delegation_service") as mock_svc:
            m_sid.get.return_value = uuid.uuid4()
            m_cid.get.return_value = None
            m_chid.get.return_value = uuid.uuid4()
            m_bid.get.return_value = "parent-bot"
            m_dt.get.return_value = None
            m_dc.get.return_value = {}
            mock_svc.run_deferred = mock_run_deferred

            result = await delegate_to_agent(
                bot_id="qa",
                prompt="run tests",
            )

            assert "task-789" in result
            call_kwargs = mock_run_deferred.call_args.kwargs
            assert call_kwargs["model_tier"] is None

    @pytest.mark.asyncio
    async def test_explicit_tier_overrides_delegate_entry(self):
        """Explicit model_tier param overrides the delegate entry default."""
        from app.tools.local.delegation import delegate_to_agent

        _registry["orchestrator"] = _make_carapace(
            "orchestrator",
            delegates=[
                {"id": "qa", "type": "carapace", "description": "QA", "model_tier": "standard"},
            ],
        )

        mock_run_deferred = AsyncMock(return_value="task-abc")

        with patch("app.tools.local.delegation.current_session_id") as m_sid, \
             patch("app.tools.local.delegation.current_client_id") as m_cid, \
             patch("app.tools.local.delegation.current_channel_id") as m_chid, \
             patch("app.tools.local.delegation.current_bot_id") as m_bid, \
             patch("app.tools.local.delegation.current_dispatch_type") as m_dt, \
             patch("app.tools.local.delegation.current_dispatch_config") as m_dc, \
             patch("app.agent.bots.get_bot", return_value=_make_bot()), \
             patch("app.agent.bots.resolve_bot_id", return_value=None), \
             patch("app.agent.carapaces.get_carapace", return_value={"id": "qa"}), \
             patch("app.services.delegation.delegation_service") as mock_svc:
            m_sid.get.return_value = uuid.uuid4()
            m_cid.get.return_value = None
            m_chid.get.return_value = uuid.uuid4()
            m_bid.get.return_value = "parent-bot"
            m_dt.get.return_value = None
            m_dc.get.return_value = {}
            mock_svc.run_deferred = mock_run_deferred

            result = await delegate_to_agent(
                bot_id="qa",
                prompt="run tests",
                model_tier="frontier",
            )

            assert "task-abc" in result
            call_kwargs = mock_run_deferred.call_args.kwargs
            assert call_kwargs["model_tier"] == "frontier"


# ---------------------------------------------------------------------------
# Deferred delegation — tier to model_override in execution_config
# ---------------------------------------------------------------------------

class TestDeferredDelegationTier:
    @pytest.mark.asyncio
    async def test_tier_resolved_to_execution_config(self):
        """run_deferred resolves tier and stores model_override in execution_config."""
        from app.services.delegation import DelegationService

        svc = DelegationService()
        parent = _make_bot()

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        captured_task = None
        original_add = mock_db.add

        def capture_add(task):
            nonlocal captured_task
            captured_task = task
            return original_add(task)

        mock_db.add = capture_add

        async def fake_refresh(task):
            task.id = uuid.uuid4()

        mock_db.refresh = fake_refresh

        with patch("app.services.delegation.async_session", return_value=mock_db), \
             patch(
                 "app.services.server_config.resolve_model_tier",
                 return_value=("gemini/gemini-2.5-flash-lite", None),
             ), \
             patch("app.agent.context.current_channel_model_tier_overrides") as m_overrides:
            m_overrides.get.return_value = None

            await svc.run_deferred(
                parent_bot=parent,
                delegate_bot_id="child-bot",
                prompt="scan files",
                dispatch_type=None,
                dispatch_config=None,
                scheduled_at=None,
                model_tier="fast",
            )

        assert captured_task is not None
        assert captured_task.execution_config["model_override"] == "gemini/gemini-2.5-flash-lite"

    @pytest.mark.asyncio
    async def test_no_tier_no_model_override(self):
        """run_deferred without tier doesn't add model_override."""
        from app.services.delegation import DelegationService

        svc = DelegationService()
        parent = _make_bot()

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        captured_task = None
        original_add = mock_db.add

        def capture_add(task):
            nonlocal captured_task
            captured_task = task
            return original_add(task)

        mock_db.add = capture_add

        async def fake_refresh(task):
            task.id = uuid.uuid4()

        mock_db.refresh = fake_refresh

        with patch("app.services.delegation.async_session", return_value=mock_db):
            await svc.run_deferred(
                parent_bot=parent,
                delegate_bot_id="child-bot",
                prompt="scan files",
                dispatch_type=None,
                dispatch_config=None,
                scheduled_at=None,
            )

        assert captured_task is not None
        assert captured_task.execution_config is None

    @pytest.mark.asyncio
    async def test_tier_with_carapace_merges_execution_config(self):
        """run_deferred with both carapace_ids and model_tier merges execution_config."""
        from app.services.delegation import DelegationService

        svc = DelegationService()
        parent = _make_bot()

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        captured_task = None
        original_add = mock_db.add

        def capture_add(task):
            nonlocal captured_task
            captured_task = task
            return original_add(task)

        mock_db.add = capture_add

        async def fake_refresh(task):
            task.id = uuid.uuid4()

        mock_db.refresh = fake_refresh

        with patch("app.services.delegation.async_session", return_value=mock_db), \
             patch(
                 "app.services.server_config.resolve_model_tier",
                 return_value=("gemini/gemini-2.5-flash", "provider-1"),
             ), \
             patch("app.agent.context.current_channel_model_tier_overrides") as m_overrides:
            m_overrides.get.return_value = None

            await svc.run_deferred(
                parent_bot=parent,
                delegate_bot_id="child-bot",
                prompt="scan files",
                dispatch_type=None,
                dispatch_config=None,
                scheduled_at=None,
                carapace_ids=["qa"],
                model_tier="standard",
            )

        assert captured_task is not None
        exec_cfg = captured_task.execution_config
        assert exec_cfg["carapaces"] == ["qa"]
        assert exec_cfg["model_override"] == "gemini/gemini-2.5-flash"
        assert exec_cfg["model_provider_id_override"] == "provider-1"

    @pytest.mark.asyncio
    async def test_unresolved_tier_no_model_override(self):
        """If tier doesn't resolve (not configured), no model_override is added."""
        from app.services.delegation import DelegationService

        svc = DelegationService()
        parent = _make_bot()

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        captured_task = None
        original_add = mock_db.add

        def capture_add(task):
            nonlocal captured_task
            captured_task = task
            return original_add(task)

        mock_db.add = capture_add

        async def fake_refresh(task):
            task.id = uuid.uuid4()

        mock_db.refresh = fake_refresh

        with patch("app.services.delegation.async_session", return_value=mock_db), \
             patch(
                 "app.services.server_config.resolve_model_tier",
                 return_value=None,
             ), \
             patch("app.agent.context.current_channel_model_tier_overrides") as m_overrides:
            m_overrides.get.return_value = None

            await svc.run_deferred(
                parent_bot=parent,
                delegate_bot_id="child-bot",
                prompt="scan files",
                dispatch_type=None,
                dispatch_config=None,
                scheduled_at=None,
                model_tier="nonexistent",
            )

        assert captured_task is not None
        assert captured_task.execution_config is None
