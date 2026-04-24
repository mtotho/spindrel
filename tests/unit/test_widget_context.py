"""Tests for app.services.widget_context."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.widget_context import build_widget_context_block, enrich_pins_for_context_export


NOW = datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc)


def _pin(
    *,
    pid: str = "pin1",
    tool: str = "core/todo_native",
    display_label: str = "Todo",
    bot_id: str = "bot-a",
    widget_ref: str | None = None,
    plain: str = "52°F, cloudy, wind 8mph",
    pinned_at: str | None = None,
    context_export: dict | None = None,
    state: dict | None = None,
    actions: list[dict] | None = None,
    context_summary: str | None = None,
    context_hint: str | None = None,
) -> dict:
    widget_ref = widget_ref or tool
    pin = {
        "id": pid,
        "tool_name": tool,
        "display_label": display_label,
        "source_bot_id": bot_id,
        "bot_id": bot_id,
        "dashboard_key": "channel:123",
        "source_channel_id": "123",
        "envelope": {
            "display_label": display_label,
            "plain_body": plain,
            "body": {
                "widget_ref": widget_ref,
                "state": state or {},
            },
        },
        "widget_contract": {
            "context_export": context_export,
            "actions": actions or [],
        },
        "pinned_at": pinned_at or "2026-04-17T12:00:00+00:00",
    }
    if context_summary is not None:
        pin["context_summary"] = context_summary
    if context_hint is not None:
        pin["context_hint"] = context_hint
    return pin


def test_none_returns_none() -> None:
    assert build_widget_context_block(None, bot_id="bot-a", now=NOW) is None


def test_empty_list_returns_none() -> None:
    assert build_widget_context_block([], bot_id="bot-a", now=NOW) is None


def test_pin_without_context_export_is_skipped() -> None:
    pin = _pin(context_export=None)
    assert build_widget_context_block([pin], bot_id="bot-a", now=NOW) is None


def test_plain_body_export_renders_header_and_line() -> None:
    block = build_widget_context_block(
        [_pin(tool="weather", display_label="Seattle", context_export={
            "enabled": True,
            "summary_kind": "plain_body",
            "hint_kind": "none",
        })],
        bot_id="bot-a",
        now=NOW,
    )
    assert block is not None
    assert block.startswith("The user has these widgets pinned in this channel")
    assert "- Seattle: 52°F, cloudy, wind 8mph" in block


def test_context_hint_is_appended() -> None:
    block = build_widget_context_block(
        [_pin(
            display_label="Todo",
            context_export={"enabled": True, "summary_kind": "native_state", "hint_kind": "invoke_widget_action"},
            context_summary="2 open, 1 done",
            context_hint="Use invoke_widget_action(pin_id='pin1', action=...).",
        )],
        bot_id="bot-a",
        now=NOW,
    )
    assert block is not None
    assert "Hint: Use invoke_widget_action" in block


def test_foreign_bot_pin_annotated() -> None:
    p = _pin(
        bot_id="bot-b",
        context_export={"enabled": True, "summary_kind": "plain_body", "hint_kind": "none"},
    )
    block = build_widget_context_block([p], bot_id="bot-a", now=NOW)
    assert block is not None
    assert "pinned by bot-b" in block


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
    block = build_widget_context_block(
        [_pin(
            pinned_at=pinned_at,
            context_export={"enabled": True, "summary_kind": "plain_body", "hint_kind": "none"},
        )],
        bot_id="bot-a",
        now=NOW,
    )
    assert block is not None
    assert f"updated {expected}" in block


@pytest.mark.asyncio
async def test_enrich_native_todo_state_uses_live_state_and_hint() -> None:
    pins = await enrich_pins_for_context_export(
        None,  # type: ignore[arg-type]
        [_pin(
            context_export={"enabled": True, "summary_kind": "native_state", "hint_kind": "invoke_widget_action"},
            actions=[
                {"id": "add_item"},
                {"id": "toggle_item"},
                {"id": "delete_item"},
            ],
            state={
                "items": [
                    {"title": "Buy milk", "done": False},
                    {"title": "Email Sam", "done": False},
                    {"title": "Shipped", "done": True},
                ],
            },
        )],
        bot_id="bot-a",
        now=NOW,
    )
    assert pins[0]["context_summary"] == "2 open, 1 done; next: Buy milk, Email Sam"
    assert "invoke_widget_action" in pins[0]["context_hint"]
    assert "add_item" in pins[0]["context_hint"]


@pytest.mark.asyncio
async def test_enrich_native_notes_state_uses_snippet_and_age() -> None:
    pins = await enrich_pins_for_context_export(
        None,  # type: ignore[arg-type]
        [_pin(
            tool="core/notes_native",
            display_label="Notes",
            context_export={"enabled": True, "summary_kind": "native_state", "hint_kind": "invoke_widget_action"},
            state={
                "body": "First line\n\nSecond line",
                "updated_at": "2026-04-17T11:45:00+00:00",
            },
        )],
        bot_id="bot-a",
        now=NOW,
    )
    assert pins[0]["context_summary"] == "First line Second line (~15m ago)"


def test_global_char_cap_drops_trailing_pins() -> None:
    chunky = "y" * 240
    pins = [
        _pin(
            pid=f"p{i}",
            display_label=f"L{i}",
            plain=chunky,
            context_export={"enabled": True, "summary_kind": "plain_body", "hint_kind": "none"},
        )
        for i in range(12)
    ]
    block = build_widget_context_block(pins, bot_id="bot-a", now=NOW)
    assert block is not None
    assert len(block) <= 2000
    assert "- L0:" in block
    assert "- L11:" not in block
