"""Integration tests for widget_handler dispatch — Phase B.2 Widget SDK.

End-to-end via POST /api/v1/widget-actions with dispatch:"widget_handler".
Uses a real widget.py written into a tmp bundle dir; mocks bot resolution
and the channel workspace root so path resolution lands in tmp_path.
"""
from __future__ import annotations

import textwrap
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig
from app.services.widget_py import clear_module_cache
from tests.integration.conftest import AUTH_HEADERS

_CHANNEL_ID = uuid.UUID("cccc0000-0000-0000-0000-000000000077")

_BOT = BotConfig(
    id="test-bot",
    name="Test Bot",
    model="test/model",
    system_prompt="",
    memory=MemoryConfig(enabled=False),
)

_ENVELOPE = {
    "content_type": "application/vnd.spindrel.html+interactive",
    "body": "",
    "source_path": "data/widgets/handler_test/index.html",
    "source_channel_id": str(_CHANNEL_ID),
    "source_bot_id": "test-bot",
    "plain_body": "handler widget",
    "display": "inline",
}


@pytest.fixture(autouse=True)
def _clear_module_cache():
    clear_module_cache()
    yield
    clear_module_cache()


@pytest.fixture()
async def handler_pin(db_session, tmp_path):
    """Seed a pin + write a widget.py into tmp_path/workspace/data/widgets/handler_test/."""
    from app.db.models import ApiKey, Bot
    from app.services.dashboard_pins import create_pin

    api_key = ApiKey(
        id=uuid.uuid4(),
        name="handler-key",
        key_hash="handlerhash",
        key_prefix="handler-key-",
        scopes=["chat"],
        is_active=True,
    )
    db_session.add(api_key)
    await db_session.flush()

    bot_row = Bot(
        id="test-bot",
        name="Test Bot",
        display_name="Test Bot",
        model="test/model",
        system_prompt="",
        api_key_id=api_key.id,
    )
    db_session.add(bot_row)
    await db_session.flush()

    pin = await create_pin(
        db_session,
        source_kind="adhoc",
        tool_name="emit_html_widget",
        envelope=_ENVELOPE,
        source_channel_id=_CHANNEL_ID,
        source_bot_id="test-bot",
        display_label="Handler widget",
    )

    ws_root = tmp_path / "workspace"
    bundle_dir = ws_root / "data" / "widgets" / "handler_test"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "index.html").write_text("<!-- test -->")

    return pin, ws_root, bundle_dir


def _ws_patch(ws_root: Path):
    return patch(
        "app.services.channel_workspace.get_channel_workspace_root",
        return_value=str(ws_root),
    )


def _bot_patch():
    return patch("app.agent.bots.get_bot", return_value=_BOT)


def _write_widget_py(bundle_dir: Path, body: str) -> None:
    (bundle_dir / "widget.py").write_text(textwrap.dedent(body).lstrip())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_dispatch_roundtrip(client, handler_pin):
    pin, ws_root, bundle_dir = handler_pin
    _write_widget_py(bundle_dir, """
        from spindrel.widget import on_action

        @on_action("echo")
        async def echo(args):
            return {"echoed": args.get("msg", "")}
    """)

    with _bot_patch(), _ws_patch(ws_root):
        resp = await client.post(
            "/api/v1/widget-actions",
            json={
                "dispatch": "widget_handler",
                "dashboard_pin_id": str(pin.id),
                "handler": "echo",
                "args": {"msg": "hello"},
            },
            headers=AUTH_HEADERS,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["result"] == {"echoed": "hello"}


@pytest.mark.asyncio
async def test_handler_missing_handler_returns_error(client, handler_pin):
    pin, ws_root, bundle_dir = handler_pin
    _write_widget_py(bundle_dir, """
        from spindrel.widget import on_action

        @on_action("save")
        def save(args): return {"ok": True}
    """)

    with _bot_patch(), _ws_patch(ws_root):
        resp = await client.post(
            "/api/v1/widget-actions",
            json={
                "dispatch": "widget_handler",
                "dashboard_pin_id": str(pin.id),
                "handler": "does_not_exist",
                "args": {},
            },
            headers=AUTH_HEADERS,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "does_not_exist" in data["error"]


@pytest.mark.asyncio
async def test_handler_missing_pin_id_returns_error(client, handler_pin):
    resp = await client.post(
        "/api/v1/widget-actions",
        json={
            "dispatch": "widget_handler",
            "handler": "echo",
            "args": {},
        },
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "dashboard_pin_id" in data["error"]


@pytest.mark.asyncio
async def test_handler_missing_handler_field_returns_error(client, handler_pin):
    pin, _, _ = handler_pin
    resp = await client.post(
        "/api/v1/widget-actions",
        json={
            "dispatch": "widget_handler",
            "dashboard_pin_id": str(pin.id),
            "args": {},
        },
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "handler" in data["error"]


@pytest.mark.asyncio
async def test_handler_missing_widget_py_returns_error(client, handler_pin):
    """Pin with no widget.py in its bundle surfaces a FileNotFoundError."""
    pin, ws_root, _ = handler_pin
    # Don't write widget.py.

    with _bot_patch(), _ws_patch(ws_root):
        resp = await client.post(
            "/api/v1/widget-actions",
            json={
                "dispatch": "widget_handler",
                "dashboard_pin_id": str(pin.id),
                "handler": "anything",
                "args": {},
            },
            headers=AUTH_HEADERS,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "widget.py" in data["error"]


@pytest.mark.asyncio
async def test_handler_propagates_permission_error(client, handler_pin):
    """Manifest allowlist refuses undeclared tool — handler raises PermissionError."""
    pin, ws_root, bundle_dir = handler_pin
    (bundle_dir / "widget.yaml").write_text(textwrap.dedent("""
        name: Scoped
        version: 1.0.0
        permissions:
          tools: [fetch_url]
    """).strip())
    _write_widget_py(bundle_dir, """
        from spindrel.widget import on_action, ctx

        @on_action("call_forbidden")
        async def call_forbidden(args):
            return await ctx.tool("send_push_notification", title="x", body="y")
    """)

    with _bot_patch(), _ws_patch(ws_root):
        resp = await client.post(
            "/api/v1/widget-actions",
            json={
                "dispatch": "widget_handler",
                "dashboard_pin_id": str(pin.id),
                "handler": "call_forbidden",
                "args": {},
            },
            headers=AUTH_HEADERS,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "does not declare tool" in data["error"]
