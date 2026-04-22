"""Tests for model tiers and plain bot-to-bot delegation."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig
from app.services.server_config import resolve_model_tier


def _make_bot(**overrides):
    defaults = dict(
        id="parent-bot",
        name="Parent",
        model="gpt-4",
        system_prompt="You are a parent bot.",
        delegate_bots=["child-bot"],
        memory=MemoryConfig(),
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


class TestTierResolution:
    def test_global_tier_resolves(self):
        with patch(
            "app.services.server_config._model_tiers",
            {"fast": {"model": "gemini/gemini-2.5-flash-lite", "provider_id": None}},
        ):
            assert resolve_model_tier("fast") == ("gemini/gemini-2.5-flash-lite", None)

    def test_channel_override_takes_precedence(self):
        with patch(
            "app.services.server_config._model_tiers",
            {"fast": {"model": "gemini/gemini-2.5-flash-lite", "provider_id": None}},
        ):
            channel_overrides = {"fast": {"model": "gpt-4.1-nano", "provider_id": "openai-1"}}
            assert resolve_model_tier("fast", channel_overrides) == ("gpt-4.1-nano", "openai-1")

    def test_missing_tier_returns_none(self):
        with patch("app.services.server_config._model_tiers", {}):
            assert resolve_model_tier("fast") is None


class TestDelegateToolTierResolution:
    @pytest.mark.asyncio
    async def test_explicit_tier_passed_to_run_deferred(self):
        from app.tools.local.delegation import delegate_to_agent

        mock_run_deferred = AsyncMock(return_value="task-123")

        with patch("app.tools.local.delegation.current_session_id") as m_sid, \
             patch("app.tools.local.delegation.current_client_id") as m_cid, \
             patch("app.tools.local.delegation.current_channel_id") as m_chid, \
             patch("app.tools.local.delegation.current_bot_id") as m_bid, \
             patch("app.tools.local.delegation.current_dispatch_type") as m_dt, \
             patch("app.tools.local.delegation.current_dispatch_config") as m_dc, \
             patch("app.agent.bots.get_bot", return_value=_make_bot()), \
             patch("app.agent.bots.resolve_bot_id", return_value=MagicMock(id="child-bot")), \
             patch("app.services.delegation.delegation_service") as mock_svc:
            m_sid.get.return_value = uuid.uuid4()
            m_cid.get.return_value = None
            m_chid.get.return_value = uuid.uuid4()
            m_bid.get.return_value = "parent-bot"
            m_dt.get.return_value = None
            m_dc.get.return_value = {}
            mock_svc.run_deferred = mock_run_deferred

            result = await delegate_to_agent(
                bot_id="child-bot",
                prompt="run tests",
                model_tier="fast",
            )

        assert "task-123" in result
        assert mock_run_deferred.call_args.kwargs["model_tier"] == "fast"


class TestDeferredDelegationTier:
    @pytest.mark.asyncio
    async def test_tier_resolved_to_execution_config(self):
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
