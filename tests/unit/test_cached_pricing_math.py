"""Unit tests for the cached-input pricing path in `/admin/usage`.

Smoking gun: when ``cached_tokens > 0`` and the provider model carries an
explicit ``cached_input_cost_per_1m``, the cost split must use the explicit
rate (not the percent-discount fallback). This is the fix that stops the
``/admin/usage`` dashboard from overstating Anthropic spend ~10x while
prompt caching is active.
"""
from __future__ import annotations


def test_no_cached_tokens_uses_full_input_rate():
    from app.routers.api_v1_admin.usage import _compute_cost

    cost = _compute_cost(
        prompt_tokens=1_000_000,
        completion_tokens=0,
        input_rate_str="$3.00",
        output_rate_str="$15.00",
        cached_tokens=0,
    )
    assert cost == 3.00


def test_explicit_cached_rate_splits_cost():
    """1M prompt tokens, 800k cached.
    Without cache: 1M * $3.00/1M = $3.00.
    With cache + explicit $0.30 rate: 200k * $3.00 + 800k * $0.30 = $0.60 + $0.24 = $0.84.
    """
    from app.routers.api_v1_admin.usage import _compute_cost

    cost = _compute_cost(
        prompt_tokens=1_000_000,
        completion_tokens=0,
        input_rate_str="$3.00",
        output_rate_str="$15.00",
        cached_tokens=800_000,
        cached_input_rate_str="$0.30",
    )
    # 200k * 3.0/1M = 0.60; 800k * 0.30/1M = 0.24; total 0.84
    assert abs(cost - 0.84) < 1e-9


def test_falls_back_to_discount_when_no_explicit_rate():
    """When cached_input_rate_str is None but a cache_discount is supplied,
    fall back to the legacy percent-discount math (Anthropic 90%, OpenAI 50%)."""
    from app.routers.api_v1_admin.usage import _compute_cost

    cost = _compute_cost(
        prompt_tokens=1_000_000,
        completion_tokens=0,
        input_rate_str="$3.00",
        output_rate_str="$15.00",
        cached_tokens=800_000,
        cache_discount=0.9,  # 90% off
    )
    # 200k * 3.0/1M = 0.60; 800k * 3.0 * 0.10 / 1M = 0.24; total 0.84
    assert abs(cost - 0.84) < 1e-9


def test_explicit_rate_wins_over_discount():
    """If both a discount and an explicit rate are provided, the explicit rate
    is authoritative — the discount is ignored. This is what `_resolve_event_cost`
    arranges; this test pins the helper-level contract."""
    from app.routers.api_v1_admin.usage import _compute_cost

    cost_explicit = _compute_cost(
        prompt_tokens=1_000_000,
        completion_tokens=0,
        input_rate_str="$3.00",
        output_rate_str="$15.00",
        cached_tokens=800_000,
        cached_input_rate_str="$0.30",
        cache_discount=0.5,  # would otherwise discount to 50% of input
    )
    # Should use explicit cached_rate, NOT the discount.
    assert abs(cost_explicit - 0.84) < 1e-9


def test_uncached_floor_at_zero():
    """If cached_tokens > prompt_tokens (provider edge case), uncached bucket
    must clamp at zero rather than going negative and producing a credit."""
    from app.routers.api_v1_admin.usage import _compute_cost

    cost = _compute_cost(
        prompt_tokens=10,
        completion_tokens=0,
        input_rate_str="$3.00",
        output_rate_str="$15.00",
        cached_tokens=100,  # more than prompt_tokens
        cached_input_rate_str="$0.30",
    )
    # uncached clamped to 0, so cost = 100 * 0.30 / 1M = 0.00003
    assert cost is not None
    assert cost > 0
    assert abs(cost - (100 * 0.30 / 1_000_000)) < 1e-9


def test_completion_tokens_priced_separately():
    from app.routers.api_v1_admin.usage import _compute_cost

    cost = _compute_cost(
        prompt_tokens=0,
        completion_tokens=1_000_000,
        input_rate_str="$3.00",
        output_rate_str="$15.00",
        cached_tokens=0,
    )
    assert cost == 15.00


def test_no_pricing_returns_none():
    from app.routers.api_v1_admin.usage import _compute_cost

    cost = _compute_cost(
        prompt_tokens=100,
        completion_tokens=100,
        input_rate_str=None,
        output_rate_str=None,
    )
    assert cost is None
