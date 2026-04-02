"""Tests for provider driver architecture and Ollama support."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.provider_drivers import (
    DRIVER_REGISTRY,
    PROVIDER_TYPES,
    get_driver,
)
from app.services.provider_drivers.anthropic_driver import (
    AnthropicCompatibleDriver,
    AnthropicDriver,
    _ANTHROPIC_MODELS,
)
from app.services.provider_drivers.base import ProviderCapabilities, ProviderDriver
from app.services.provider_drivers.litellm_driver import LiteLLMDriver
from app.services.provider_drivers.ollama_driver import OllamaDriver
from app.services.provider_drivers.openai_driver import OpenAICompatibleDriver, OpenAIDriver


# ---------------------------------------------------------------------------
# Driver registry
# ---------------------------------------------------------------------------


class TestDriverRegistry:
    def test_all_types_registered(self):
        assert len(DRIVER_REGISTRY) == 6
        expected = {"litellm", "openai", "openai-compatible", "anthropic", "anthropic-compatible", "ollama"}
        assert set(DRIVER_REGISTRY.keys()) == expected

    def test_provider_types_list_matches_registry(self):
        assert set(PROVIDER_TYPES) == set(DRIVER_REGISTRY.keys())

    def test_get_driver_returns_correct_instance(self):
        assert isinstance(get_driver("litellm"), LiteLLMDriver)
        assert isinstance(get_driver("openai"), OpenAIDriver)
        assert isinstance(get_driver("openai-compatible"), OpenAICompatibleDriver)
        assert isinstance(get_driver("anthropic"), AnthropicDriver)
        assert isinstance(get_driver("anthropic-compatible"), AnthropicCompatibleDriver)
        assert isinstance(get_driver("ollama"), OllamaDriver)

    def test_get_driver_unknown_type_returns_fallback(self):
        """Unknown provider types fall back to OpenAI-compatible driver."""
        driver = get_driver("nonexistent")
        assert isinstance(driver, OpenAICompatibleDriver)

    def test_drivers_are_singletons(self):
        """Same instance is returned on repeated calls."""
        d1 = get_driver("ollama")
        d2 = get_driver("ollama")
        assert d1 is d2


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


class TestDriverCapabilities:
    def test_ollama_capabilities(self):
        caps = get_driver("ollama").capabilities()
        assert caps.list_models is True
        assert caps.pull_model is True
        assert caps.delete_model is True
        assert caps.model_info is True
        assert caps.running_models is True
        assert caps.requires_base_url is True
        assert caps.requires_api_key is False

    def test_openai_capabilities(self):
        caps = get_driver("openai").capabilities()
        assert caps.list_models is True
        assert caps.requires_base_url is False
        assert caps.requires_api_key is True
        assert caps.pull_model is False
        assert caps.delete_model is False

    def test_openai_compatible_capabilities(self):
        caps = get_driver("openai-compatible").capabilities()
        assert caps.list_models is True
        assert caps.requires_base_url is True

    def test_anthropic_capabilities(self):
        caps = get_driver("anthropic").capabilities()
        assert caps.list_models is False
        assert caps.requires_api_key is True
        assert caps.pull_model is False

    def test_anthropic_compatible_capabilities(self):
        caps = get_driver("anthropic-compatible").capabilities()
        assert caps.list_models is True
        assert caps.requires_base_url is True

    def test_litellm_capabilities(self):
        caps = get_driver("litellm").capabilities()
        assert caps.list_models is True
        assert caps.pricing is True
        assert caps.management_key is True
        assert caps.requires_base_url is True

    def test_capabilities_is_dataclass(self):
        from dataclasses import asdict
        caps = get_driver("ollama").capabilities()
        d = asdict(caps)
        assert isinstance(d, dict)
        assert "list_models" in d

    def test_base_driver_default_capabilities(self):
        """Base class returns all-False capabilities."""
        driver = ProviderDriver()
        caps = driver.capabilities()
        assert caps.list_models is False
        assert caps.pull_model is False
        assert caps.requires_api_key is True  # default True


# ---------------------------------------------------------------------------
# make_client
# ---------------------------------------------------------------------------


def _mock_config(**kwargs):
    """Create a mock ProviderConfigRow."""
    config = MagicMock()
    config.id = kwargs.get("id", "test-provider")
    config.provider_type = kwargs.get("provider_type", "openai")
    config.api_key = kwargs.get("api_key", "sk-test")
    config.base_url = kwargs.get("base_url", None)
    config.config = kwargs.get("config", {})
    return config


class TestMakeClient:
    @patch("app.services.provider_drivers.openai_driver.settings")
    def test_openai_client(self, mock_settings):
        mock_settings.LLM_TIMEOUT = 60
        config = _mock_config(api_key="sk-test", base_url=None)
        client = get_driver("openai").make_client(config)
        assert client.api_key == "sk-test"

    @patch("app.services.provider_drivers.openai_driver.settings")
    def test_openai_compatible_with_base_url(self, mock_settings):
        mock_settings.LLM_TIMEOUT = 60
        config = _mock_config(base_url="https://custom.api.com/v1")
        client = get_driver("openai-compatible").make_client(config)
        assert "custom.api.com" in str(client.base_url)

    @patch("app.services.provider_drivers.anthropic_driver.settings")
    def test_anthropic_client_default_url(self, mock_settings):
        mock_settings.LLM_TIMEOUT = 60
        config = _mock_config(api_key="sk-ant-test", base_url=None)
        client = get_driver("anthropic").make_client(config)
        assert "anthropic.com" in str(client.base_url)

    @patch("app.services.provider_drivers.anthropic_driver.settings")
    def test_anthropic_client_has_version_header(self, mock_settings):
        mock_settings.LLM_TIMEOUT = 60
        config = _mock_config(api_key="sk-ant-test", base_url=None)
        client = get_driver("anthropic").make_client(config)
        # The client should have the anthropic-version header set
        assert client._custom_headers.get("anthropic-version") == "2023-06-01"

    @patch("app.services.provider_drivers.litellm_driver.settings")
    def test_litellm_client_fallback_settings(self, mock_settings):
        mock_settings.LLM_TIMEOUT = 60
        mock_settings.LITELLM_BASE_URL = "http://litellm.local:4000"
        mock_settings.LITELLM_API_KEY = "key-from-env"
        config = _mock_config(api_key=None, base_url=None)
        client = get_driver("litellm").make_client(config)
        assert "litellm.local" in str(client.base_url)

    @patch("app.services.provider_drivers.ollama_driver.settings")
    def test_ollama_client_appends_v1(self, mock_settings):
        mock_settings.LLM_TIMEOUT = 60
        config = _mock_config(base_url="http://myollama:11434")
        client = get_driver("ollama").make_client(config)
        assert str(client.base_url).rstrip("/") == "http://myollama:11434/v1"
        assert client.api_key == "ollama"

    @patch("app.services.provider_drivers.ollama_driver.settings")
    def test_ollama_client_default_url(self, mock_settings):
        mock_settings.LLM_TIMEOUT = 60
        config = _mock_config(base_url=None)
        client = get_driver("ollama").make_client(config)
        assert "localhost:11434/v1" in str(client.base_url)


# ---------------------------------------------------------------------------
# OllamaDriver — test_connection
# ---------------------------------------------------------------------------


class TestOllamaTestConnection:
    @pytest.mark.asyncio
    async def test_connection_success(self):
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"models": [{"name": "llama3.1:8b"}, {"name": "mistral:7b"}]}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get = AsyncMock(return_value=mock_response)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            driver = OllamaDriver()
            ok, msg = await driver.test_connection(None, "http://localhost:11434")
            assert ok is True
            assert "2 models" in msg

    @pytest.mark.asyncio
    async def test_connection_failure(self):
        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get = AsyncMock(side_effect=ConnectionError("refused"))
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            driver = OllamaDriver()
            ok, msg = await driver.test_connection(None, "http://localhost:11434")
            assert ok is False
            assert "refused" in msg


# ---------------------------------------------------------------------------
# OllamaDriver — list_models
# ---------------------------------------------------------------------------


class TestOllamaListModels:
    @pytest.mark.asyncio
    async def test_list_models(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "models": [
                {"name": "mistral:7b"},
                {"name": "llama3.1:8b"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get = AsyncMock(return_value=mock_response)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            config = _mock_config(base_url="http://localhost:11434")
            driver = OllamaDriver()
            models = await driver.list_models(config)
            assert models == ["llama3.1:8b", "mistral:7b"]  # sorted

    @pytest.mark.asyncio
    async def test_list_models_enriched(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "models": [
                {
                    "name": "llama3.1:8b",
                    "size": 4_700_000_000,
                    "details": {
                        "parameter_size": "8B",
                        "quantization_level": "Q4_0",
                        "family": "llama",
                    },
                    "modified_at": "2024-01-01T00:00:00Z",
                },
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get = AsyncMock(return_value=mock_response)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            config = _mock_config(base_url="http://localhost:11434")
            driver = OllamaDriver()
            enriched = await driver.list_models_enriched(config)
            assert len(enriched) == 1
            m = enriched[0]
            assert m["id"] == "llama3.1:8b"
            assert m["size_bytes"] == 4_700_000_000
            assert m["parameter_size"] == "8B"
            assert m["quantization"] == "Q4_0"
            assert m["family"] == "llama"


# ---------------------------------------------------------------------------
# OllamaDriver — get_model_info
# ---------------------------------------------------------------------------


class TestOllamaModelInfo:
    @pytest.mark.asyncio
    async def test_get_model_info(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "template": "{{ .System }}\n{{ .Prompt }}",
            "parameters": "stop <|eot_id|>",
            "details": {"family": "llama", "parameter_size": "8B"},
            "model_info": {"general.context_length": 8192},
            "license": "llama3 community license",
            "modelfile": "FROM llama3.1:8b",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post = AsyncMock(return_value=mock_response)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            config = _mock_config(base_url="http://localhost:11434")
            driver = OllamaDriver()
            info = await driver.get_model_info(config, "llama3.1:8b")
            assert info["template"] is not None
            assert info["parameters"] == "stop <|eot_id|>"
            assert info["details"]["family"] == "llama"
            # Verify /api/show was called with correct body
            instance.post.assert_called_once()
            call_args = instance.post.call_args
            assert call_args[1]["json"]["name"] == "llama3.1:8b"


# ---------------------------------------------------------------------------
# OllamaDriver — get_running_models
# ---------------------------------------------------------------------------


class TestOllamaRunningModels:
    @pytest.mark.asyncio
    async def test_get_running_models(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "models": [
                {
                    "name": "llama3.1:8b",
                    "model": "llama3.1:8b",
                    "size": 4_700_000_000,
                    "size_vram": 4_700_000_000,
                    "digest": "abc123",
                    "expires_at": "2024-01-01T01:00:00Z",
                    "details": {"family": "llama"},
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get = AsyncMock(return_value=mock_response)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            config = _mock_config(base_url="http://localhost:11434")
            driver = OllamaDriver()
            running = await driver.get_running_models(config)
            assert len(running) == 1
            assert running[0]["name"] == "llama3.1:8b"
            assert running[0]["size_vram"] == 4_700_000_000
            assert running[0]["digest"] == "abc123"


# ---------------------------------------------------------------------------
# OllamaDriver — delete_model
# ---------------------------------------------------------------------------


class TestOllamaDeleteModel:
    @pytest.mark.asyncio
    async def test_delete_model(self):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.request = AsyncMock(return_value=mock_response)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            config = _mock_config(base_url="http://localhost:11434")
            driver = OllamaDriver()
            result = await driver.delete_model(config, "llama3.1:8b")
            assert result is True
            # Verify DELETE /api/delete was called
            instance.request.assert_called_once()
            call_args = instance.request.call_args
            assert call_args[0][0] == "DELETE"
            assert "/api/delete" in call_args[0][1]
            assert call_args[1]["json"]["name"] == "llama3.1:8b"


# ---------------------------------------------------------------------------
# AnthropicDriver — list_models returns hardcoded list
# ---------------------------------------------------------------------------


class TestAnthropicDriver:
    @pytest.mark.asyncio
    async def test_list_models_returns_hardcoded(self):
        config = _mock_config()
        driver = AnthropicDriver()
        models = await driver.list_models(config)
        assert models == list(_ANTHROPIC_MODELS)
        assert "claude-opus-4-6" in models

    @pytest.mark.asyncio
    async def test_test_connection_always_ok(self):
        driver = AnthropicDriver()
        ok, msg = await driver.test_connection("sk-test", None)
        assert ok is True
        assert "Credentials OK" in msg


# ---------------------------------------------------------------------------
# providers.py delegation — _make_client uses driver
# ---------------------------------------------------------------------------


class TestProvidersIntegration:
    @patch("app.services.provider_drivers.openai_driver.settings")
    def test_make_client_delegates_to_driver(self, mock_settings):
        """The _make_client function in providers.py should delegate to the driver."""
        mock_settings.LLM_TIMEOUT = 60
        from app.services.providers import _make_client

        config = _mock_config(provider_type="openai", api_key="sk-test")
        client = _make_client(config)
        assert client.api_key == "sk-test"

    @patch("app.services.provider_drivers.ollama_driver.settings")
    def test_make_client_ollama(self, mock_settings):
        mock_settings.LLM_TIMEOUT = 60
        from app.services.providers import _make_client

        config = _mock_config(provider_type="ollama", base_url="http://myollama:11434")
        client = _make_client(config)
        assert "myollama:11434/v1" in str(client.base_url)
        assert client.api_key == "ollama"


# ---------------------------------------------------------------------------
# model_params — ollama family support
# ---------------------------------------------------------------------------


class TestOllamaModelParams:
    def test_ollama_in_model_param_support(self):
        from app.agent.model_params import MODEL_PARAM_SUPPORT
        assert "ollama" in MODEL_PARAM_SUPPORT
        params = MODEL_PARAM_SUPPORT["ollama"]
        assert "temperature" in params
        assert "max_tokens" in params
        assert "frequency_penalty" in params
        assert "presence_penalty" in params

    def test_get_supported_params_ollama_prefix(self):
        from app.agent.model_params import get_supported_params
        params = get_supported_params("ollama/llama3.1:8b")
        assert "temperature" in params
        assert "max_tokens" in params
