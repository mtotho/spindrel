"""Tests for app.services.widget_context."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.widget_context import (
    build_pinned_widget_context_snapshot,
    build_widget_context_block,
    enrich_pins_for_context_export,
    is_pinned_widget_context_enabled,
)


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


def test_channel_config_gate_defaults_on() -> None:
    assert is_pinned_widget_context_enabled(None) is True
    assert is_pinned_widget_context_enabled({}) is True
    assert is_pinned_widget_context_enabled({"pinned_widget_context_enabled": True}) is True
    assert is_pinned_widget_context_enabled({"pinned_widget_context_enabled": False}) is False


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


@pytest.mark.asyncio
async def test_snapshot_records_exported_rows_and_skips() -> None:
    snapshot = await build_pinned_widget_context_snapshot(
        None,  # type: ignore[arg-type]
        [
            _pin(
                pid="todo",
                context_export={"enabled": True, "summary_kind": "native_state", "hint_kind": "invoke_widget_action"},
                actions=[{"id": "add_item"}],
                state={"items": [{"title": "Buy milk", "done": False}]},
            ),
            _pin(
                pid="hidden",
                display_label="Hidden",
                context_export=None,
            ),
        ],
        bot_id="bot-a",
        now=NOW,
        channel_id="123",
    )
    assert snapshot["enabled"] is True
    assert snapshot["total_pins"] == 2
    assert snapshot["exported_count"] == 1
    assert snapshot["rows"][0]["label"] == "Todo"
    assert snapshot["rows"][0]["summary"] == "1 open, 0 done; next: Buy milk"
    assert snapshot["rows"][0]["hint"] is not None
    assert snapshot["skipped"] == [
        {"pin_id": "hidden", "label": "Hidden", "reason": "export_disabled"},
    ]
    assert "Todo: 1 open, 0 done; next: Buy milk" in snapshot["block_text"]


@pytest.mark.asyncio
async def test_snapshot_reports_disabled_channel_state() -> None:
    snapshot = await build_pinned_widget_context_snapshot(
        None,  # type: ignore[arg-type]
        [
            _pin(
                pid="todo",
                context_export={"enabled": True, "summary_kind": "plain_body", "hint_kind": "none"},
            ),
        ],
        bot_id="bot-a",
        now=NOW,
        enabled=False,
        disabled_reason="channel_disabled",
    )
    assert snapshot["enabled"] is False
    assert snapshot["exported_count"] == 0
    assert snapshot["block_text"] is None
    assert snapshot["skipped"] == [
        {"pin_id": "todo", "label": "Todo", "reason": "channel_disabled"},
    ]


@pytest.mark.asyncio
async def test_snapshot_marks_trimmed_rows() -> None:
    chunky = "y" * 240
    snapshot = await build_pinned_widget_context_snapshot(
        None,  # type: ignore[arg-type]
        [
            _pin(
                pid=f"p{i}",
                display_label=f"L{i}",
                plain=chunky,
                context_export={"enabled": True, "summary_kind": "plain_body", "hint_kind": "none"},
            )
            for i in range(12)
        ],
        bot_id="bot-a",
        now=NOW,
    )
    assert snapshot["enabled"] is True
    assert snapshot["truncated"] is True
    assert snapshot["exported_count"] < snapshot["total_pins"]
    assert any(item["reason"] == "trimmed" for item in snapshot["skipped"])
    assert snapshot["total_chars"] <= 2000


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
