"""Tests for compression_prompt channel override in app.services.compression."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.compression import compress_context


def _bot(**cc_overrides) -> MagicMock:
    bot = MagicMock()
    bot.compression_config = cc_overrides or {}
    bot.model = "gemini/gemini-2.5-flash"
    bot.model_provider_id = None
    return bot


def _channel(**overrides) -> MagicMock:
    ch = MagicMock()
    ch.context_compression = overrides.get("context_compression", None)
    ch.compression_model = overrides.get("compression_model", None)
    ch.compression_threshold = overrides.get("compression_threshold", None)
    ch.compression_keep_turns = overrides.get("compression_keep_turns", None)
    ch.compression_prompt = overrides.get("compression_prompt", None)
    return ch


def _make_messages(user_turns: int = 10) -> list[dict]:
    msgs = [{"role": "system", "content": "You are a helpful bot."}]
    for i in range(user_turns):
        msgs.append({"role": "user", "content": f"User message {i} " + "x" * 200})
        msgs.append({"role": "assistant", "content": f"Response {i} " + "z" * 200})
    msgs.append({"role": "user", "content": "What was the first thing we discussed?"})
    return msgs


class TestCompressionPromptOverride:
    @pytest.mark.asyncio
    async def test_channel_compression_prompt_used(self):
        """When channel has compression_prompt set, it overrides the hardcoded default."""
        bot = _bot(enabled=True, threshold=100, keep_turns=1)
        custom_prompt = "My custom compression prompt. Summarize briefly."
        ch = _channel(compression_prompt=custom_prompt)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Custom summary."

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        # Mock channel lookup
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        fake_result = MagicMock()
        fake_result.scalar_one_or_none.return_value = ch
        mock_db.execute = AsyncMock(return_value=fake_result)

        with (
            patch("app.db.engine.async_session", return_value=mock_db),
            patch("app.services.providers.get_llm_client", return_value=mock_client),
        ):
            result = await compress_context(
                _make_messages(10), bot, "What was discussed?",
                channel_id="fake-channel-id",
            )

        assert result is not None
        # Verify the custom prompt was used in the LLM call
        call_args = mock_client.chat.completions.create.call_args
        system_msg = call_args.kwargs["messages"][0]["content"]
        assert system_msg == custom_prompt

    @pytest.mark.asyncio
    async def test_default_prompt_when_no_channel_override(self):
        """When channel has no compression_prompt, the hardcoded default is used."""
        bot = _bot(enabled=True, threshold=100, keep_turns=1)
        ch = _channel(compression_prompt=None)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Default summary."

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        fake_result = MagicMock()
        fake_result.scalar_one_or_none.return_value = ch
        mock_db.execute = AsyncMock(return_value=fake_result)

        with (
            patch("app.db.engine.async_session", return_value=mock_db),
            patch("app.services.providers.get_llm_client", return_value=mock_client),
        ):
            result = await compress_context(
                _make_messages(10), bot, "Question?",
                channel_id="fake-channel-id",
            )

        assert result is not None
        call_args = mock_client.chat.completions.create.call_args
        system_msg = call_args.kwargs["messages"][0]["content"]
        # Should contain the default prompt keywords
        assert "conversation summariser" in system_msg
        assert "[msg:N]" in system_msg
