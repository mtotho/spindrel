"""Tests for ``translate_effort`` — the single source of truth for reasoning
knob translation across provider families.

If this test goes silent after a code change, the translator is being
bypassed somewhere and the effort knob will silently drop on the wire (this
is exactly the regression that Phase 1 of the Provider Refactor fixed).
"""
from __future__ import annotations

import pytest

from app.agent.model_params import EFFORT_LEVELS, translate_effort


class TestAnthropicFamily:
    def test_high_effort_maps_to_thinking_budget_kwarg(self):
        kwargs = translate_effort("anthropic/claude-opus-4-7", "high")
        assert kwargs == {"thinking_budget": 16384}

    def test_medium_effort_scales_down(self):
        kwargs = translate_effort("anthropic/claude-sonnet-4-6", "medium")
        assert kwargs["thinking_budget"] == 8192

    def test_low_effort_scales_down_further(self):
        kwargs = translate_effort("anthropic/claude-haiku-4-5-20251001", "low")
        assert kwargs["thinking_budget"] == 2048

    def test_explicit_budget_wins_over_enum_default(self):
        """Power users who set an explicit thinking_budget keep their precision."""
        kwargs = translate_effort("anthropic/claude-opus-4-7", "medium", explicit_budget=6000)
        assert kwargs["thinking_budget"] == 6000

    def test_explicit_zero_budget_is_ignored(self):
        """A zero override shouldn't disable reasoning when the user set effort=high."""
        kwargs = translate_effort("anthropic/claude-opus-4-7", "high", explicit_budget=0)
        assert kwargs["thinking_budget"] == 16384


class TestGeminiFamily:
    def test_low_effort_emits_extra_body_thinking_config(self):
        kwargs = translate_effort("gemini/gemini-2.5-pro", "low")
        assert "extra_body" in kwargs
        cfg = kwargs["extra_body"]["thinking_config"]
        assert cfg["thinking_budget"] == 2048
        assert cfg["include_thoughts"] is True

    def test_google_family_alias(self):
        # Both `gemini/...` and `google/...` prefixes resolve to the same budget path.
        gemini_kwargs = translate_effort("gemini/gemini-2.5-flash", "medium")
        google_kwargs = translate_effort("google/gemini-2.5-pro", "medium")
        assert gemini_kwargs["extra_body"]["thinking_config"]["thinking_budget"] == 8192
        assert google_kwargs["extra_body"]["thinking_config"]["thinking_budget"] == 8192


class TestOpenAIFamily:
    def test_codex_maps_to_reasoning_effort_string(self):
        """Codex / gpt-5 uses reasoning_effort; the adapter translates it to
        body.reasoning.effort on the wire. See
        test_openai_responses_reasoning_effort for the adapter-level assertion.
        """
        kwargs = translate_effort("gpt-5-codex", "high")
        assert kwargs == {"reasoning_effort": "high"}

    def test_bare_gpt_model_defaults_to_openai_family(self):
        kwargs = translate_effort("gpt-4o", "medium")
        assert kwargs == {"reasoning_effort": "medium"}

    def test_xai_family_also_uses_reasoning_effort(self):
        kwargs = translate_effort("xai/grok-4", "low")
        assert kwargs == {"reasoning_effort": "low"}

    def test_deepseek_family_also_uses_reasoning_effort(self):
        kwargs = translate_effort("deepseek/deepseek-reasoner", "high")
        assert kwargs == {"reasoning_effort": "high"}


class TestOffAndUnsupported:
    def test_off_returns_empty_dict(self):
        """OFF must be an explicit empty dict, not None — callers merge into filtered params."""
        assert translate_effort("anthropic/claude-opus-4-7", "off") == {}
        assert translate_effort("gpt-5-codex", "off") == {}
        assert translate_effort("gemini/gemini-2.5-pro", "off") == {}

    def test_none_returns_empty_dict(self):
        assert translate_effort("anthropic/claude-opus-4-7", None) == {}

    def test_unknown_effort_level_returns_empty_dict(self):
        assert translate_effort("anthropic/claude-opus-4-7", "turbo") == {}

    def test_unsupported_family_returns_empty_dict(self):
        """Mistral / Groq / Ollama don't support effort — translator must NOT emit junk."""
        assert translate_effort("mistral/mistral-large", "high") == {}
        assert translate_effort("groq/llama-3-70b", "high") == {}
        assert translate_effort("ollama/llama3.2", "high") == {}


class TestEnumValidity:
    def test_effort_levels_canonical_order(self):
        """Regression pin: the enum order is the user-facing menu order."""
        assert EFFORT_LEVELS == ("off", "low", "medium", "high")
