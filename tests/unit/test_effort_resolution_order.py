"""Tests the resolution order for the reasoning/effort knob:

  1. `current_effort_override` ContextVar (set by run_stream from channel.config)
  2. bot.model_params["effort"] / bot.model_params["thinking_budget"]

The ContextVar path is driven by `/effort` persisting to channel.config and
``run_stream`` reading it back at the top of the turn. These tests isolate
the merge logic that sits between those two stages: the ``translate_effort``
call in ``_prepare_call_params`` must see the effective, post-overlay value.
"""
from __future__ import annotations

import pytest

from app.agent.context import current_effort_override
from app.agent.model_params import filter_model_params, translate_effort


@pytest.fixture(autouse=True)
def _allow_reasoning(monkeypatch):
    """Phase 2 added a DB-flag reasoning gate inside ``filter_model_params``.
    These tests isolate ContextVar / bot_params overlay + translation — the
    DB gate has its own suite. Force the gate open so we don't need to seed
    provider_models for every case."""
    monkeypatch.setattr(
        "app.services.providers.supports_reasoning",
        lambda _m: True,
    )


class TestContextVarWinsOverBotParams:
    def test_contextvar_unset_uses_bot_default(self):
        """If no /effort was fired, bot's own model_params drive the request."""
        token = current_effort_override.set(None)
        try:
            bot_params = {"effort": "low"}
            # filter_model_params keeps the key for a reasoning-capable family
            filtered = filter_model_params("anthropic/claude-opus-4-7", bot_params)
            assert filtered.get("effort") == "low"
            kwargs = translate_effort("anthropic/claude-opus-4-7", filtered.get("effort"))
            assert kwargs["thinking_budget"] == 2048
        finally:
            current_effort_override.reset(token)

    def test_contextvar_override_beats_bot_default(self):
        """`/effort high` set on the channel promotes past the bot's low default.

        Mirrors what run_agent_tool_loop does at the top of the function:
        it overlays the ContextVar onto a copy of bot.model_params.
        """
        token = current_effort_override.set("high")
        try:
            bot_params = {"effort": "low"}
            effective = dict(bot_params)
            ctx_override = current_effort_override.get()
            if ctx_override:
                effective["effort"] = ctx_override
            filtered = filter_model_params("anthropic/claude-opus-4-7", effective)
            kwargs = translate_effort("anthropic/claude-opus-4-7", filtered.get("effort"))
            assert kwargs["thinking_budget"] == 16384, (
                "ContextVar override should produce high-level budget, "
                "got something else — the layers merged in the wrong order"
            )
        finally:
            current_effort_override.reset(token)

    def test_contextvar_off_clears_bot_default(self):
        """If the channel explicitly set /effort off, it should SUPPRESS the
        bot's configured default rather than silently falling through."""
        token = current_effort_override.set("off")
        try:
            bot_params = {"effort": "high"}
            effective = dict(bot_params)
            ctx_override = current_effort_override.get()
            if ctx_override:
                effective["effort"] = ctx_override
            kwargs = translate_effort("anthropic/claude-opus-4-7", effective.get("effort"))
            assert kwargs == {}
        finally:
            current_effort_override.reset(token)


class TestExplicitBudgetPreserved:
    def test_advanced_thinking_budget_still_honored_when_effort_from_contextvar(self):
        """Power users who set an explicit budget under the 'Advanced' disclosure
        keep that precision even when /effort fires on the channel."""
        token = current_effort_override.set("medium")
        try:
            bot_params = {"thinking_budget": 3500}
            effective = dict(bot_params)
            ctx_override = current_effort_override.get()
            if ctx_override:
                effective["effort"] = ctx_override
            # filter_model_params keeps both keys for anthropic family
            filtered = filter_model_params("anthropic/claude-opus-4-7", effective)
            kwargs = translate_effort(
                "anthropic/claude-opus-4-7",
                filtered.get("effort"),
                explicit_budget=filtered.get("thinking_budget"),
            )
            # Explicit budget should win over the enum default (8192 for medium)
            assert kwargs["thinking_budget"] == 3500
        finally:
            current_effort_override.reset(token)


class TestSnapshotRestore:
    def test_snapshot_carries_effort_override(self):
        """Delegated/nested runs must inherit the outer turn's effort."""
        from app.agent.context import snapshot_agent_context, restore_agent_context

        token = current_effort_override.set("high")
        try:
            snap = snapshot_agent_context()
            assert snap.effort_override == "high"

            # Clobber the ContextVar and restore — value must come back
            inner = current_effort_override.set("low")
            try:
                assert current_effort_override.get() == "low"
                restore_agent_context(snap)
                assert current_effort_override.get() == "high"
            finally:
                current_effort_override.reset(inner)
        finally:
            # The restore above already set the var back — but reset the outer
            # token to guarantee teardown returns to baseline (None).
            current_effort_override.reset(token)
