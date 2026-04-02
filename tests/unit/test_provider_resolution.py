"""Tests for model→provider auto-resolution."""
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# providers.py: resolve_provider_for_model
# ---------------------------------------------------------------------------

class TestResolveProviderForModel:
    """Unit tests for the reverse-index lookup in providers.py."""

    def test_returns_provider_when_model_registered(self):
        """resolve_provider_for_model returns the provider_id for a known model."""
        from app.services import providers

        old = providers._model_to_provider
        try:
            providers._model_to_provider = {
                "claude-sonnet-4-20250514": "anthropic-prod",
                "gpt-4o": "openai-prod",
            }
            assert providers.resolve_provider_for_model("claude-sonnet-4-20250514") == "anthropic-prod"
            assert providers.resolve_provider_for_model("gpt-4o") == "openai-prod"
        finally:
            providers._model_to_provider = old

    def test_returns_none_for_unknown_model(self):
        """resolve_provider_for_model returns None for unregistered models."""
        from app.services import providers

        old = providers._model_to_provider
        try:
            providers._model_to_provider = {"gpt-4o": "openai-prod"}
            assert providers.resolve_provider_for_model("some-unknown-model") is None
        finally:
            providers._model_to_provider = old

    def test_returns_none_when_index_empty(self):
        """resolve_provider_for_model returns None when no providers loaded."""
        from app.services import providers

        old = providers._model_to_provider
        try:
            providers._model_to_provider = {}
            assert providers.resolve_provider_for_model("gpt-4o") is None
        finally:
            providers._model_to_provider = old


# ---------------------------------------------------------------------------
# llm.py: _prepare_call_params auto-resolution
# ---------------------------------------------------------------------------

class TestPrepareCallParamsAutoResolution:
    """Verify _prepare_call_params resolves provider_id when not supplied."""

    @patch("app.services.providers.resolve_provider_for_model", return_value="anthropic-prod")
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
            model="claude-sonnet-4-20250514",
            messages=[{"role": "user", "content": "hi"}],
            tools_param=None,
            tool_choice=None,
            provider_id=None,
            model_params=None,
        )
        mock_resolve.assert_called_once_with("claude-sonnet-4-20250514")
        # The resolved provider_id should be passed to get_llm_client
        mock_client.assert_called_once_with("anthropic-prod")

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
            model="claude-sonnet-4-20250514",
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
