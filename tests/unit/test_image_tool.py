"""Unit tests for the generate_image tool — provider resolution and parameter handling."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.local.image import (
    _generate_kwargs,
    _edit_kwargs,
    _is_dalle_model,
    _is_gemini_model,
    _is_gpt_image_model,
    _is_openai_model,
    _resolve_image_client,
    _supports_edit,
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

    def test_gpt_image_models(self):
        assert _is_gpt_image_model("gpt-image-1") is True
        assert _is_gpt_image_model("gpt-image-1.5") is True
        assert _is_gpt_image_model("dall-e-3") is False
        assert _is_gpt_image_model("gemini/gemini-2.5-flash-image") is False

    def test_dalle_models(self):
        assert _is_dalle_model("dall-e-3") is True
        assert _is_dalle_model("dall-e-2") is True
        assert _is_dalle_model("DALL-E-3") is True
        assert _is_dalle_model("gpt-image-1") is False

    def test_gemini_models(self):
        assert _is_gemini_model("gemini/gemini-2.5-flash-image") is True
        assert _is_gemini_model("imagen-3.0-generate-002") is True
        assert _is_gemini_model("dall-e-3") is False

    def test_empty_model(self):
        assert _is_openai_model("") is False
        assert _is_openai_model(None) is False
        assert _is_gemini_model("") is False
        assert _is_gemini_model(None) is False

    def test_supports_edit(self):
        assert _supports_edit("gpt-image-1") is True
        assert _supports_edit("dall-e-3") is True
        assert _supports_edit("gemini/gemini-2.5-flash-image") is False
        assert _supports_edit("imagen-3.0-generate-002") is False


# ---------------------------------------------------------------------------
# Provider-optimal kwargs
# ---------------------------------------------------------------------------

class TestKwargsGeneration:
    def test_gpt_image_generate_kwargs(self):
        """GPT Image family: n supported, no response_format (uses output_format)."""
        kw = _generate_kwargs("gpt-image-1", n=3)
        assert kw == {"n": 3}
        assert "response_format" not in kw

    def test_dalle3_generate_kwargs_clamps_n(self):
        """dall-e-3 only supports n=1."""
        kw = _generate_kwargs("dall-e-3", n=5)
        assert kw == {"n": 1, "response_format": "b64_json"}

    def test_dalle2_generate_kwargs_allows_n(self):
        """dall-e-2 supports n>1."""
        kw = _generate_kwargs("dall-e-2", n=4)
        assert kw == {"n": 4, "response_format": "b64_json"}

    def test_gemini_generate_kwargs(self):
        kw = _generate_kwargs("gemini/gemini-2.5-flash-image", n=3)
        assert kw == {}  # Gemini rejects extra params

    def test_unknown_model_generate_kwargs(self):
        """Unknown models get no extra params (safe default)."""
        kw = _generate_kwargs("flux-pro", n=2)
        assert kw == {}

    def test_gpt_image_edit_kwargs(self):
        kw = _edit_kwargs("gpt-image-1", n=3)
        assert kw == {"n": 3}

    def test_dalle3_edit_kwargs_clamps_n(self):
        kw = _edit_kwargs("dall-e-3", n=2)
        assert kw == {"n": 1}

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

    @pytest.mark.asyncio
    async def test_gemini_edit_falls_back_to_generate(self):
        """Gemini models should fall back to generation when attachment_ids are passed."""
        from app.tools.local.image import generate_image_tool

        mock_att = MagicMock()
        mock_att.file_data = b"fake-image"
        mock_att.description = "A black dog with a plaid collar"

        mock_resp = MagicMock()
        mock_resp.data = []  # triggers "No image returned" but we check generate was called

        mock_client = AsyncMock()
        mock_client.images.generate = AsyncMock(return_value=mock_resp)

        with patch("app.tools.local.image._resolve_image_client", return_value=mock_client), \
             patch("app.tools.local.image.settings") as mock_settings, \
             patch("app.services.attachments.get_attachment_by_id", new_callable=AsyncMock, return_value=mock_att):
            mock_settings.IMAGE_GENERATION_MODEL = "gemini/gemini-2.5-flash-image"

            await generate_image_tool(
                prompt="make the sky purple",
                attachment_ids=["00000000-0000-0000-0000-000000000001"],
            )

        # Should have called images.generate (not edit) with enriched prompt
        mock_client.images.generate.assert_called_once()
        call_kwargs = mock_client.images.generate.call_args.kwargs
        assert "black dog" in call_kwargs["prompt"]
        assert "make the sky purple" in call_kwargs["prompt"]

    @pytest.mark.asyncio
    async def test_gemini_fallback_without_descriptions(self):
        """Gemini fallback works even if attachments have no descriptions."""
        from app.tools.local.image import generate_image_tool

        mock_att = MagicMock()
        mock_att.file_data = b"fake-image"
        mock_att.description = None  # no description yet

        mock_resp = MagicMock()
        mock_resp.data = []

        mock_client = AsyncMock()
        mock_client.images.generate = AsyncMock(return_value=mock_resp)

        with patch("app.tools.local.image._resolve_image_client", return_value=mock_client), \
             patch("app.tools.local.image.settings") as mock_settings, \
             patch("app.services.attachments.get_attachment_by_id", new_callable=AsyncMock, return_value=mock_att):
            mock_settings.IMAGE_GENERATION_MODEL = "gemini/gemini-2.5-flash-image"

            await generate_image_tool(
                prompt="combine these images",
                attachment_ids=["00000000-0000-0000-0000-000000000001"],
            )

        # Should still call generate (not error), just with original prompt
        mock_client.images.generate.assert_called_once()
        call_kwargs = mock_client.images.generate.call_args.kwargs
        assert call_kwargs["prompt"] == "combine these images"

    @pytest.mark.asyncio
    async def test_gemini_fallback_success_message(self):
        """Successful Gemini fallback should include a note about the limitation."""
        from app.tools.local.image import generate_image_tool

        mock_att = MagicMock()
        mock_att.file_data = b"fake-image"
        mock_att.description = "A cute cat"

        mock_item = MagicMock()
        mock_item.b64_json = "AAAA"  # minimal base64
        mock_item.url = None
        mock_resp = MagicMock()
        mock_resp.data = [mock_item]

        mock_client = AsyncMock()
        mock_client.images.generate = AsyncMock(return_value=mock_resp)

        with patch("app.tools.local.image._resolve_image_client", return_value=mock_client), \
             patch("app.tools.local.image.settings") as mock_settings, \
             patch("app.services.attachments.get_attachment_by_id", new_callable=AsyncMock, return_value=mock_att), \
             patch("app.agent.context.current_bot_id") as mock_bot_id, \
             patch("app.agent.context.current_channel_id") as mock_chan_id, \
             patch("app.agent.context.current_dispatch_type") as mock_dispatch, \
             patch("app.services.attachments.create_attachment", new_callable=AsyncMock):
            mock_settings.IMAGE_GENERATION_MODEL = "gemini/gemini-2.5-flash-image"
            mock_bot_id.get.return_value = "test-bot"
            mock_chan_id.get.return_value = None
            mock_dispatch.get.return_value = "web"

            result = json.loads(await generate_image_tool(
                prompt="draw this cat in a hat",
                attachment_ids=["00000000-0000-0000-0000-000000000001"],
            ))

        assert "client_action" in result
        assert "doesn't support direct image editing" in result["message"]

    @pytest.mark.asyncio
    async def test_openai_edit_allowed(self):
        """OpenAI models should be allowed to use images.edit()."""
        from app.tools.local.image import generate_image_tool

        mock_att = MagicMock()
        mock_att.file_data = b"fake-image"
        mock_att.description = "A dog"

        mock_resp = MagicMock()
        mock_resp.data = []

        mock_client = AsyncMock()
        mock_client.images.edit = AsyncMock(return_value=mock_resp)

        with patch("app.tools.local.image._resolve_image_client", return_value=mock_client), \
             patch("app.tools.local.image.settings") as mock_settings, \
             patch("app.services.attachments.get_attachment_by_id", new_callable=AsyncMock, return_value=mock_att):
            mock_settings.IMAGE_GENERATION_MODEL = "gpt-image-1"

            result = json.loads(await generate_image_tool(
                prompt="make the sky purple",
                attachment_ids=["00000000-0000-0000-0000-000000000001"],
            ))

        # Should have called images.edit, not images.generate
        mock_client.images.edit.assert_called_once()
        assert "not supported" not in result.get("error", "")
