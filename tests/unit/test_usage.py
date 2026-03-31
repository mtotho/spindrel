"""Unit tests for usage cost helpers."""
import pytest

from app.routers.api_v1_admin.usage import (
    _parse_cost_str, _compute_cost, _lookup_pricing,
    _resolve_event_cost, _cache_discount_for_provider,
)


class TestParseCostStr:
    def test_dollar_prefix(self):
        assert _parse_cost_str("$3.00") == 3.0

    def test_no_prefix(self):
        assert _parse_cost_str("3.00") == 3.0

    def test_small_value(self):
        assert _parse_cost_str("$0.15") == 0.15

    def test_none(self):
        assert _parse_cost_str(None) is None

    def test_empty(self):
        assert _parse_cost_str("") is None

    def test_invalid(self):
        assert _parse_cost_str("abc") is None

    def test_whitespace(self):
        assert _parse_cost_str("  $2.50  ") == 2.5


class TestComputeCost:
    def test_basic_cost(self):
        # $3/1M input, $15/1M output
        cost = _compute_cost(1000, 500, "$3.00", "$15.00")
        assert cost is not None
        assert abs(cost - (1000 * 3 / 1_000_000 + 500 * 15 / 1_000_000)) < 1e-10

    def test_no_pricing(self):
        assert _compute_cost(1000, 500, None, None) is None

    def test_input_only(self):
        cost = _compute_cost(1000, 500, "$3.00", None)
        assert cost is not None
        assert abs(cost - 1000 * 3 / 1_000_000) < 1e-10

    def test_output_only(self):
        cost = _compute_cost(1000, 500, None, "$15.00")
        assert cost is not None
        assert abs(cost - 500 * 15 / 1_000_000) < 1e-10

    def test_zero_tokens(self):
        cost = _compute_cost(0, 0, "$3.00", "$15.00")
        assert cost == 0.0

    def test_large_token_count(self):
        cost = _compute_cost(1_000_000, 500_000, "$3.00", "$15.00")
        assert cost is not None
        assert abs(cost - (3.0 + 7.5)) < 1e-10


class TestLookupPricing:
    def test_exact_match(self):
        pricing = {("prov1", "gpt-4"): ("$30.00", "$60.00")}
        result = _lookup_pricing(pricing, "prov1", "gpt-4")
        assert result == ("$30.00", "$60.00")

    def test_fallback_no_provider(self):
        pricing = {("prov1", "gpt-4"): ("$30.00", "$60.00")}
        result = _lookup_pricing(pricing, None, "gpt-4")
        assert result == ("$30.00", "$60.00")

    def test_no_match(self):
        pricing = {("prov1", "gpt-4"): ("$30.00", "$60.00")}
        result = _lookup_pricing(pricing, "prov1", "claude-3")
        assert result == (None, None)

    def test_no_model(self):
        pricing = {("prov1", "gpt-4"): ("$30.00", "$60.00")}
        result = _lookup_pricing(pricing, "prov1", None)
        assert result == (None, None)

    def test_provider_mismatch_falls_back_to_model(self):
        pricing = {("prov1", "gpt-4"): ("$30.00", "$60.00")}
        result = _lookup_pricing(pricing, "prov2", "gpt-4")
        assert result == ("$30.00", "$60.00")

    def test_env_fallback_key(self):
        """No provider_id on event → should match __env__ sentinel from LiteLLM cache."""
        pricing = {("__env__", "gemini/gemini-2.5-flash"): ("$0.15", "$0.60")}
        result = _lookup_pricing(pricing, None, "gemini/gemini-2.5-flash")
        assert result == ("$0.15", "$0.60")

    def test_db_overrides_env(self):
        """DB row should win over __env__ LiteLLM cache entry."""
        pricing = {
            ("__env__", "gpt-4"): ("$10.00", "$30.00"),
            ("prov1", "gpt-4"): ("$5.00", "$15.00"),
        }
        result = _lookup_pricing(pricing, "prov1", "gpt-4")
        assert result == ("$5.00", "$15.00")


class TestComputeCostWithCache:
    """Tests for cached token discount in _compute_cost."""

    def test_no_cached_tokens_unchanged(self):
        """Without cached tokens, cost is the same as before."""
        cost = _compute_cost(10_000, 5_000, "$3.00", "$15.00")
        expected = 10_000 * 3 / 1_000_000 + 5_000 * 15 / 1_000_000
        assert abs(cost - expected) < 1e-10

    def test_cached_tokens_with_90_percent_discount(self):
        """Anthropic-style: 90% discount on cached tokens."""
        # 10k prompt tokens, 8k cached, 5k completion
        # uncached: 2k * $3/1M + cached: 8k * $3/1M * 0.1 + output: 5k * $15/1M
        cost = _compute_cost(10_000, 5_000, "$3.00", "$15.00",
                             cached_tokens=8_000, cache_discount=0.9)
        uncached_cost = 2_000 * 3 / 1_000_000
        cached_cost = 8_000 * 3 * 0.1 / 1_000_000
        output_cost = 5_000 * 15 / 1_000_000
        assert abs(cost - (uncached_cost + cached_cost + output_cost)) < 1e-10

    def test_cached_tokens_with_50_percent_discount(self):
        """OpenAI-style: 50% discount on cached tokens."""
        cost = _compute_cost(10_000, 5_000, "$3.00", "$15.00",
                             cached_tokens=8_000, cache_discount=0.5)
        uncached_cost = 2_000 * 3 / 1_000_000
        cached_cost = 8_000 * 3 * 0.5 / 1_000_000
        output_cost = 5_000 * 15 / 1_000_000
        assert abs(cost - (uncached_cost + cached_cost + output_cost)) < 1e-10

    def test_all_tokens_cached(self):
        """All prompt tokens cached — only pays discounted rate."""
        cost = _compute_cost(10_000, 0, "$3.00", None,
                             cached_tokens=10_000, cache_discount=0.9)
        expected = 10_000 * 3 * 0.1 / 1_000_000
        assert abs(cost - expected) < 1e-10

    def test_zero_discount_no_effect(self):
        """cache_discount=0.0 means no savings (same as no caching)."""
        cost_with = _compute_cost(10_000, 5_000, "$3.00", "$15.00",
                                  cached_tokens=8_000, cache_discount=0.0)
        cost_without = _compute_cost(10_000, 5_000, "$3.00", "$15.00")
        assert abs(cost_with - cost_without) < 1e-10


class TestResolveEventCost:
    """Tests for _resolve_event_cost — the unified cost resolution helper."""

    def test_prefers_response_cost(self):
        """When response_cost is present, use it directly."""
        d = {"response_cost": 0.042, "prompt_tokens": 10_000, "completion_tokens": 5_000,
             "model": "gpt-4", "provider_id": "prov1"}
        pricing = {("prov1", "gpt-4"): ("$30.00", "$60.00")}
        ptype_map = {"prov1": "openai"}
        cost = _resolve_event_cost(d, pricing, ptype_map)
        assert cost == 0.042

    def test_falls_back_to_computed_with_cache(self):
        """No response_cost → compute with cache discount."""
        d = {"prompt_tokens": 10_000, "completion_tokens": 5_000,
             "cached_tokens": 8_000, "model": "claude-3", "provider_id": "ant1"}
        pricing = {("ant1", "claude-3"): ("$3.00", "$15.00")}
        ptype_map = {"ant1": "anthropic"}
        cost = _resolve_event_cost(d, pricing, ptype_map)
        # Anthropic: 90% discount on cached tokens
        uncached_cost = 2_000 * 3 / 1_000_000
        cached_cost = 8_000 * 3 * 0.1 / 1_000_000
        output_cost = 5_000 * 15 / 1_000_000
        assert abs(cost - (uncached_cost + cached_cost + output_cost)) < 1e-10

    def test_no_cached_tokens_no_discount(self):
        """Without cached_tokens in event, no discount applied."""
        d = {"prompt_tokens": 10_000, "completion_tokens": 5_000,
             "model": "gpt-4", "provider_id": "prov1"}
        pricing = {("prov1", "gpt-4"): ("$3.00", "$15.00")}
        ptype_map = {"prov1": "openai"}
        cost = _resolve_event_cost(d, pricing, ptype_map)
        expected = 10_000 * 3 / 1_000_000 + 5_000 * 15 / 1_000_000
        assert abs(cost - expected) < 1e-10

    def test_unknown_provider_uses_default_discount(self):
        """Unknown provider type → default 50% cache discount."""
        d = {"prompt_tokens": 10_000, "completion_tokens": 0,
             "cached_tokens": 10_000, "model": "m1", "provider_id": "custom1"}
        pricing = {("custom1", "m1"): ("$10.00", None)}
        ptype_map = {"custom1": "custom-type"}
        cost = _resolve_event_cost(d, pricing, ptype_map)
        # Default 50% discount
        expected = 10_000 * 10 * 0.5 / 1_000_000
        assert abs(cost - expected) < 1e-10


class TestCacheDiscountForProvider:
    def test_anthropic(self):
        ptype_map = {"ant1": "anthropic"}
        assert _cache_discount_for_provider("ant1", ptype_map) == 0.9

    def test_openai(self):
        ptype_map = {"oai1": "openai"}
        assert _cache_discount_for_provider("oai1", ptype_map) == 0.5

    def test_litellm_default(self):
        ptype_map = {None: "litellm"}
        assert _cache_discount_for_provider(None, ptype_map) == 0.5

    def test_unknown_provider(self):
        ptype_map = {"x": "some-unknown"}
        assert _cache_discount_for_provider("x", ptype_map) == 0.5

    def test_missing_provider_falls_back_to_litellm(self):
        ptype_map = {}
        assert _cache_discount_for_provider("missing", ptype_map) == 0.5
