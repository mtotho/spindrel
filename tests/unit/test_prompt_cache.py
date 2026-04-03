"""Tests for app.agent.prompt_cache."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.agent.prompt_cache import (
    _CHARS_PER_TOKEN,
    _MAX_BREAKPOINTS,
    apply_cache_breakpoints,
    should_apply_cache_control,
)


# ---------------------------------------------------------------------------
# should_apply_cache_control
# ---------------------------------------------------------------------------

class TestShouldApplyCacheControl:
    def test_disabled(self):
        with patch("app.agent.prompt_cache.settings") as mock_settings:
            mock_settings.PROMPT_CACHE_ENABLED = False
            assert should_apply_cache_control("claude-3-5-sonnet-20241022") is False

    def test_claude_model_name(self):
        with patch("app.agent.prompt_cache.settings") as mock_settings:
            mock_settings.PROMPT_CACHE_ENABLED = True
            assert should_apply_cache_control("claude-3-5-sonnet-20241022") is True
            assert should_apply_cache_control("anthropic/claude-3-haiku") is True
            assert should_apply_cache_control("Claude-3-Opus") is True

    def test_non_claude_model(self):
        with patch("app.agent.prompt_cache.settings") as mock_settings:
            mock_settings.PROMPT_CACHE_ENABLED = True
            assert should_apply_cache_control("gpt-4o") is False
            assert should_apply_cache_control("gemini/gemini-2.5-flash") is False

    def test_litellm_claude_prefix(self):
        with patch("app.agent.prompt_cache.settings") as mock_settings:
            mock_settings.PROMPT_CACHE_ENABLED = True
            # LiteLLM may prefix with provider
            assert should_apply_cache_control("bedrock/claude-3-sonnet") is True

    def test_anthropic_provider_type(self):
        mock_provider = MagicMock()
        mock_provider.provider_type = "anthropic"

        with patch("app.agent.prompt_cache.settings") as mock_settings:
            mock_settings.PROMPT_CACHE_ENABLED = True
            with patch("app.services.providers._registry", {"my-provider": mock_provider}):
                assert should_apply_cache_control("my-custom-model", provider_id="my-provider") is True

    def test_anthropic_compatible_provider_type(self):
        mock_provider = MagicMock()
        mock_provider.provider_type = "anthropic-compatible"

        with patch("app.agent.prompt_cache.settings") as mock_settings:
            mock_settings.PROMPT_CACHE_ENABLED = True
            with patch("app.services.providers._registry", {"my-provider": mock_provider}):
                assert should_apply_cache_control("my-custom-model", provider_id="my-provider") is True

    def test_provider_lookup_error_graceful(self):
        with patch("app.agent.prompt_cache.settings") as mock_settings:
            mock_settings.PROMPT_CACHE_ENABLED = True
            # Non-claude model + provider lookup raises
            with patch("app.services.providers._registry", side_effect=Exception("boom")):
                assert should_apply_cache_control("my-model", provider_id="bad-provider") is False


# ---------------------------------------------------------------------------
# apply_cache_breakpoints
# ---------------------------------------------------------------------------

class TestApplyCacheBreakpoints:
    def _long_system(self, text: str = "x") -> str:
        """Return text long enough to exceed min token threshold."""
        return text * (1024 * _CHARS_PER_TOKEN + 1)

    def test_empty_messages(self):
        result = apply_cache_breakpoints([])
        assert result == []

    def test_no_system_messages(self):
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        with patch("app.agent.prompt_cache.settings") as mock_settings:
            mock_settings.PROMPT_CACHE_MIN_TOKENS = 1024
            result = apply_cache_breakpoints(messages)
        assert result == messages

    def test_short_system_messages_skipped(self):
        messages = [
            {"role": "system", "content": "Short prompt"},
            {"role": "user", "content": "hello"},
        ]
        with patch("app.agent.prompt_cache.settings") as mock_settings:
            mock_settings.PROMPT_CACHE_MIN_TOKENS = 1024
            result = apply_cache_breakpoints(messages)
        # No changes — message too short
        assert result[0]["content"] == "Short prompt"

    def test_single_long_system_message(self):
        long_text = self._long_system()
        messages = [
            {"role": "system", "content": long_text},
            {"role": "user", "content": "hello"},
        ]
        with patch("app.agent.prompt_cache.settings") as mock_settings:
            mock_settings.PROMPT_CACHE_MIN_TOKENS = 1024
            result = apply_cache_breakpoints(messages)

        # Should convert to content-block format
        assert isinstance(result[0]["content"], list)
        assert result[0]["content"][0]["type"] == "text"
        assert result[0]["content"][0]["text"] == long_text
        assert result[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
        # User message unchanged
        assert result[1] == messages[1]

    def test_multiple_system_messages(self):
        long_text = self._long_system()
        messages = [
            {"role": "system", "content": long_text},       # 0: first sys
            {"role": "system", "content": long_text + "2"},  # 1: second sys
            {"role": "system", "content": long_text + "3"},  # 2: third sys
            {"role": "user", "content": "hello"},
        ]
        with patch("app.agent.prompt_cache.settings") as mock_settings:
            mock_settings.PROMPT_CACHE_MIN_TOKENS = 1024
            result = apply_cache_breakpoints(messages)

        # First and last system messages should have cache_control
        assert isinstance(result[0]["content"], list)
        assert isinstance(result[2]["content"], list)

    def test_original_messages_not_mutated(self):
        long_text = self._long_system()
        messages = [
            {"role": "system", "content": long_text},
            {"role": "user", "content": "hello"},
        ]
        original_content = messages[0]["content"]
        with patch("app.agent.prompt_cache.settings") as mock_settings:
            mock_settings.PROMPT_CACHE_MIN_TOKENS = 1024
            result = apply_cache_breakpoints(messages)

        # Original list unchanged
        assert messages[0]["content"] == original_content
        assert isinstance(messages[0]["content"], str)

    def test_max_breakpoints(self):
        long_text = self._long_system()
        # Create more system messages than max breakpoints
        messages = [{"role": "system", "content": long_text + str(i)} for i in range(8)]
        messages.append({"role": "user", "content": "hello"})

        with patch("app.agent.prompt_cache.settings") as mock_settings:
            mock_settings.PROMPT_CACHE_MIN_TOKENS = 1024
            result = apply_cache_breakpoints(messages)

        # Count how many got cache_control
        cached = sum(
            1 for msg in result
            if msg.get("role") == "system"
            and isinstance(msg.get("content"), list)
        )
        assert cached <= _MAX_BREAKPOINTS

    def test_non_string_content_ignored(self):
        """System messages with non-string content (already content blocks) are skipped."""
        messages = [
            {"role": "system", "content": [{"type": "text", "text": "already blocks"}]},
            {"role": "user", "content": "hello"},
        ]
        with patch("app.agent.prompt_cache.settings") as mock_settings:
            mock_settings.PROMPT_CACHE_MIN_TOKENS = 1024
            result = apply_cache_breakpoints(messages)
        # Unchanged
        assert result[0]["content"] == [{"type": "text", "text": "already blocks"}]
