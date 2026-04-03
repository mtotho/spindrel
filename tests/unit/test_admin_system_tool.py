"""Unit tests for get_system_status tool."""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.local.admin_system import get_system_status


def _mock_provider(**overrides):
    defaults = dict(
        id="openai-main",
        provider_type="openai",
        display_name="OpenAI Production",
        is_enabled=True,
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


class _FakeBot:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", "my-bot")
        self.name = kwargs.get("name", "My Bot")
        self.model = kwargs.get("model", "gpt-4o")


@pytest.fixture
def _mock_deps():
    """Patch all external dependencies of get_system_status."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []  # no channels
    mock_db.execute = AsyncMock(return_value=mock_result)

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.tools.local.admin_system.async_session", return_value=mock_ctx),
        patch("app.agent.bots.list_bots", return_value=[]),
        patch("app.services.providers.list_providers", return_value=[]),
        patch("integrations.discover_setup_status", return_value=[]),
    ):
        yield


@pytest.mark.asyncio
async def test_provider_display_name_not_name(_mock_deps):
    """Regression: ProviderConfig has display_name, not name."""
    providers = [
        _mock_provider(id="openai", display_name="OpenAI"),
        _mock_provider(id="anthropic", display_name="Anthropic"),
    ]
    with patch("app.services.providers.list_providers", return_value=providers):
        result = json.loads(await get_system_status())

    assert len(result["providers"]) == 2
    assert result["providers"][0]["name"] == "OpenAI"
    assert result["providers"][1]["name"] == "Anthropic"


@pytest.mark.asyncio
async def test_basic_structure(_mock_deps):
    """get_system_status returns all expected top-level keys."""
    result = json.loads(await get_system_status())
    assert "bots" in result
    assert "channels" in result
    assert "integrations" in result
    assert "providers" in result
    assert "config" in result
    assert "is_fresh_install" in result


@pytest.mark.asyncio
async def test_fresh_install_detection(_mock_deps):
    """No bots + no channels = fresh install."""
    result = json.loads(await get_system_status())
    assert result["is_fresh_install"] is True


@pytest.mark.asyncio
async def test_not_fresh_with_bots(_mock_deps):
    """Having bots means not a fresh install."""
    bots = [_FakeBot(id="helper", name="Helper", model="gpt-4o")]
    with patch("app.agent.bots.list_bots", return_value=bots):
        result = json.loads(await get_system_status())
    assert result["is_fresh_install"] is False


@pytest.mark.asyncio
async def test_system_bots_excluded(_mock_deps):
    """Orchestrator and default bots should be excluded from the list."""
    bots = [
        _FakeBot(id="orchestrator", name="Orchestrator"),
        _FakeBot(id="default", name="Default"),
        _FakeBot(id="helper", name="Helper"),
    ]
    with patch("app.agent.bots.list_bots", return_value=bots):
        result = json.loads(await get_system_status())
    assert len(result["bots"]) == 1
    assert result["bots"][0]["id"] == "helper"
