"""Integration tests for spindrel.db dispatch — Phase B.1 Widget SDK.

End-to-end via POST /api/v1/widget-actions with dispatch:"db_exec" / "db_query".
Uses a real SQLite file in tmp_path; mocks bot resolution and workspace root.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig
from tests.integration.conftest import AUTH_HEADERS

_CHANNEL_ID = uuid.UUID("cccc0000-0000-0000-0000-000000000001")
_PIN_ID = uuid.UUID("dddd0000-0000-0000-0000-000000000001")

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
    "source_path": "data/widgets/test_db/index.html",
    "source_channel_id": str(_CHANNEL_ID),
    "source_bot_id": "test-bot",
    "plain_body": "test db widget",
    "display": "inline",
}


# ---------------------------------------------------------------------------
# Fixture: a real pin in SQLite (test DB) + workspace stub
# ---------------------------------------------------------------------------

@pytest.fixture()
async def db_pin(db_session, tmp_path):
    """Create a WidgetDashboardPin row pointing at a bundle in tmp_path."""
    from app.services.dashboard_pins import create_pin
    from app.db.models import Bot, ApiKey

    # Seed the bot row (required by create_pin bot validation).
    api_key = ApiKey(
        id=uuid.uuid4(),
        name="test-key",
        key_hash="testhash",
        key_prefix="test-key-",
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
        display_label="DB test widget",
    )
    return pin, tmp_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ws_patch(ws_root: Path):
    return patch(
        "app.services.channel_workspace.get_channel_workspace_root",
        return_value=str(ws_root),
    )


def _bot_patch():
    return patch("app.agent.bots.get_bot", return_value=_BOT)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_exec_creates_table_and_inserts(client, db_pin):
    pin, tmp_path = db_pin
    ws_root = tmp_path / "workspace"
    (ws_root / "data" / "widgets" / "test_db").mkdir(parents=True)

    with _bot_patch(), _ws_patch(ws_root):
        # CREATE TABLE via db_exec.
        resp = await client.post(
            "/api/v1/widget-actions",
            json={
                "dispatch": "db_exec",
                "dashboard_pin_id": str(pin.id),
                "sql": "CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT)",
                "params": [],
            },
            headers=AUTH_HEADERS,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "db_result" in data


@pytest.mark.asyncio
async def test_db_exec_insert_and_query_roundtrip(client, db_pin):
    pin, tmp_path = db_pin
    ws_root = tmp_path / "workspace"
    (ws_root / "data" / "widgets" / "test_db").mkdir(parents=True)

    with _bot_patch(), _ws_patch(ws_root):
        # Create table.
        await client.post(
            "/api/v1/widget-actions",
            json={
                "dispatch": "db_exec",
                "dashboard_pin_id": str(pin.id),
                "sql": "CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT)",
                "params": [],
            },
            headers=AUTH_HEADERS,
        )
        # Insert a row.
        ins_resp = await client.post(
            "/api/v1/widget-actions",
            json={
                "dispatch": "db_exec",
                "dashboard_pin_id": str(pin.id),
                "sql": "INSERT INTO items(text) VALUES (?)",
                "params": ["hello world"],
            },
            headers=AUTH_HEADERS,
        )
        assert ins_resp.json()["ok"] is True
        ins_result = ins_resp.json()["db_result"]
        assert ins_result["lastInsertRowid"] == 1
        assert ins_result["rowsAffected"] == 1

        # Query back.
        qry_resp = await client.post(
            "/api/v1/widget-actions",
            json={
                "dispatch": "db_query",
                "dashboard_pin_id": str(pin.id),
                "sql": "SELECT * FROM items WHERE text = ?",
                "params": ["hello world"],
            },
            headers=AUTH_HEADERS,
        )
    assert qry_resp.json()["ok"] is True
    rows = qry_resp.json()["db_result"]["rows"]
    assert len(rows) == 1
    assert rows[0]["text"] == "hello world"


@pytest.mark.asyncio
async def test_db_exec_missing_pin_id_returns_error(client, db_pin):
    pin, tmp_path = db_pin

    resp = await client.post(
        "/api/v1/widget-actions",
        json={
            "dispatch": "db_exec",
            "sql": "SELECT 1",
        },
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "dashboard_pin_id" in data["error"]


@pytest.mark.asyncio
async def test_db_query_missing_sql_returns_error(client, db_pin):
    pin, tmp_path = db_pin

    resp = await client.post(
        "/api/v1/widget-actions",
        json={
            "dispatch": "db_query",
            "dashboard_pin_id": str(pin.id),
        },
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "sql" in data["error"]


@pytest.mark.asyncio
async def test_db_exec_inline_widget_returns_error(client, db_session, tmp_path):
    """Inline widgets (no source_path) must not have a DB."""
    from app.services.dashboard_pins import create_pin
    from app.db.models import Bot, ApiKey

    api_key = ApiKey(
        id=uuid.uuid4(),
        name="inline-key",
        key_hash="inlinehash",
        key_prefix="inline-key",
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

    inline_envelope = {
        "content_type": "application/vnd.spindrel.html+interactive",
        "body": "<p>hello</p>",
        "source_bot_id": "test-bot",
        "plain_body": "inline widget",
        "display": "inline",
    }
    pin = await create_pin(
        db_session,
        source_kind="adhoc",
        tool_name="emit_html_widget",
        envelope=inline_envelope,
        source_bot_id="test-bot",
    )

    resp = await client.post(
        "/api/v1/widget-actions",
        json={
            "dispatch": "db_exec",
            "dashboard_pin_id": str(pin.id),
            "sql": "SELECT 1",
        },
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "inline" in data["error"].lower()
