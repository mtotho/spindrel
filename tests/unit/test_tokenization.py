"""Unit tests for the unified token counter.

Verifies the provider cascade (anthropic → tiktoken → chars/3.5) and the
content-hash + TTL cache.
"""
from __future__ import annotations

import asyncio

import pytest

from app.agent import tokenization


@pytest.fixture(autouse=True)
def _reset_cache():
    tokenization._cache_clear()
    yield
    tokenization._cache_clear()


# ---------------------------------------------------------------------------
# Sync helper — tiktoken when available, chars/3.5 floor otherwise
# ---------------------------------------------------------------------------


class TestSyncCounter:
    def test_empty_string_is_zero(self):
        assert tokenization.count_text_tokens_sync("", "gpt-4o") == 0

    def test_tiktoken_route_for_openai_models(self):
        # tiktoken is in the dep set; verify we get a real count, not chars/3.5
        text = "the quick brown fox jumps over the lazy dog"
        n = tokenization.count_text_tokens_sync(text, "gpt-4o-mini")
        # tiktoken cl100k/o200k should give 9 tokens for this phrase; chars/3.5 = 12
        assert 8 <= n <= 11, f"expected real tiktoken count, got {n}"

    def test_unknown_model_falls_back_to_o200k(self):
        # Anthropic models aren't in tiktoken's registry — should fall back
        # to o200k_base, NOT chars/3.5.
        text = "x" * 100
        n = tokenization.count_text_tokens_sync(text, "claude-opus-4-6")
        chars_3_5 = int(100 / 3.5)
        # tiktoken on a string of identical chars compresses heavily
        assert n != chars_3_5, "should not have hit chars/3.5 fallback"


# ---------------------------------------------------------------------------
# Async counter — provider routing
# ---------------------------------------------------------------------------


class TestProviderRouting:
    async def test_openai_kind_uses_tiktoken(self, monkeypatch):
        # No anthropic client should be touched.
        called = {"anthropic": False}

        async def boom(*a, **kw):
            called["anthropic"] = True
            return type("R", (), {"input_tokens": 999})()

        monkeypatch.setattr(tokenization, "_count_anthropic", boom)

        n = await tokenization.count_text_tokens(
            "hello world", model="gpt-4o-mini", provider_type="openai"
        )
        assert called["anthropic"] is False
        # tiktoken: 2 tokens for "hello world" + 3-token per-message overhead
        assert 4 <= n <= 6

    async def test_anthropic_kind_calls_count_tokens(self, monkeypatch):
        seen = {}

        async def fake(*, model, messages, system, tools):
            seen["model"] = model
            seen["messages"] = messages
            return 42

        monkeypatch.setattr(tokenization, "_count_anthropic", fake)

        n = await tokenization.count_text_tokens(
            "hi", model="claude-opus-4-6", provider_type="anthropic"
        )
        assert n == 42
        assert seen["model"] == "claude-opus-4-6"
        assert seen["messages"][0]["content"] == "hi"

    async def test_unknown_provider_warns_once_and_falls_back(self, monkeypatch, caplog):
        # Force tiktoken to be unavailable so we exercise the chars fallback.
        monkeypatch.setattr(tokenization, "_tiktoken_encoding", lambda *_: None)

        with caplog.at_level("WARNING"):
            n1 = await tokenization.count_text_tokens(
                "x" * 35, model="weird-model", provider_type="weird-provider"
            )
            n2 = await tokenization.count_text_tokens(
                "x" * 35, model="weird-model", provider_type="weird-provider"
            )

        assert n1 == 10  # 35 / 3.5
        assert n2 == 10
        # Warning should fire exactly once thanks to the dedupe set.
        warns = [r for r in caplog.records if "chars/3.5 fallback" in r.message]
        assert len(warns) == 1


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


class TestCache:
    async def test_repeat_call_hits_cache(self, monkeypatch):
        calls = {"n": 0}

        async def fake(*, model, messages, system, tools):
            calls["n"] += 1
            return 7

        monkeypatch.setattr(tokenization, "_count_anthropic", fake)

        a = await tokenization.count_text_tokens(
            "same text", model="claude-opus-4-6", provider_type="anthropic"
        )
        b = await tokenization.count_text_tokens(
            "same text", model="claude-opus-4-6", provider_type="anthropic"
        )
        assert a == b == 7
        assert calls["n"] == 1, "second call should have come from cache"

    async def test_different_text_misses_cache(self, monkeypatch):
        calls = {"n": 0}

        async def fake(*, model, messages, system, tools):
            calls["n"] += 1
            return 7

        monkeypatch.setattr(tokenization, "_count_anthropic", fake)

        await tokenization.count_text_tokens(
            "first", model="claude-opus-4-6", provider_type="anthropic"
        )
        await tokenization.count_text_tokens(
            "second", model="claude-opus-4-6", provider_type="anthropic"
        )
        assert calls["n"] == 2


# ---------------------------------------------------------------------------
# Compat shim
# ---------------------------------------------------------------------------


class TestEstimateCompat:
    def test_estimate_tokens_matches_chars_over_3_5(self):
        assert tokenization.estimate_tokens("") == 0
        assert tokenization.estimate_tokens("x" * 35) == 10

    def test_context_budget_re_export(self):
        # context_budget.py re-exports estimate_tokens — keep the import alive.
        from app.agent.context_budget import estimate_tokens
        assert estimate_tokens("x" * 35) == 10
