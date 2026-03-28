"""Unit tests for usage cost helpers."""
import pytest

from app.routers.api_v1_admin.usage import _parse_cost_str, _compute_cost, _lookup_pricing


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
