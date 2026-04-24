"""Unit tests for Phase 5 provider capability column additions.

Covers the new ``supports_prompt_caching``, ``supports_structured_output``,
``cached_input_cost_per_1m``, ``context_window``, ``max_output_tokens``, and
``extra_body`` columns plus the per-provider ``extra_headers`` JSON sub-key.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.db.models import ProviderConfig, ProviderModel


pytestmark = pytest.mark.asyncio


async def _seed(db_session, *, model_id: str = "claude-sonnet-4-7", **flags):
    """Add a single provider + provider_model row using the new columns."""
    db_session.add(
        ProviderConfig(
            id="test-provider",
            provider_type=flags.pop("provider_type", "openai-compatible"),
            display_name="Test",
            is_enabled=True,
            config=flags.pop("provider_config", {}),
        )
    )
    db_session.add(
        ProviderModel(
            provider_id="test-provider",
            model_id=model_id,
            **flags,
        )
    )
    await db_session.commit()


def _factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class TestPromptCachingCache:
    async def test_cache_populated_from_db_column(self, engine, db_session):
        from app.services import providers

        await _seed(db_session, supports_prompt_caching=True)

        with patch("app.services.providers.async_session", _factory(engine)):
            await providers.load_providers()

        assert providers.supports_prompt_caching("claude-sonnet-4-7") is True
        assert providers.supports_prompt_caching("unknown-model") is False

    async def test_replaces_string_sniff_in_prompt_cache_module(
        self, engine, db_session, monkeypatch
    ):
        """`should_apply_cache_control` must consult the DB cache, not match
        on ``"claude" in model.lower()``. Use a non-claude name with the flag
        toggled true to prove it."""
        from app.agent import prompt_cache as pc
        from app.services import providers

        # Monkeypatch settings.PROMPT_CACHE_ENABLED to true
        monkeypatch.setattr(pc.settings, "PROMPT_CACHE_ENABLED", True)

        await _seed(
            db_session,
            model_id="minimax-pro",
            supports_prompt_caching=True,
        )
        with patch("app.services.providers.async_session", _factory(engine)):
            await providers.load_providers()

        # No "claude" in the name — only the DB flag drives the gate.
        assert pc.should_apply_cache_control("minimax-pro", "test-provider") is True
        # And a model without the flag should be False even with the
        # provider type as openai-compatible (no legacy fallback).
        assert pc.should_apply_cache_control("gpt-4o", "test-provider") is False


class TestStructuredOutputCache:
    async def test_cache_populated_from_db_column(self, engine, db_session):
        from app.services import providers

        await _seed(db_session, supports_structured_output=True)
        with patch("app.services.providers.async_session", _factory(engine)):
            await providers.load_providers()

        assert providers.supports_structured_output("claude-sonnet-4-7") is True
        assert providers.supports_structured_output("unknown-model") is False


class TestExtraBodyAccessor:
    async def test_returns_dict_when_set(self, engine, db_session):
        from app.services import providers

        await _seed(
            db_session,
            extra_body={"options": {"num_ctx": 16384, "num_predict": 4096}},
        )
        with patch("app.services.providers.async_session", _factory(engine)):
            await providers.load_providers()

        body = providers.get_provider_model_extra_body(
            "claude-sonnet-4-7", "test-provider"
        )
        assert body == {"options": {"num_ctx": 16384, "num_predict": 4096}}

    async def test_returns_empty_when_unset(self, engine, db_session):
        from app.services import providers

        await _seed(db_session)
        with patch("app.services.providers.async_session", _factory(engine)):
            await providers.load_providers()

        assert providers.get_provider_model_extra_body(
            "claude-sonnet-4-7", "test-provider"
        ) == {}

    async def test_returns_fresh_copy_so_mutation_doesnt_corrupt_cache(
        self, engine, db_session
    ):
        from app.services import providers

        await _seed(db_session, extra_body={"options": {"num_ctx": 1024}})
        with patch("app.services.providers.async_session", _factory(engine)):
            await providers.load_providers()

        body = providers.get_provider_model_extra_body(
            "claude-sonnet-4-7", "test-provider"
        )
        body["options"]["num_ctx"] = 99999

        # Re-read — cache must be unmodified.
        again = providers.get_provider_model_extra_body(
            "claude-sonnet-4-7", "test-provider"
        )
        assert again == {"options": {"num_ctx": 1024}}


class TestExtraHeadersAccessor:
    async def test_loads_from_provider_config_subkey(self, engine, db_session):
        from app.services import providers

        await _seed(
            db_session,
            provider_config={
                "extra_headers": {
                    "HTTP-Referer": "https://spindrel.local",
                    "X-Title": "Spindrel",
                }
            },
        )
        with patch("app.services.providers.async_session", _factory(engine)):
            await providers.load_providers()

        headers = providers.get_provider_extra_headers("test-provider")
        assert headers == {
            "HTTP-Referer": "https://spindrel.local",
            "X-Title": "Spindrel",
        }

    async def test_empty_when_provider_has_no_extra_headers(
        self, engine, db_session
    ):
        from app.services import providers

        await _seed(db_session)
        with patch("app.services.providers.async_session", _factory(engine)):
            await providers.load_providers()

        assert providers.get_provider_extra_headers("test-provider") == {}


class TestCachedInputCostAccessor:
    async def test_lookup_returns_string_value(self, engine, db_session):
        from app.services import providers

        await _seed(db_session, cached_input_cost_per_1m="$0.30")
        with patch("app.services.providers.async_session", _factory(engine)):
            await providers.load_providers()

        assert providers.get_cached_input_cost_per_1m(
            "claude-sonnet-4-7", "test-provider"
        ) == "$0.30"
        assert providers.get_cached_input_cost_per_1m(
            "unknown", "test-provider"
        ) is None


class TestContextWindowAccessors:
    async def test_split_input_vs_output_tokens(self, engine, db_session):
        from app.services import providers

        await _seed(
            db_session,
            context_window=200000,
            max_output_tokens=8192,
        )
        with patch("app.services.providers.async_session", _factory(engine)):
            await providers.load_providers()

        assert providers.get_provider_model_context_window(
            "claude-sonnet-4-7", "test-provider"
        ) == 200000
        assert providers.get_provider_model_max_output_tokens(
            "claude-sonnet-4-7", "test-provider"
        ) == 8192
