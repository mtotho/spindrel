"""Integration tests for the orchestrator bot system: admin tools, landing channel, seeding, wildcard delegation."""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig
from app.db.models import Bot as BotRow, Channel, Session
from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_orchestrator_bot(**overrides) -> BotConfig:
    defaults = dict(
        id="orchestrator",
        name="Orchestrator",
        model="test/model",
        system_prompt="You are the orchestrator.",
        delegate_bots=["*"],
        local_tools=["get_system_status", "manage_bot", "manage_channel", "manage_integration"],
        memory=MemoryConfig(enabled=False),
        knowledge=KnowledgeConfig(enabled=False),
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


def _make_test_bot(bot_id="test-bot", **overrides) -> BotConfig:
    defaults = dict(
        id=bot_id,
        name=bot_id.replace("-", " ").title(),
        model="test/model",
        system_prompt="Test bot.",
        memory=MemoryConfig(enabled=False),
        knowledge=KnowledgeConfig(enabled=False),
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


# ---------------------------------------------------------------------------
# ensure_orchestrator_channel
# ---------------------------------------------------------------------------

class TestEnsureOrchestratorChannel:
    async def test_creates_channel_when_bot_exists(self, db_session):
        """When orchestrator bot is seeded, ensure_orchestrator_channel creates the landing channel."""
        # Seed orchestrator bot into DB
        bot = BotRow(
            id="orchestrator",
            name="Orchestrator",
            model="test/model",
            system_prompt="test",
            local_tools=[],
            mcp_servers=[],
            client_tools=[],
            pinned_tools=[],
            skills=[],
            docker_sandbox_profiles=[],
            tool_retrieval=True,
            persona=False,
            context_compaction=True,
            audio_input="transcribe",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(bot)
        await db_session.commit()

        # Register bot in memory
        orchestrator_config = _make_orchestrator_bot()
        registry = {"orchestrator": orchestrator_config}

        with patch("app.agent.bots._registry", registry), \
             patch("app.agent.bots.get_bot", side_effect=lambda bid: registry.get(bid) or (_ for _ in ()).throw(Exception(f"not found: {bid}"))), \
             patch("app.services.channels.async_session") as mock_session_ctx:
            # Make async_session return our test session
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db_session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            from app.services.channels import ensure_orchestrator_channel
            await ensure_orchestrator_channel()

        # Verify channel was created
        from sqlalchemy import select
        result = await db_session.execute(
            select(Channel).where(Channel.client_id == "orchestrator:home")
        )
        ch = result.scalar_one_or_none()
        assert ch is not None
        assert ch.bot_id == "orchestrator"
        assert ch.name == "Home"
        assert ch.active_session_id is not None

    async def test_skips_when_no_orchestrator_bot(self, db_session):
        """When orchestrator bot doesn't exist, ensure_orchestrator_channel is a no-op."""
        registry = {}
        with patch("app.agent.bots._registry", registry), \
             patch("app.agent.bots.get_bot", side_effect=Exception("not found")):
            from app.services.channels import ensure_orchestrator_channel
            await ensure_orchestrator_channel()

        # No channel created
        from sqlalchemy import select
        result = await db_session.execute(
            select(Channel).where(Channel.client_id == "orchestrator:home")
        )
        assert result.scalar_one_or_none() is None

    async def test_idempotent(self, db_session):
        """Calling ensure_orchestrator_channel twice doesn't duplicate."""
        bot = BotRow(
            id="orchestrator",
            name="Orchestrator",
            model="test/model",
            system_prompt="test",
            local_tools=[],
            mcp_servers=[],
            client_tools=[],
            pinned_tools=[],
            skills=[],
            docker_sandbox_profiles=[],
            tool_retrieval=True,
            persona=False,
            context_compaction=True,
            audio_input="transcribe",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(bot)
        await db_session.commit()

        orchestrator_config = _make_orchestrator_bot()
        registry = {"orchestrator": orchestrator_config}

        with patch("app.agent.bots._registry", registry), \
             patch("app.agent.bots.get_bot", side_effect=lambda bid: registry[bid]), \
             patch("app.services.channels.async_session") as mock_session_ctx:
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db_session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            from app.services.channels import ensure_orchestrator_channel
            await ensure_orchestrator_channel()
            await ensure_orchestrator_channel()

        from sqlalchemy import select
        result = await db_session.execute(
            select(Channel).where(Channel.client_id == "orchestrator:home")
        )
        channels = result.scalars().all()
        assert len(channels) == 1


# ---------------------------------------------------------------------------
# Wildcard delegation
# ---------------------------------------------------------------------------

class TestWildcardDelegation:
    def test_wildcard_allows_any_delegate(self):
        """delegate_bots: ["*"] allows delegation to any bot."""
        parent = _make_orchestrator_bot(delegate_bots=["*"])
        allowed = parent.delegate_bots or []
        # The check: "*" not in allowed and delegate_bot_id not in allowed
        assert "*" in allowed  # wildcard present
        # Any bot_id should pass the check
        for bot_id in ["assistant", "researcher", "coder", "random-bot"]:
            assert "*" in allowed or bot_id in allowed

    def test_explicit_list_rejects_unlisted(self):
        """Without wildcard, only listed bots are allowed."""
        parent = _make_test_bot(delegate_bots=["assistant"])
        allowed = parent.delegate_bots or []
        assert "*" not in allowed
        assert "assistant" in allowed
        assert "researcher" not in allowed

    def test_empty_delegate_bots(self):
        """Empty delegate_bots rejects all."""
        parent = _make_test_bot(delegate_bots=[])
        allowed = parent.delegate_bots or []
        assert "*" not in allowed
        assert "assistant" not in allowed


# ---------------------------------------------------------------------------
# System bot seeding
# ---------------------------------------------------------------------------

class TestSystemBotSeeding:
    async def test_seed_scans_system_bots_dir(self, db_session):
        """seed_bots_from_yaml should scan app/data/system_bots/ in addition to bots/."""
        from pathlib import Path
        from app.agent.bots import SYSTEM_BOTS_DIR

        # Verify the system bots directory exists and has orchestrator.yaml
        assert SYSTEM_BOTS_DIR.exists()
        yaml_files = list(SYSTEM_BOTS_DIR.glob("*.yaml"))
        assert any(f.name == "orchestrator.yaml" for f in yaml_files)

    async def test_orchestrator_yaml_valid(self):
        """orchestrator.yaml should be valid and have required fields."""
        import yaml
        from app.agent.bots import SYSTEM_BOTS_DIR

        path = SYSTEM_BOTS_DIR / "orchestrator.yaml"
        assert path.exists()

        with open(path) as f:
            data = yaml.safe_load(f)

        assert data["id"] == "orchestrator"
        assert data["name"] == "Orchestrator"
        assert "model" in data
        assert "system_prompt" in data
        assert "get_system_status" in data["local_tools"]
        assert "manage_bot" in data["local_tools"]
        assert "manage_channel" in data["local_tools"]
        assert "manage_integration" in data["local_tools"]
        assert "*" in data["delegate_bots"]

    async def test_yaml_data_to_row_dict(self):
        """_yaml_data_to_row_dict should handle orchestrator YAML fields."""
        import yaml
        from app.agent.bots import SYSTEM_BOTS_DIR, _yaml_data_to_row_dict

        with open(SYSTEM_BOTS_DIR / "orchestrator.yaml") as f:
            data = yaml.safe_load(f)

        row_dict = _yaml_data_to_row_dict(data)
        assert row_dict["id"] == "orchestrator"
        assert row_dict["local_tools"] == data["local_tools"]
        assert row_dict["delegation_config"]["delegate_bots"] == ["*"]


# ---------------------------------------------------------------------------
# Admin tools — get_system_status
# ---------------------------------------------------------------------------

class TestGetSystemStatus:
    async def test_returns_fresh_install(self, db_session):
        """get_system_status returns is_fresh_install=True when no user bots/channels exist."""
        with patch("app.agent.bots.list_bots", return_value=[_make_orchestrator_bot()]), \
             patch("app.tools.local.admin_system.async_session") as mock_session_ctx, \
             patch("integrations.discover_setup_status", return_value=[]), \
             patch("app.services.providers.list_providers", return_value=[]):
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db_session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            from app.tools.local.admin_system import get_system_status
            result = json.loads(await get_system_status())

        assert result["is_fresh_install"] is True
        assert result["bots"] == []  # orchestrator excluded
        assert result["channels"] == []

    async def test_returns_existing_system(self, db_session):
        """get_system_status returns is_fresh_install=False when user bots exist."""
        user_bot = _make_test_bot("assistant")
        orchestrator = _make_orchestrator_bot()

        # Create a user channel
        ch = Channel(
            id=uuid.uuid4(),
            name="General",
            bot_id="assistant",
            client_id="ui:general",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(ch)
        await db_session.commit()

        with patch("app.agent.bots.list_bots", return_value=[orchestrator, user_bot]), \
             patch("app.tools.local.admin_system.async_session") as mock_session_ctx, \
             patch("integrations.discover_setup_status", return_value=[]), \
             patch("app.services.providers.list_providers", return_value=[]):
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db_session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            from app.tools.local.admin_system import get_system_status
            result = json.loads(await get_system_status())

        assert result["is_fresh_install"] is False
        assert len(result["bots"]) == 1
        assert result["bots"][0]["id"] == "assistant"
        assert len(result["channels"]) == 1


# ---------------------------------------------------------------------------
# Admin tools — manage_bot
# ---------------------------------------------------------------------------

class TestManageBot:
    async def test_list_bots(self):
        """manage_bot(action='list') returns all bots."""
        bots = [_make_orchestrator_bot(), _make_test_bot("assistant")]
        with patch("app.agent.bots.list_bots", return_value=bots):
            from app.tools.local.admin_bots import manage_bot
            result = json.loads(await manage_bot(action="list"))

        assert len(result) == 2
        assert result[0]["id"] == "orchestrator"
        assert result[1]["id"] == "assistant"

    async def test_get_bot(self):
        """manage_bot(action='get') returns bot details."""
        bot = _make_test_bot("assistant")
        with patch("app.agent.bots.get_bot", return_value=bot):
            from app.tools.local.admin_bots import manage_bot
            result = json.loads(await manage_bot(action="get", bot_id="assistant"))

        assert result["id"] == "assistant"
        assert result["model"] == "test/model"

    async def test_get_bot_not_found(self):
        """manage_bot(action='get') returns error for unknown bot."""
        with patch("app.agent.bots.get_bot", side_effect=Exception("not found")):
            from app.tools.local.admin_bots import manage_bot
            result = json.loads(await manage_bot(action="get", bot_id="nonexistent"))

        assert "error" in result

    async def test_create_requires_model(self):
        """manage_bot(action='create') requires model in config."""
        with patch("app.agent.bots.get_bot", side_effect=Exception("not found")):
            from app.tools.local.admin_bots import manage_bot
            result = json.loads(await manage_bot(action="create", bot_id="new-bot", config={"name": "New Bot"}))

        assert "error" in result
        assert "model" in result["error"]


# ---------------------------------------------------------------------------
# Admin tools — manage_channel
# ---------------------------------------------------------------------------

class TestManageChannel:
    async def test_list_channels(self, db_session):
        """manage_channel(action='list') returns all channels."""
        ch = Channel(
            id=uuid.uuid4(),
            name="Test Channel",
            bot_id="test-bot",
            client_id="ui:test",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(ch)
        await db_session.commit()

        with patch("app.tools.local.admin_channels.async_session") as mock_session_ctx:
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db_session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            from app.tools.local.admin_channels import manage_channel
            result = json.loads(await manage_channel(action="list"))

        assert len(result) == 1
        assert result[0]["name"] == "Test Channel"

    async def test_create_requires_bot_id(self):
        """manage_channel(action='create') requires bot_id."""
        from app.tools.local.admin_channels import manage_channel
        result = json.loads(await manage_channel(action="create", name="Test"))
        assert "error" in result
        assert "bot_id" in result["error"]

    async def test_create_validates_bot_exists(self):
        """manage_channel(action='create') validates bot exists."""
        with patch("app.agent.bots.get_bot", side_effect=Exception("not found")):
            from app.tools.local.admin_channels import manage_channel
            result = json.loads(await manage_channel(action="create", name="Test", bot_id="nonexistent"))

        assert "error" in result
        assert "not found" in result["error"]


# ---------------------------------------------------------------------------
# Admin tools — manage_integration
# ---------------------------------------------------------------------------

class TestManageIntegration:
    async def test_list_integrations(self):
        """manage_integration(action='list') returns discovered integrations."""
        mock_integrations = [
            {
                "id": "slack",
                "name": "Slack",
                "status": "ready",
                "has_process": True,
                "process_status": {"status": "running"},
                "env_vars": [{"key": "SLACK_BOT_TOKEN", "required": True, "is_set": True}],
            },
        ]
        with patch("integrations.discover_setup_status", return_value=mock_integrations):
            from app.tools.local.admin_integrations import manage_integration
            result = json.loads(await manage_integration(action="list"))

        assert len(result) == 1
        assert result[0]["id"] == "slack"
        assert result[0]["process_status"] == "running"

    async def test_requires_integration_id(self):
        """Non-list actions require integration_id."""
        from app.tools.local.admin_integrations import manage_integration
        result = json.loads(await manage_integration(action="get_settings"))
        assert "error" in result
        assert "integration_id" in result["error"]
