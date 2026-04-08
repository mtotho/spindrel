"""Tier 3: Model smoke tests — verify each configured model/provider works.

Parametrized over E2E_SMOKE_MODELS. Each model gets 3 tests: basic chat,
tool calling, and streaming. Catches provider API changes and model regressions.

Each test creates its own temporary bot and cleans it up after.
"""

from __future__ import annotations

import re

import pytest

from ..harness.client import E2EClient
from ..harness.config import E2EConfig


def _model_configs(config: E2EConfig) -> list[dict]:
    """Return smoke model configs, each with at least a 'model' key."""
    return config.smoke_models


def _model_id(model_cfg: dict) -> str:
    """Human-readable ID for parametrize."""
    return model_cfg["model"]


@pytest.fixture(scope="session")
def smoke_model_configs(e2e_config: E2EConfig) -> list[dict]:
    return _model_configs(e2e_config)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize tests over smoke_models from config."""
    if "model_cfg" in metafunc.fixturenames:
        config = E2EConfig.from_env()
        models = _model_configs(config)
        metafunc.parametrize("model_cfg", models, ids=[_model_id(m) for m in models])


@pytest.fixture
async def temp_bot(client: E2EClient, model_cfg: dict):
    """Create a temporary bot for this model, clean up after."""
    bot_id = await client.create_temp_bot(
        model=model_cfg["model"],
        provider_id=model_cfg.get("provider_id"),
    )
    yield bot_id
    await client.delete_bot(bot_id)


# ---------------------------------------------------------------------------
# Tests — 3 per model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_model_can_chat(client: E2EClient, temp_bot: str, model_cfg: dict) -> None:
    """Model can handle a basic non-streaming chat request."""
    cid = client.new_client_id()
    resp = await client.chat(
        "Say exactly: 'smoke test ok'",
        bot_id=temp_bot,
        client_id=cid,
    )
    assert resp.response, f"Model {model_cfg['model']} returned empty response"
    assert resp.session_id, f"Model {model_cfg['model']} returned no session_id"


@pytest.mark.asyncio
async def test_model_can_call_tools(client: E2EClient, temp_bot: str, model_cfg: dict) -> None:
    """Model can call a tool (get_current_time) and return the result."""
    cid = client.new_client_id()
    resp = await client.chat(
        "What is the current time right now? Use your time tool.",
        bot_id=temp_bot,
        client_id=cid,
    )
    assert re.search(r"\d{1,2}:\d{2}", resp.response), (
        f"Model {model_cfg['model']} should return time but got: {resp.response[:200]}"
    )


@pytest.mark.asyncio
async def test_model_can_stream(client: E2EClient, temp_bot: str, model_cfg: dict) -> None:
    """Model can handle streaming and produce proper SSE events."""
    cid = client.new_client_id()
    result = await client.chat_stream(
        "Say exactly: 'stream test ok'",
        bot_id=temp_bot,
        client_id=cid,
    )
    assert len(result.events) > 0, f"Model {model_cfg['model']} produced no events"
    assert result.response_text, f"Model {model_cfg['model']} produced no response text"
    assert not result.error_events, (
        f"Model {model_cfg['model']} produced errors: {result.error_events}"
    )
