"""Tests for model→provider auto-resolution."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# providers.py: resolve_provider_for_model
# ---------------------------------------------------------------------------


def _fake_provider(provider_type: str) -> SimpleNamespace:
    return SimpleNamespace(provider_type=provider_type)


class TestResolveProviderForModel:
    """Unit tests for the reverse-index lookup in providers.py."""

    def test_returns_provider_for_openai_compatible(self):
        """resolve_provider_for_model returns provider_id for chat-completions-compatible providers."""
        from app.services import providers

        old_idx, old_reg = providers._model_to_provider, providers._registry
        try:
            providers._model_to_provider = {"gpt-4o": "openai-prod"}
            providers._registry = {"openai-prod": _fake_provider("openai-compatible")}
            assert providers.resolve_provider_for_model("gpt-4o") == "openai-prod"
        finally:
            providers._model_to_provider = old_idx
            providers._registry = old_reg

    def test_skips_anthropic_compatible_provider(self):
        """Anthropic-compatible providers are skipped (not chat/completions compatible)."""
        from app.services import providers

        old_idx, old_reg = providers._model_to_provider, providers._registry
        try:
            providers._model_to_provider = {"MiniMax-Text-01": "mini-max"}
            providers._registry = {"mini-max": _fake_provider("anthropic-compatible")}
            assert providers.resolve_provider_for_model("MiniMax-Text-01") is None
        finally:
            providers._model_to_provider = old_idx
            providers._registry = old_reg

    def test_skips_anthropic_provider(self):
        """Direct anthropic providers are skipped."""
        from app.services import providers

        old_idx, old_reg = providers._model_to_provider, providers._registry
        try:
            providers._model_to_provider = {"claude-opus-4-6": "claude-direct"}
            providers._registry = {"claude-direct": _fake_provider("anthropic")}
            assert providers.resolve_provider_for_model("claude-opus-4-6") is None
        finally:
            providers._model_to_provider = old_idx
            providers._registry = old_reg

    def test_returns_litellm_provider(self):
        """LiteLLM providers are chat-completions compatible."""
        from app.services import providers

        old_idx, old_reg = providers._model_to_provider, providers._registry
        try:
            providers._model_to_provider = {"gpt-4o": "my-litellm"}
            providers._registry = {"my-litellm": _fake_provider("litellm")}
            assert providers.resolve_provider_for_model("gpt-4o") == "my-litellm"
        finally:
            providers._model_to_provider = old_idx
            providers._registry = old_reg

    def test_returns_ollama_provider(self):
        """Ollama providers are chat-completions compatible."""
        from app.services import providers

        old_idx, old_reg = providers._model_to_provider, providers._registry
        try:
            providers._model_to_provider = {"llama3": "my-ollama"}
            providers._registry = {"my-ollama": _fake_provider("ollama")}
            assert providers.resolve_provider_for_model("llama3") == "my-ollama"
        finally:
            providers._model_to_provider = old_idx
            providers._registry = old_reg

    def test_returns_none_for_unknown_model(self):
        """resolve_provider_for_model returns None for unregistered models."""
        from app.services import providers

        old_idx = providers._model_to_provider
        try:
            providers._model_to_provider = {"gpt-4o": "openai-prod"}
            assert providers.resolve_provider_for_model("some-unknown-model") is None
        finally:
            providers._model_to_provider = old_idx

    def test_returns_none_when_index_empty(self):
        """resolve_provider_for_model returns None when no providers loaded."""
        from app.services import providers

        old_idx = providers._model_to_provider
        try:
            providers._model_to_provider = {}
            assert providers.resolve_provider_for_model("gpt-4o") is None
        finally:
            providers._model_to_provider = old_idx

    def test_returns_none_when_provider_not_in_registry(self):
        """If model maps to a provider_id not in registry, returns None."""
        from app.services import providers

        old_idx, old_reg = providers._model_to_provider, providers._registry
        try:
            providers._model_to_provider = {"gpt-4o": "ghost-provider"}
            providers._registry = {}
            assert providers.resolve_provider_for_model("gpt-4o") is None
        finally:
            providers._model_to_provider = old_idx
            providers._registry = old_reg


# ---------------------------------------------------------------------------
# llm.py: _prepare_call_params auto-resolution
# ---------------------------------------------------------------------------

class TestPrepareCallParamsAutoResolution:
    """Verify _prepare_call_params resolves provider_id when not supplied."""

    @patch("app.services.providers.resolve_provider_for_model", return_value="openai-prod")
    @patch("app.services.providers.get_llm_client")
    @patch("app.services.providers.requires_system_message_folding", return_value=False)
    @patch("app.services.providers.model_supports_tools", return_value=True)
    @patch("app.agent.model_params.filter_model_params", return_value={})
    def test_resolves_provider_when_none(
        self, _params, _tools, _fold, mock_client, mock_resolve
    ):
        """When provider_id is None, resolver should be called and result used."""
        from app.agent.llm import _prepare_call_params

        _prepare_call_params(
            model="gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
            tools_param=None,
            tool_choice=None,
            provider_id=None,
            model_params=None,
        )
        mock_resolve.assert_called_once_with("gpt-4o")
        mock_client.assert_called_once_with("openai-prod")

    @patch("app.services.providers.resolve_provider_for_model")
    @patch("app.services.providers.get_llm_client")
    @patch("app.services.providers.requires_system_message_folding", return_value=False)
    @patch("app.services.providers.model_supports_tools", return_value=True)
    @patch("app.agent.model_params.filter_model_params", return_value={})
    def test_skips_resolution_when_provider_explicit(
        self, _params, _tools, _fold, mock_client, mock_resolve
    ):
        """When provider_id is already supplied, resolver should NOT be called."""
        from app.agent.llm import _prepare_call_params

        _prepare_call_params(
            model="gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
            tools_param=None,
            tool_choice=None,
            provider_id="my-explicit-provider",
            model_params=None,
        )
        mock_resolve.assert_not_called()
        mock_client.assert_called_once_with("my-explicit-provider")

    @patch("app.services.providers.resolve_provider_for_model", return_value=None)
    @patch("app.services.providers.get_llm_client")
    @patch("app.services.providers.requires_system_message_folding", return_value=False)
    @patch("app.services.providers.model_supports_tools", return_value=True)
    @patch("app.agent.model_params.filter_model_params", return_value={})
    def test_falls_back_to_none_when_unresolvable(
        self, _params, _tools, _fold, mock_client, mock_resolve
    ):
        """When resolver returns None, get_llm_client gets None (→ .env fallback)."""
        from app.agent.llm import _prepare_call_params

        _prepare_call_params(
            model="some-litellm-model",
            messages=[{"role": "user", "content": "hi"}],
            tools_param=None,
            tool_choice=None,
            provider_id=None,
            model_params=None,
        )
        mock_resolve.assert_called_once_with("some-litellm-model")
        mock_client.assert_called_once_with(None)
