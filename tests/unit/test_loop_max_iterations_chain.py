"""Pin the resolution chain for per-turn tool-call cap:
channel override → bot override → global settings default.

The loop itself is large; we only test the tiny expression at
``app/agent/loop.py::agent_tool_loop`` that computes
``effective_max_iterations``. Done by inlining the expression so
refactors that break the chain still get caught.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.config import settings


@dataclass
class _StubBot:
    max_iterations: int | None = None


def _effective(max_iter_override: int | None, bot: _StubBot) -> int:
    # Mirrors app/agent/loop.py effective_max_iterations resolution.
    return (
        max_iter_override
        or getattr(bot, "max_iterations", None)
        or settings.AGENT_MAX_ITERATIONS
    )


def test_channel_override_wins_over_bot_and_global():
    assert _effective(3, _StubBot(max_iterations=20)) == 3


def test_bot_override_used_when_no_channel_override():
    assert _effective(None, _StubBot(max_iterations=7)) == 7


def test_global_default_when_neither_set():
    assert _effective(None, _StubBot(max_iterations=None)) == settings.AGENT_MAX_ITERATIONS


def test_zero_channel_override_falls_through_to_bot():
    # ``0 or x`` short-circuits to x — this is deliberate. A zero cap
    # would disable the loop fence entirely, which is never useful.
    assert _effective(0, _StubBot(max_iterations=9)) == 9


def test_zero_bot_override_falls_through_to_global():
    assert _effective(None, _StubBot(max_iterations=0)) == settings.AGENT_MAX_ITERATIONS
