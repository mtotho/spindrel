"""Unit tests for the generate_image tool — provider resolution and parameter handling."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.local.image import (
    _generate_kwargs,
    _edit_kwargs,
    _is_gemini_model,
    _is_openai_model,
    _resolve_image_client,
)


# ---------------------------------------------------------------------------
# Model detection helpers
# ---------------------------------------------------------------------------

class TestModelDetection:
    def test_openai_models(self):
        assert _is_openai_model("gpt-image-1") is True
        assert _is_openai_model("dall-e-3") is True
        assert _is_openai_model("DALL-E-3") is True
        assert _is_openai_model("gemini/gemini-2.5-flash-image") is False

    def test_gemini_models(self):
        assert _is_gemini_model("gemini/gemini-2.5-flash-image") is True
        assert _is_gemini_model("imagen-3.0-generate-002") is True
        assert _is_gemini_model("dall-e-3") is False

    def test_empty_model(self):
        assert _is_openai_model("") is False
        assert _is_openai_model(None) is False
        assert _is_gemini_model("") is False
        assert _is_gemini_model(None) is False


# ---------------------------------------------------------------------------
# Provider-optimal kwargs
# ---------------------------------------------------------------------------

class TestKwargsGeneration:
    def test_openai_generate_kwargs(self):
        kw = _generate_kwargs("gpt-image-1", n=3)
        assert kw == {"n": 3, "response_format": "b64_json"}

    def test_gemini_generate_kwargs(self):
        kw = _generate_kwargs("gemini/gemini-2.5-flash-image", n=3)
        assert kw == {}  # Gemini rejects extra params

    def test_openai_edit_kwargs(self):
        kw = _edit_kwargs("dall-e-3", n=2)
        assert kw == {"n": 2}

    def test_gemini_edit_kwargs(self):
        kw = _edit_kwargs("gemini/gemini-2.5-flash-image", n=2)
        assert kw == {}


# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------

class TestResolveImageClient:
    """Test the _resolve_image_client resolution cascade."""

    @patch("app.services.providers.get_llm_client")
    @patch("app.tools.local.image.settings")
    def test_explicit_provider_id(self, mock_settings, mock_get_client):
        """Explicit provider_id takes priority over everything."""
        mock_settings.IMAGE_GENERATION_PROVIDER_ID = "config-provider"
        sentinel = MagicMock()
        mock_get_client.return_value = sentinel

        result = _resolve_image_client("explicit-provider")

        mock_get_client.assert_called_once_with("explicit-provider")
        assert result is sentinel

    @patch("app.services.providers.get_llm_client")
    @patch("app.tools.local.image.settings")
    def test_config_provider_id(self, mock_settings, mock_get_client):
        """Falls back to IMAGE_GENERATION_PROVIDER_ID config."""
        mock_settings.IMAGE_GENERATION_PROVIDER_ID = "config-provider"
        sentinel = MagicMock()
        mock_get_client.return_value = sentinel

        result = _resolve_image_client(None)

        mock_get_client.assert_called_once_with("config-provider")
        assert result is sentinel

    @patch("app.services.providers.get_llm_client")
    @patch("app.agent.bots.get_bot")
    @patch("app.agent.context.current_bot_id")
    @patch("app.tools.local.image.settings")
    def test_bot_provider_fallback(self, mock_settings, mock_ctx, mock_get_bot, mock_get_client):
        """Falls back to the current bot's model_provider_id."""
        mock_settings.IMAGE_GENERATION_PROVIDER_ID = ""
        sentinel = MagicMock()
        mock_get_client.return_value = sentinel

        mock_ctx.get.return_value = "my-bot"
        mock_bot = MagicMock()
        mock_bot.model_provider_id = "bot-provider"
        mock_get_bot.return_value = mock_bot

        result = _resolve_image_client(None)

        mock_get_client.assert_called_once_with("bot-provider")
        assert result is sentinel

    @patch("app.services.providers.get_llm_client")
    @patch("app.agent.context.current_bot_id")
    @patch("app.tools.local.image.settings")
    def test_env_fallback(self, mock_settings, mock_ctx, mock_get_client):
        """Falls back to None (env defaults) when nothing else is set."""
        mock_settings.IMAGE_GENERATION_PROVIDER_ID = ""
        sentinel = MagicMock()
        mock_get_client.return_value = sentinel
        mock_ctx.get.return_value = None  # No bot context

        result = _resolve_image_client(None)

        mock_get_client.assert_called_once_with(None)
        assert result is sentinel

    @patch("app.services.providers.get_llm_client")
    @patch("app.agent.bots.get_bot")
    @patch("app.agent.context.current_bot_id")
    @patch("app.tools.local.image.settings")
    def test_bot_without_provider(self, mock_settings, mock_ctx, mock_get_bot, mock_get_client):
        """Bot exists but has no model_provider_id — falls back to None."""
        mock_settings.IMAGE_GENERATION_PROVIDER_ID = ""
        sentinel = MagicMock()
        mock_get_client.return_value = sentinel

        mock_ctx.get.return_value = "my-bot"
        mock_bot = MagicMock()
        mock_bot.model_provider_id = None
        mock_get_bot.return_value = mock_bot

        result = _resolve_image_client(None)

        mock_get_client.assert_called_once_with(None)
        assert result is sentinel


# ---------------------------------------------------------------------------
# End-to-end tool call (mocked API)
# ---------------------------------------------------------------------------

class TestGenerateImageTool:
    @pytest.mark.asyncio
    async def test_model_override(self):
        """When model param is passed, it overrides the config default."""
        from app.tools.local.image import generate_image_tool

        mock_resp = MagicMock()
        mock_resp.data = []  # Empty = "No image returned" error, but we check model was used

        mock_client = AsyncMock()
        mock_client.images.generate = AsyncMock(return_value=mock_resp)

        with patch("app.tools.local.image._resolve_image_client", return_value=mock_client), \
             patch("app.tools.local.image.settings") as mock_settings:
            mock_settings.IMAGE_GENERATION_MODEL = "default-model"

            result = json.loads(await generate_image_tool(
                prompt="a cat",
                model="custom-model",
            ))

        # Verify the custom model was passed to the API
        mock_client.images.generate.assert_called_once()
        call_kwargs = mock_client.images.generate.call_args
        assert call_kwargs.kwargs["model"] == "custom-model"

    @pytest.mark.asyncio
    async def test_provider_id_passthrough(self):
        """When provider_id is passed, it reaches _resolve_image_client."""
        from app.tools.local.image import generate_image_tool

        mock_resp = MagicMock()
        mock_resp.data = []

        mock_client = AsyncMock()
        mock_client.images.generate = AsyncMock(return_value=mock_resp)

        with patch("app.tools.local.image._resolve_image_client", return_value=mock_client) as mock_resolve, \
             patch("app.tools.local.image.settings") as mock_settings:
            mock_settings.IMAGE_GENERATION_MODEL = "default-model"

            await generate_image_tool(
                prompt="a dog",
                provider_id="openai-prod",
            )

        mock_resolve.assert_called_once_with("openai-prod")

    @pytest.mark.asyncio
    async def test_default_model_from_settings(self):
        """When no model param, uses IMAGE_GENERATION_MODEL from settings."""
        from app.tools.local.image import generate_image_tool

        mock_resp = MagicMock()
        mock_resp.data = []

        mock_client = AsyncMock()
        mock_client.images.generate = AsyncMock(return_value=mock_resp)

        with patch("app.tools.local.image._resolve_image_client", return_value=mock_client), \
             patch("app.tools.local.image.settings") as mock_settings:
            mock_settings.IMAGE_GENERATION_MODEL = "gemini/gemini-2.5-flash-image"

            await generate_image_tool(prompt="a bird")

        call_kwargs = mock_client.images.generate.call_args
        assert call_kwargs.kwargs["model"] == "gemini/gemini-2.5-flash-image"

    @pytest.mark.asyncio
    async def test_empty_prompt_returns_error(self):
        """Empty prompt should return an error without calling the API."""
        from app.tools.local.image import generate_image_tool

        result = json.loads(await generate_image_tool(prompt=""))
        assert "error" in result
        assert "prompt is required" in result["error"]
