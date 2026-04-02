"""Unit tests for the context budget module."""
import pytest
from unittest.mock import patch

from app.agent.context_budget import (
    ContextBudget,
    Priority,
    estimate_tokens,
    get_model_context_window,
    _normalize_model_name,
)


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_short_string(self):
        # "hello" = 5 chars → 5 / 3.5 ≈ 1.4 → 1
        assert estimate_tokens("hello") >= 1

    def test_known_length(self):
        # 350 chars → 350 / 3.5 = 100 tokens
        text = "x" * 350
        assert estimate_tokens(text) == 100

    def test_longer_text(self):
        text = "a" * 7000  # 7000 / 3.5 = 2000
        assert estimate_tokens(text) == 2000

    def test_conservative_estimate(self):
        """Token estimate should be conservative (overestimate rather than underestimate)."""
        # Real tokenizers typically give ~4 chars/token for English.
        # We use 3.5 chars/token which overestimates by ~12.5%.
        text = "The quick brown fox jumps over the lazy dog."
        tokens = estimate_tokens(text)
        # With real tokenizer this would be ~10 tokens, but our estimate should be higher
        assert tokens >= 10


class TestNormalizeModelName:
    def test_strips_provider_prefix(self):
        assert _normalize_model_name("openai/gpt-4o") == "gpt-4o"
        assert _normalize_model_name("gemini/gemini-2.5-flash") == "gemini-2.5-flash"
        assert _normalize_model_name("anthropic/claude-3-opus-20240229") == "claude-3-opus-20240229"

    def test_no_prefix(self):
        assert _normalize_model_name("gpt-4o") == "gpt-4o"
        assert _normalize_model_name("claude-3-opus-20240229") == "claude-3-opus-20240229"

    def test_multiple_slashes(self):
        # Only strip first prefix
        assert _normalize_model_name("openrouter/anthropic/claude-3-opus") == "anthropic/claude-3-opus"


class TestGetModelContextWindow:
    def test_known_model_direct(self):
        assert get_model_context_window("gpt-4o") == 128_000

    def test_known_model_with_prefix(self):
        assert get_model_context_window("openai/gpt-4o") == 128_000

    def test_gemini_model(self):
        assert get_model_context_window("gemini/gemini-2.5-flash") == 1_000_000

    def test_claude_model(self):
        assert get_model_context_window("claude-3-opus-20240229") == 200_000

    def test_unknown_model_returns_default(self):
        with patch("app.config.settings") as mock_settings:
            mock_settings.CONTEXT_BUDGET_DEFAULT_WINDOW = 128_000
            result = get_model_context_window("some-unknown-model-xyz")
            assert result == 128_000

    def test_provider_cache_hit(self):
        """When model info is in the provider cache, use its max_tokens."""
        with patch("app.services.providers._model_info_cache", {
            "provider-1": {"my-custom-model": {"max_tokens": 64_000}},
        }):
            result = get_model_context_window("my-custom-model", provider_id="provider-1")
            assert result == 64_000

    def test_alias_resolution(self):
        result = get_model_context_window("claude-opus-4")
        assert result == 200_000

    def test_prefix_match(self):
        """Models starting with a known key should match."""
        result = get_model_context_window("gpt-4o-2025-01-01")
        assert result == 128_000


class TestContextBudget:
    def test_initial_state(self):
        b = ContextBudget(total_tokens=128_000, reserve_tokens=19_200)
        assert b.consumed_tokens == 0
        assert b.remaining == 128_000 - 19_200
        assert b.utilization == 0.0
        assert b.breakdown == {}

    def test_consume(self):
        b = ContextBudget(total_tokens=100_000, reserve_tokens=15_000)
        b.consume("system_prompt", 5_000)
        assert b.consumed_tokens == 5_000
        assert b.breakdown == {"system_prompt": 5_000}
        assert b.remaining == 100_000 - 15_000 - 5_000

    def test_consume_cumulative(self):
        b = ContextBudget(total_tokens=100_000, reserve_tokens=15_000)
        b.consume("prompt", 3_000)
        b.consume("history", 7_000)
        assert b.consumed_tokens == 10_000
        assert b.breakdown["prompt"] == 3_000
        assert b.breakdown["history"] == 7_000

    def test_consume_same_category_adds_up(self):
        b = ContextBudget(total_tokens=100_000, reserve_tokens=0)
        b.consume("rag", 1_000)
        b.consume("rag", 2_000)
        assert b.breakdown["rag"] == 3_000

    def test_can_afford(self):
        b = ContextBudget(total_tokens=100_000, reserve_tokens=15_000)
        assert b.can_afford(50_000) is True
        assert b.can_afford(85_000) is True
        assert b.can_afford(85_001) is False

    def test_can_afford_after_consumption(self):
        b = ContextBudget(total_tokens=100_000, reserve_tokens=15_000)
        b.consume("stuff", 80_000)
        # remaining = 100_000 - 15_000 - 80_000 = 5_000
        assert b.can_afford(5_000) is True
        assert b.can_afford(5_001) is False

    def test_remaining_never_negative(self):
        b = ContextBudget(total_tokens=100_000, reserve_tokens=15_000)
        b.consume("overflow", 200_000)
        assert b.remaining == 0

    def test_utilization(self):
        b = ContextBudget(total_tokens=100_000, reserve_tokens=0)
        b.consume("stuff", 50_000)
        assert b.utilization == 0.5

    def test_utilization_over_100_percent(self):
        b = ContextBudget(total_tokens=100_000, reserve_tokens=0)
        b.consume("stuff", 120_000)
        assert b.utilization == 1.2

    def test_available_budget(self):
        b = ContextBudget(total_tokens=100_000, reserve_tokens=15_000)
        assert b.available_budget == 85_000

    def test_dynamic_top_k_plenty_of_budget(self):
        b = ContextBudget(total_tokens=100_000, reserve_tokens=0)
        # 100k remaining → 100_000 / 500 = 200 affordable chunks
        assert b.dynamic_top_k(10) == 10

    def test_dynamic_top_k_tight_budget(self):
        b = ContextBudget(total_tokens=100_000, reserve_tokens=0)
        b.consume("stuff", 99_000)
        # 1000 remaining → 1000 / 500 = 2 affordable chunks
        assert b.dynamic_top_k(10) == 2

    def test_dynamic_top_k_no_budget(self):
        b = ContextBudget(total_tokens=100_000, reserve_tokens=0)
        b.consume("stuff", 100_000)
        assert b.dynamic_top_k(10) == 0

    def test_to_dict(self):
        b = ContextBudget(total_tokens=100_000, reserve_tokens=15_000)
        b.consume("prompt", 5_000)
        d = b.to_dict()
        assert d["total_tokens"] == 100_000
        assert d["reserve_tokens"] == 15_000
        assert d["consumed_tokens"] == 5_000
        assert d["remaining_tokens"] == 80_000
        assert d["utilization"] == pytest.approx(5_000 / 85_000, abs=0.01)
        assert d["breakdown"] == {"prompt": 5_000}


class TestPriority:
    def test_ordering(self):
        assert Priority.P0_PROTECTED < Priority.P1_ESSENTIAL
        assert Priority.P1_ESSENTIAL < Priority.P2_IMPORTANT
        assert Priority.P2_IMPORTANT < Priority.P3_NICE_TO_HAVE
        assert Priority.P3_NICE_TO_HAVE < Priority.P4_EXPENDABLE
