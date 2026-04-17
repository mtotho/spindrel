"""Tests for app.services.widget_context."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.widget_context import build_widget_context_block


NOW = datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc)


def _pin(
    *,
    pid: str = "pin1",
    tool: str = "get_weather",
    display_name: str = "Weather",
    bot_id: str = "bot-a",
    label: str | None = "Seattle",
    plain: str = "52°F, cloudy, wind 8mph",
    pinned_at: str | None = None,
    config: dict | None = None,
) -> dict:
    return {
        "id": pid,
        "tool_name": tool,
        "display_name": display_name,
        "bot_id": bot_id,
        "envelope": {
            "display_label": label,
            "plain_body": plain,
        },
        "position": 0,
        "pinned_at": pinned_at or "2026-04-17T12:00:00+00:00",
        "config": config or {},
    }


# ---------------------------------------------------------------------------
# empty / degenerate
# ---------------------------------------------------------------------------

def test_none_returns_none() -> None:
    assert build_widget_context_block(None, bot_id="bot-a", now=NOW) is None


def test_empty_list_returns_none() -> None:
    assert build_widget_context_block([], bot_id="bot-a", now=NOW) is None


def test_pin_without_plain_body_skipped_returns_none() -> None:
    pin = _pin(plain="")
    assert build_widget_context_block([pin], bot_id="bot-a", now=NOW) is None


def test_non_dict_pin_is_ignored() -> None:
    result = build_widget_context_block(
        ["not-a-dict", _pin()],
        bot_id="bot-a",
        now=NOW,
    )
    assert result is not None
    assert "Seattle" in result


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------

def test_single_pin_renders_header_and_line() -> None:
    block = build_widget_context_block([_pin()], bot_id="bot-a", now=NOW)
    assert block is not None
    assert block.startswith(
        "The user has these widgets pinned in this channel"
    )
    assert "- Seattle: 52°F, cloudy, wind 8mph" in block


def test_label_falls_back_to_display_name_then_tool_name() -> None:
    p = _pin(label=None, display_name="", tool="my_tool")
    block = build_widget_context_block([p], bot_id="bot-a", now=NOW)
    assert block is not None
    assert "- my_tool:" in block


# ---------------------------------------------------------------------------
# truncation and caps
# ---------------------------------------------------------------------------

def test_long_plain_body_truncated_with_ellipsis() -> None:
    long_body = "x" * 500
    block = build_widget_context_block([_pin(plain=long_body)], bot_id="bot-a", now=NOW)
    assert block is not None
    # per-pin cap is 250; so the rendered 'x' run is at most 249 + '…'
    assert "…" in block
    xs = block.count("x")
    assert xs <= 250


def test_max_pins_cap() -> None:
    pins = [_pin(pid=f"p{i}", label=f"Loc{i}") for i in range(20)]
    block = build_widget_context_block(pins, bot_id="bot-a", now=NOW)
    assert block is not None
    # Only 12 pins should render
    assert block.count("\n- ") == 12
    # Specifically Loc0..Loc11 (first 12)
    assert "Loc0:" in block
    assert "Loc11:" in block
    assert "Loc12:" not in block


def test_global_char_cap_drops_trailing_pins() -> None:
    # Each pin ~ 240 chars * 12 = ~2880, exceeds 2000 ceiling
    chunky = "y" * 240
    pins = [_pin(pid=f"p{i}", label=f"L{i}", plain=chunky) for i in range(12)]
    block = build_widget_context_block(pins, bot_id="bot-a", now=NOW)
    assert block is not None
    assert len(block) <= 2000
    # Still rendered at least one pin
    assert "- L0:" in block
    # Trailing pins dropped
    assert "- L11:" not in block


# ---------------------------------------------------------------------------
# multi-bot attribution
# ---------------------------------------------------------------------------

def test_foreign_bot_pin_annotated() -> None:
    p = _pin(bot_id="bot-b")
    block = build_widget_context_block([p], bot_id="bot-a", now=NOW)
    assert block is not None
    assert "pinned by bot-b" in block


def test_own_pin_not_annotated() -> None:
    p = _pin(bot_id="bot-a")
    block = build_widget_context_block([p], bot_id="bot-a", now=NOW)
    assert block is not None
    assert "pinned by" not in block


# ---------------------------------------------------------------------------
# age suffix
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "delta, expected",
    [
        (timedelta(seconds=10), "just now"),
        (timedelta(minutes=35), "~35m ago"),
        (timedelta(hours=3), "~3h ago"),
        (timedelta(days=2, hours=5), "~2d ago"),
    ],
)
def test_age_suffix(delta: timedelta, expected: str) -> None:
    pinned_at = (NOW - delta).isoformat()
    block = build_widget_context_block([_pin(pinned_at=pinned_at)], bot_id="bot-a", now=NOW)
    assert block is not None
    assert f"updated {expected}" in block


def test_unparseable_pinned_at_omits_age() -> None:
    block = build_widget_context_block(
        [_pin(pinned_at="not-a-date")],
        bot_id="bot-a",
        now=NOW,
    )
    assert block is not None
    assert "updated" not in block


def test_future_pinned_at_omits_age() -> None:
    pinned_at = (NOW + timedelta(hours=1)).isoformat()
    block = build_widget_context_block([_pin(pinned_at=pinned_at)], bot_id="bot-a", now=NOW)
    assert block is not None
    assert "updated" not in block


def test_trailing_z_iso_parses() -> None:
    pinned_at = (NOW - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    block = build_widget_context_block([_pin(pinned_at=pinned_at)], bot_id="bot-a", now=NOW)
    assert block is not None
    assert "updated ~10m ago" in block


# ---------------------------------------------------------------------------
# combined attribution + age
# ---------------------------------------------------------------------------

def test_foreign_bot_and_age_both_in_suffix() -> None:
    pinned_at = (NOW - timedelta(minutes=15)).isoformat()
    p = _pin(bot_id="bot-b", pinned_at=pinned_at)
    block = build_widget_context_block([p], bot_id="bot-a", now=NOW)
    assert block is not None
    assert "(pinned by bot-b; updated ~15m ago)" in block
