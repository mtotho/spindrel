"""Tests for pricing data in model sync and list_models_enriched."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.provider_drivers.litellm_driver import LiteLLMDriver


class TestLiteLLMListModelsEnriched:
    @pytest.mark.asyncio
    async def test_enriched_merges_pricing(self):
        """list_models_enriched should merge pricing from fetch_pricing into model list."""
        driver = LiteLLMDriver()
        config = MagicMock()

        with (
            patch.object(driver, "list_models", new_callable=AsyncMock, return_value=["gpt-4", "gpt-3.5-turbo"]),
            patch.object(driver, "fetch_pricing", new_callable=AsyncMock, return_value={
                "gpt-4": {"input_cost_per_1m": "$30.00", "output_cost_per_1m": "$60.00", "max_tokens": 128000},
                "gpt-3.5-turbo": {"input_cost_per_1m": "$0.50", "output_cost_per_1m": "$1.50", "max_tokens": 16385},
            }),
        ):
            result = await driver.list_models_enriched(config)

        assert len(result) == 2
        gpt4 = next(m for m in result if m["id"] == "gpt-4")
        assert gpt4["input_cost_per_1m"] == "$30.00"
        assert gpt4["output_cost_per_1m"] == "$60.00"
        assert gpt4["max_tokens"] == 128000

        gpt35 = next(m for m in result if m["id"] == "gpt-3.5-turbo")
        assert gpt35["input_cost_per_1m"] == "$0.50"

    @pytest.mark.asyncio
    async def test_enriched_handles_missing_pricing(self):
        """Models without pricing data should still be listed, just without cost fields."""
        driver = LiteLLMDriver()
        config = MagicMock()

        with (
            patch.object(driver, "list_models", new_callable=AsyncMock, return_value=["local-model"]),
            patch.object(driver, "fetch_pricing", new_callable=AsyncMock, return_value={}),
        ):
            result = await driver.list_models_enriched(config)

        assert len(result) == 1
        assert result[0]["id"] == "local-model"
        assert "input_cost_per_1m" not in result[0]
        assert "output_cost_per_1m" not in result[0]

    @pytest.mark.asyncio
    async def test_enriched_handles_partial_pricing(self):
        """Models with only some pricing fields should include what's available."""
        driver = LiteLLMDriver()
        config = MagicMock()

        with (
            patch.object(driver, "list_models", new_callable=AsyncMock, return_value=["model-a"]),
            patch.object(driver, "fetch_pricing", new_callable=AsyncMock, return_value={
                "model-a": {"input_cost_per_1m": "$1.00", "output_cost_per_1m": None, "max_tokens": 4096},
            }),
        ):
            result = await driver.list_models_enriched(config)

        assert result[0]["input_cost_per_1m"] == "$1.00"
        assert "output_cost_per_1m" not in result[0]
        assert result[0]["max_tokens"] == 4096


class TestWarmModelInfoCacheIncludesOpenAICompatible:
    @pytest.mark.asyncio
    async def test_includes_openai_compatible_providers(self):
        """_warm_model_info_cache should walk openai-compatible providers too."""
        from app.services.providers import _warm_model_info_cache

        mock_provider = MagicMock()
        mock_provider.id = "gemini-provider"
        mock_provider.provider_type = "openai-compatible"
        mock_provider.base_url = "https://gemini-proxy.example.com"
        mock_provider.api_key = "test-key"
        mock_provider.extra_config = {}

        with (
            patch("app.services.providers._registry", {"gemini-provider": mock_provider}),
            patch("app.services.providers.settings") as mock_settings,
            patch("app.services.provider_drivers.litellm_driver._fetch_litellm_model_info", new_callable=AsyncMock) as mock_fetch,
            patch("app.services.providers._model_info_cache", {}) as cache,
        ):
            mock_settings.LLM_BASE_URL = None
            mock_fetch.return_value = {"gemini-pro": {"max_tokens": 32000}}

            await _warm_model_info_cache()

            # Should have been called with the openai-compatible provider's URL
            mock_fetch.assert_called_once()
            assert "gemini-provider" in cache
