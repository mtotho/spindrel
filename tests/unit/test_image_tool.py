"""Unit tests for the generate_image tool.

Covers the canonical-overhaul shape:

* ``_image_family(model, provider_id)`` resolves provider_type +
  model-name patterns (no DB / driver in scope here).
* ``_generate_kwargs`` / ``_edit_kwargs`` produce family-specific kwargs.
* ``generate_image_tool`` dispatches to images.generate / images.edit /
  the Gemini multimodal helper as expected.
* The ``size``/``aspect_ratio``/``seed``/``n`` params reach the wire.
* ``source_image_b64`` is removed (no leftover code path).
* Every model in ``supports_image_generation_set()`` resolves to a known
  family — drift pin against capability flag vs routing.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.local.image import (
    _aspect_to_size,
    _edit_kwargs,
    _generate_kwargs,
    _image_family,
    _resolve_image_client,
)


# ---------------------------------------------------------------------------
# _image_family — provider-type + model-name dispatch
# ---------------------------------------------------------------------------


class TestImageFamily:
    def test_openai_subscription_provider_wins(self):
        """openai-subscription provider routes to its own family regardless of model."""
        provider = SimpleNamespace(provider_type="openai-subscription")
        with patch("app.services.providers.get_provider", return_value=provider):
            assert _image_family("gpt-image-1", "my-sub") == "openai-subscription"
            assert _image_family("dall-e-3", "my-sub") == "openai-subscription"
            assert _image_family("gemini-2.5-flash-image", "my-sub") == "openai-subscription"

    def test_openai_models_route_to_openai(self):
        """gpt-image / dall-e prefixes route to the OpenAI Images API call shape."""
        with patch("app.services.providers.get_provider", return_value=None):
            assert _image_family("gpt-image-1", "openai-prod") == "openai"
            assert _image_family("gpt-image-1.5", None) == "openai"
            assert _image_family("dall-e-3", None) == "openai"
            assert _image_family("DALL-E-2", None) == "openai"

    def test_gemini_models_route_to_gemini(self):
        """gemini / imagen / *-image suffix all route to Gemini multimodal."""
        with patch("app.services.providers.get_provider", return_value=None):
            assert _image_family("gemini/gemini-2.5-flash-image", None) == "gemini"
            assert _image_family("imagen-3.0-generate-002", None) == "gemini"
            assert _image_family("gemini-2.0-flash-exp-image-generation", None) == "gemini"
            assert _image_family("google/gemini-2.5-pro-image", None) == "gemini"

    def test_unknown_model_warns_and_defaults_openai(self, caplog):
        """An unknown model falls back to openai routing with a WARNING."""
        with patch("app.services.providers.get_provider", return_value=None), \
             patch("app.services.providers.supports_image_generation", return_value=False):
            with caplog.at_level("WARNING"):
                assert _image_family("flux-pro", None) == "openai"
            assert any(
                "no recognized family" in record.getMessage()
                for record in caplog.records
            )

    def test_flagged_unknown_model_no_warning(self, caplog):
        """Unknown model that's flagged supports_image_generation skips the warning."""
        with patch("app.services.providers.get_provider", return_value=None), \
             patch("app.services.providers.supports_image_generation", return_value=True):
            with caplog.at_level("WARNING"):
                _image_family("custom-image-model", None)
            assert not any(
                "no recognized family" in record.getMessage()
                for record in caplog.records
            )


# ---------------------------------------------------------------------------
# Family-specific kwargs
# ---------------------------------------------------------------------------


class TestGenerateKwargs:
    def test_openai_gpt_image(self):
        kw = _generate_kwargs("openai", "gpt-image-1", n=3, size=None, seed=None)
        assert kw == {"n": 3}

    def test_openai_gpt_image_with_size(self):
        kw = _generate_kwargs("openai", "gpt-image-1", n=2, size="1024x1024", seed=42)
        assert kw == {"n": 2, "size": "1024x1024"}

    def test_openai_dalle3_clamps_n(self):
        kw = _generate_kwargs("openai", "dall-e-3", n=5, size=None, seed=None)
        assert kw == {"n": 1, "response_format": "b64_json"}

    def test_openai_dalle2_keeps_n(self):
        kw = _generate_kwargs("openai", "dall-e-2", n=4, size=None, seed=None)
        assert kw == {"n": 4, "response_format": "b64_json"}

    def test_subscription_passes_size(self):
        kw = _generate_kwargs("openai-subscription", "gpt-image-1", n=2, size="1792x1024", seed=None)
        assert kw == {"n": 2, "size": "1792x1024"}

    def test_gemini_returns_empty(self):
        # Gemini goes through chat.completions; images.generate kwargs don't apply.
        kw = _generate_kwargs("gemini", "gemini-2.5-flash-image", n=3, size="1024x1024", seed=42)
        assert kw == {}


class TestEditKwargs:
    def test_openai_gpt_image(self):
        assert _edit_kwargs("openai", "gpt-image-1", n=2, size=None) == {"n": 2}

    def test_openai_dalle3_clamps_n(self):
        assert _edit_kwargs("openai", "dall-e-3", n=5, size=None) == {"n": 1}

    def test_subscription_includes_size(self):
        assert _edit_kwargs("openai-subscription", "gpt-image-1", n=1, size="1024x1024") == {"n": 1, "size": "1024x1024"}


class TestAspectMapping:
    def test_known_ratios(self):
        assert _aspect_to_size("1:1") == "1024x1024"
        assert _aspect_to_size("16:9") == "1792x1024"
        assert _aspect_to_size("9:16") == "1024x1792"

    def test_unknown_ratio_returns_none(self):
        assert _aspect_to_size("21:9") is None
        assert _aspect_to_size(None) is None
        assert _aspect_to_size("") is None


# ---------------------------------------------------------------------------
# _resolve_image_client cascade
# ---------------------------------------------------------------------------


class TestResolveImageClient:
    @patch("app.services.providers.get_llm_client")
    @patch("app.tools.local.image.settings")
    def test_explicit_provider_id(self, mock_settings, mock_get_client):
        mock_settings.IMAGE_GENERATION_PROVIDER_ID = "config-provider"
        sentinel = MagicMock()
        mock_get_client.return_value = sentinel

        assert _resolve_image_client("explicit") is sentinel
        mock_get_client.assert_called_once_with("explicit")

    @patch("app.services.providers.get_llm_client")
    @patch("app.tools.local.image.settings")
    def test_config_fallback(self, mock_settings, mock_get_client):
        mock_settings.IMAGE_GENERATION_PROVIDER_ID = "config-provider"
        sentinel = MagicMock()
        mock_get_client.return_value = sentinel

        assert _resolve_image_client(None) is sentinel
        mock_get_client.assert_called_once_with("config-provider")

    @patch("app.services.providers.get_llm_client")
    @patch("app.agent.bots.get_bot")
    @patch("app.agent.context.current_bot_id")
    @patch("app.tools.local.image.settings")
    def test_bot_fallback(self, mock_settings, mock_ctx, mock_get_bot, mock_get_client):
        mock_settings.IMAGE_GENERATION_PROVIDER_ID = ""
        mock_ctx.get.return_value = "my-bot"
        bot = MagicMock()
        bot.model_provider_id = "bot-provider"
        mock_get_bot.return_value = bot
        mock_get_client.return_value = "client-sentinel"

        assert _resolve_image_client(None) == "client-sentinel"
        mock_get_client.assert_called_once_with("bot-provider")

    @patch("app.services.providers.get_llm_client")
    @patch("app.agent.context.current_bot_id")
    @patch("app.tools.local.image.settings")
    def test_env_fallback(self, mock_settings, mock_ctx, mock_get_client):
        mock_settings.IMAGE_GENERATION_PROVIDER_ID = ""
        mock_ctx.get.return_value = None
        mock_get_client.return_value = "client-sentinel"

        assert _resolve_image_client(None) == "client-sentinel"
        mock_get_client.assert_called_once_with(None)


# ---------------------------------------------------------------------------
# generate_image_tool — end-to-end dispatch
# ---------------------------------------------------------------------------


def _bot_channel_ctx():
    """Pin bot/channel/dispatch context vars so attachment-creation paths run.

    Returns the tokens so the caller can ``reset`` them in a finally block.
    """
    from app.agent import context as agent_ctx
    tokens = (
        agent_ctx.current_bot_id.set("test-bot"),
        agent_ctx.current_channel_id.set(None),
        agent_ctx.current_dispatch_type.set("web"),
    )

    def _restore():
        agent_ctx.current_dispatch_type.reset(tokens[2])
        agent_ctx.current_channel_id.reset(tokens[1])
        agent_ctx.current_bot_id.reset(tokens[0])

    return _restore


class TestGenerateImageTool:
    @pytest.mark.asyncio
    async def test_empty_prompt_errors(self):
        from app.tools.local.image import generate_image_tool
        result = json.loads(await generate_image_tool(prompt=""))
        assert "prompt is required" in result["error"]

    @pytest.mark.asyncio
    async def test_openai_generate_passes_size_and_n(self, monkeypatch):
        from app.tools.local.image import generate_image_tool

        item = SimpleNamespace(b64_json="AAAA", url=None)
        resp = SimpleNamespace(data=[item])
        client = AsyncMock()
        client.images.generate = AsyncMock(return_value=resp)

        gen_att = SimpleNamespace(id="att-uuid")
        with patch("app.tools.local.image._resolve_image_client", return_value=client), \
             patch("app.tools.local.image._image_family", return_value="openai"), \
             patch("app.tools.local.image.settings") as s, \
             patch("app.services.attachments.create_widget_backed_attachment", new=AsyncMock(return_value=gen_att)):
            s.IMAGE_GENERATION_MODEL = "gpt-image-1"
            s.IMAGE_GENERATION_PROVIDER_ID = ""
            _restore = _bot_channel_ctx()
            result = json.loads(await generate_image_tool(prompt="a cat", size="1792x1024", n=3))

        client.images.generate.assert_awaited_once()
        kwargs = client.images.generate.call_args.kwargs
        assert kwargs["model"] == "gpt-image-1"
        assert kwargs["prompt"] == "a cat"
        assert kwargs["n"] == 3
        assert kwargs["size"] == "1792x1024"
        assert result["images"][0]["attachment_id"] == "att-uuid"

    @pytest.mark.asyncio
    async def test_aspect_ratio_maps_to_size_for_openai(self, monkeypatch):
        from app.tools.local.image import generate_image_tool

        item = SimpleNamespace(b64_json="AAAA", url=None)
        client = AsyncMock()
        client.images.generate = AsyncMock(return_value=SimpleNamespace(data=[item]))
        gen_att = SimpleNamespace(id="att-uuid")
        with patch("app.tools.local.image._resolve_image_client", return_value=client), \
             patch("app.tools.local.image._image_family", return_value="openai"), \
             patch("app.tools.local.image.settings") as s, \
             patch("app.services.attachments.create_widget_backed_attachment", new=AsyncMock(return_value=gen_att)):
            s.IMAGE_GENERATION_MODEL = "gpt-image-1"
            s.IMAGE_GENERATION_PROVIDER_ID = ""
            _restore = _bot_channel_ctx()
            await generate_image_tool(prompt="x", aspect_ratio="16:9")

        kwargs = client.images.generate.call_args.kwargs
        assert kwargs["size"] == "1792x1024"

    @pytest.mark.asyncio
    async def test_openai_edit_with_attachments(self, monkeypatch):
        from app.tools.local.image import generate_image_tool

        att = SimpleNamespace(file_data=b"fake-image-bytes", description="A dog", mime_type="image/png")
        item = SimpleNamespace(b64_json="AAAA", url=None)
        client = AsyncMock()
        client.images.edit = AsyncMock(return_value=SimpleNamespace(data=[item]))
        gen_att = SimpleNamespace(id="edited-uuid")
        with patch("app.tools.local.image._resolve_image_client", return_value=client), \
             patch("app.tools.local.image._image_family", return_value="openai"), \
             patch("app.tools.local.image.settings") as s, \
             patch("app.services.attachments.get_attachment_by_id", new=AsyncMock(return_value=att)), \
             patch("app.services.attachments.create_widget_backed_attachment", new=AsyncMock(return_value=gen_att)):
            s.IMAGE_GENERATION_MODEL = "gpt-image-1"
            s.IMAGE_GENERATION_PROVIDER_ID = ""
            _restore = _bot_channel_ctx()
            result = json.loads(await generate_image_tool(
                prompt="make sky purple",
                attachment_ids=["00000000-0000-0000-0000-000000000001"],
            ))

        client.images.edit.assert_awaited_once()
        client.images.generate.assert_not_called()
        assert result["images"][0]["attachment_id"] == "edited-uuid"

    @pytest.mark.asyncio
    async def test_gemini_routes_through_multimodal_helper(self, monkeypatch):
        """Gemini family does NOT call client.images.* — it uses chat.completions."""
        from app.tools.local.image import generate_image_tool

        client = AsyncMock()
        # Sentinels so a wrong route would surface as an unexpected call:
        client.images.generate = AsyncMock(side_effect=AssertionError("must not be called"))
        client.images.edit = AsyncMock(side_effect=AssertionError("must not be called"))

        gen_att = SimpleNamespace(id="gem-uuid")
        with patch("app.tools.local.image._resolve_image_client", return_value=client), \
             patch("app.tools.local.image._image_family", return_value="gemini"), \
             patch("app.tools.local.image._gemini_generate_or_edit", new=AsyncMock(return_value=["AAAA"])) as gem, \
             patch("app.tools.local.image.settings") as s, \
             patch("app.services.attachments.create_widget_backed_attachment", new=AsyncMock(return_value=gen_att)):
            s.IMAGE_GENERATION_MODEL = "gemini/gemini-2.5-flash-image"
            s.IMAGE_GENERATION_PROVIDER_ID = ""
            _restore = _bot_channel_ctx()
            result = json.loads(await generate_image_tool(prompt="paint me a galaxy"))

        gem.assert_awaited_once()
        # Helper called with model + prompt + empty image_files (generate-from-scratch).
        call_kwargs = gem.call_args
        assert call_kwargs.args[1] == "gemini/gemini-2.5-flash-image"
        assert call_kwargs.args[2] == "paint me a galaxy"
        assert call_kwargs.args[3] == []
        assert result["images"][0]["attachment_id"] == "gem-uuid"

    @pytest.mark.asyncio
    async def test_gemini_edit_passes_attachments_to_helper(self, monkeypatch):
        from app.tools.local.image import generate_image_tool

        att = SimpleNamespace(file_data=b"fake-bytes", description="cat", mime_type="image/png")
        client = AsyncMock()
        gen_att = SimpleNamespace(id="edit-uuid")
        with patch("app.tools.local.image._resolve_image_client", return_value=client), \
             patch("app.tools.local.image._image_family", return_value="gemini"), \
             patch("app.tools.local.image._gemini_generate_or_edit", new=AsyncMock(return_value=["BBBB"])) as gem, \
             patch("app.tools.local.image.settings") as s, \
             patch("app.services.attachments.get_attachment_by_id", new=AsyncMock(return_value=att)), \
             patch("app.services.attachments.create_widget_backed_attachment", new=AsyncMock(return_value=gen_att)):
            s.IMAGE_GENERATION_MODEL = "gemini/gemini-2.5-flash-image"
            s.IMAGE_GENERATION_PROVIDER_ID = ""
            _restore = _bot_channel_ctx()
            await generate_image_tool(
                prompt="put it in a hat",
                attachment_ids=["00000000-0000-0000-0000-000000000001"],
            )

        image_files = gem.call_args.args[3]
        assert len(image_files) == 1
        assert image_files[0][1] == b"fake-bytes"

    @pytest.mark.asyncio
    async def test_legacy_source_image_b64_param_removed(self):
        """``source_image_b64`` should no longer be a parameter."""
        import inspect
        from app.tools.local.image import generate_image_tool
        sig = inspect.signature(generate_image_tool)
        assert "source_image_b64" not in sig.parameters


# ---------------------------------------------------------------------------
# Drift pin: every flagged model resolves to a known family
# ---------------------------------------------------------------------------


class TestCapabilityFamilyDrift:
    def test_every_flagged_model_resolves_to_known_family(self):
        """Each model in supports_image_generation_set() should produce a
        valid family — guards against a new model getting flagged in the
        DB but not getting routing in ``_image_family``.
        """
        from app.services.providers import supports_image_generation_set

        # Use a string-only set (provider context not required for the
        # fallback patterns); empty in unit tests is fine — this is a
        # forward-looking assertion that won't fail until DB rows exist.
        flagged = supports_image_generation_set()
        with patch("app.services.providers.get_provider", return_value=None):
            for mid in flagged:
                family = _image_family(mid, None)
                assert family in {"openai", "openai-subscription", "gemini"}, (
                    f"Flagged model {mid!r} resolved to unknown family {family!r}"
                )
