"""Integration tests for the bot↔widget bridge + Todo reference widget.

Validates end-to-end:
- Widget handlers surface as bot-callable tools via `list_widget_handler_tools`.
- Tool names follow `widget.<slug>.<handler>` naming.
- Dispatching through `widget-actions` (the iframe path) and the dynamic
  tool-source resolver (the bot path) end up at the same SQLite state.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig
from tests.integration.conftest import AUTH_HEADERS


_CHANNEL_ID = uuid.UUID("eeee0000-0000-0000-0000-000000000101")
_BOT_ID = "todo-bridge-bot"

_BOT = BotConfig(
    id=_BOT_ID, name="Todo Bridge Bot", model="test/model",
    system_prompt="", memory=MemoryConfig(enabled=False),
)


def _envelope(channel_id: uuid.UUID) -> dict:
    return {
        "content_type": "application/vnd.spindrel.html+interactive",
        "body": "",
        "source_path": "widgets/todo/index.html",
        "source_channel_id": str(channel_id),
        "source_bot_id": _BOT_ID,
        "plain_body": "todo",
        "display": "inline",
    }


@pytest.fixture()
async def seeded(db_session, tmp_path, monkeypatch):
    from app.db.models import ApiKey, Bot

    api_key = ApiKey(
        id=uuid.uuid4(),
        name="bridge-key",
        key_hash="bridgehash",
        key_prefix="bridge-key-",
        scopes=["chat"],
        is_active=True,
    )
    db_session.add(api_key)
    await db_session.flush()

    db_session.add(Bot(
        id=_BOT_ID, name="Todo Bridge Bot", display_name="Todo Bridge Bot",
        model="test/model", system_prompt="", api_key_id=api_key.id,
    ))
    await db_session.flush()

    # Isolate workspace + widget_db root to tmp_path.
    from app.services import paths as paths_mod
    monkeypatch.setattr(
        paths_mod, "local_workspace_base", lambda: str(tmp_path),
    )

    widgets_parent = (
        Path(__file__).resolve().parents[2] / "app" / "tools" / "local"
    )
    assert (widgets_parent / "widgets" / "todo" / "widget.py").is_file()
    monkeypatch.setattr(
        "app.services.channel_workspace.get_channel_workspace_root",
        lambda channel_id, bot: str(widgets_parent),
    )
    return tmp_path


@pytest.fixture()
async def channel(db_session):
    from app.db.models import Channel
    ch = Channel(
        id=_CHANNEL_ID, name="todo-channel", bot_id=_BOT_ID,
        client_id="todo-client-a",
    )
    db_session.add(ch)
    await db_session.flush()
    return _CHANNEL_ID


def _bot_patch():
    return patch("app.agent.bots.get_bot", return_value=_BOT)


async def _create_pin(db_session, channel_id: uuid.UUID):
    from app.services.dashboard_pins import create_pin
    return await create_pin(
        db_session,
        source_kind="adhoc",
        tool_name="emit_html_widget",
        envelope=_envelope(channel_id),
        source_channel_id=channel_id,
        source_bot_id=_BOT_ID,
        display_label="Todo",
        dashboard_key=f"channel:{channel_id}",
    )


@pytest.mark.asyncio
async def test_handler_tools_surface_for_pinned_widget(
    seeded, db_session, channel,
):
    """A bot in the channel where the todo widget is pinned sees its handlers
    as ``widget.todo.*`` tools with proper schemas + safety tiers."""
    from app.services.widget_handler_tools import list_widget_handler_tools

    with _bot_patch():
        await _create_pin(db_session, channel)

    with _bot_patch():
        schemas, resolver = await list_widget_handler_tools(
            db_session, _BOT_ID, str(channel),
        )

    names = sorted(s["function"]["name"] for s in schemas)
    assert names == [
        "widget.todo.add_todo",
        "widget.todo.delete_todo",
        "widget.todo.list_todos",
        "widget.todo.toggle_done",
    ]
    add_schema = next(
        s for s in schemas if s["function"]["name"] == "widget.todo.add_todo"
    )
    assert add_schema["function"]["parameters"]["required"] == ["title"]

    _, _, list_tier = resolver["widget.todo.list_todos"]
    assert list_tier == "readonly"
    _, _, add_tier = resolver["widget.todo.add_todo"]
    assert add_tier == "mutating"


@pytest.mark.asyncio
async def test_iframe_and_bot_paths_see_same_state(
    client, seeded, db_session, channel,
):
    """A todo added through the iframe path (/widget-actions dispatch=widget_handler)
    is visible when the bot-bridge invokes `list_todos` via the resolver path.
    Proves both dispatch routes terminate at the same SQLite state."""
    from app.services.widget_handler_tools import resolve_widget_handler
    from app.services.widget_py import invoke_action

    with _bot_patch():
        pin = await _create_pin(db_session, channel)

    # --- iframe path: add via /widget-actions ---
    with _bot_patch():
        resp = await client.post(
            "/api/v1/widget-actions",
            json={
                "dispatch": "widget_handler",
                "dashboard_pin_id": str(pin.id),
                "handler": "add_todo",
                "args": {"title": "Buy cheese"},
            },
            headers=AUTH_HEADERS,
        )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # --- bot path: resolve tool name → invoke_action ---
    with _bot_patch():
        resolved = await resolve_widget_handler(
            db_session, "widget.todo.list_todos", _BOT_ID, str(channel),
        )
    assert resolved is not None
    resolved_pin, handler, _tier = resolved
    assert resolved_pin.id == pin.id
    assert handler == "list_todos"

    with _bot_patch():
        rows = await invoke_action(resolved_pin, handler, {})
    titles = [r["title"] for r in rows]
    assert "Buy cheese" in titles


@pytest.mark.asyncio
async def test_cross_bot_widget_handler_triggers_approval_gate(
    seeded, db_session, channel,
):
    """Widget handler tool names flow through the standard approval gate.

    The widget-handler bridge was flagged as a potential trust-boundary
    break: bot A's turn invoking a handler on bot B's pinned widget runs
    the handler under bot B's identity. The design answer is that the
    pin bot is the ceiling AND the standard tool-policy approval gate
    still fires per the configured rule set.

    This test pins the approval-gate half of that contract:
    ``evaluate_tool_policy`` receives a ``widget.todo.add_todo`` tool name
    from a caller bot that does NOT own the pin, and an explicit
    ``ToolPolicyRule`` with a ``widget.todo.*`` glob turns the call into
    ``require_approval`` — the same decision shape any other mutating
    tool would produce. No special-case bypass, no silent allow.
    """
    from app.db.models import ToolPolicyRule
    from app.services.tool_policies import evaluate_tool_policy

    with _bot_patch():
        await _create_pin(db_session, channel)

    # Global rule — bot_id is NULL so it applies to any caller bot.
    rule = ToolPolicyRule(
        bot_id=None,
        tool_name="widget.todo.*",
        action="require_approval",
        priority=50,
        reason="Mutating Todo widget handlers require approval",
        enabled=True,
    )
    db_session.add(rule)
    await db_session.commit()

    # Caller bot_id is intentionally different from the pin owner (_BOT_ID)
    # so this doubles as a cross-bot invocation.
    caller_bot_id = "some-other-bot"
    decision = await evaluate_tool_policy(
        db_session, caller_bot_id, "widget.todo.add_todo",
        {"title": "pay bills"},
    )
    assert decision.action == "require_approval"
    assert decision.rule_id == str(rule.id)

    # Readonly handlers on the same widget also route through the gate —
    # the glob catches them — and the same policy choice applies.
    decision_ro = await evaluate_tool_policy(
        db_session, caller_bot_id, "widget.todo.list_todos", {},
    )
    assert decision_ro.action == "require_approval"
    assert decision_ro.rule_id == str(rule.id)


@pytest.mark.asyncio
async def test_bot_path_mutation_visible_in_iframe_path(
    client, seeded, db_session, channel,
):
    """A todo added via the bot path is visible through a /widget-actions query —
    the reverse direction of the prior test."""
    from app.services.widget_handler_tools import resolve_widget_handler
    from app.services.widget_py import invoke_action

    with _bot_patch():
        pin = await _create_pin(db_session, channel)

    with _bot_patch():
        resolved = await resolve_widget_handler(
            db_session, "widget.todo.add_todo", _BOT_ID, str(channel),
        )
    assert resolved is not None
    resolved_pin, handler, _ = resolved

    with _bot_patch():
        result = await invoke_action(resolved_pin, handler, {"title": "Take out trash"})
    assert result["title"] == "Take out trash"

    # Query via iframe path.
    with _bot_patch():
        qry = await client.post(
            "/api/v1/widget-actions",
            json={
                "dispatch": "db_query",
                "dashboard_pin_id": str(pin.id),
                "sql": "SELECT title, done FROM todos WHERE title = ?",
                "params": ["Take out trash"],
            },
            headers=AUTH_HEADERS,
        )
    body = qry.json()
    assert body["ok"] is True, body
    rows = body["db_result"]["rows"]
    assert len(rows) == 1
    assert rows[0]["done"] == 0
