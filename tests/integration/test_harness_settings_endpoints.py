"""Endpoint coverage for harness settings + runtime capabilities.

Pins:
- GET /sessions/{id}/harness-settings returns current settings
- POST partial-patch semantics (missing key = no change, null = clear)
- POST 422 on oversized model
- 404 on unknown runtime
- 200 on Claude runtime returns RuntimeCapabilitiesOut shape
- 401 on capabilities without auth
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.db.models import Session as SessionRow
from tests.factories import build_bot, build_channel
from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


async def _make_session(db_session):
    bot = build_bot(id="hs-ep-bot", name="HS EP", model="x")
    bot.harness_runtime = "claude-code"
    db_session.add(bot)
    channel = build_channel(bot_id=bot.id)
    db_session.add(channel)
    session = SessionRow(
        id=uuid.uuid4(),
        client_id="hs-ep-client",
        bot_id=bot.id,
        channel_id=channel.id,
        created_at=datetime.now(timezone.utc),
        last_active=datetime.now(timezone.utc),
    )
    db_session.add(session)
    await db_session.commit()
    return session


# ---------------------------------------------------------------------------
# Harness settings GET/POST
# ---------------------------------------------------------------------------


async def test_get_harness_settings_returns_defaults_when_unset(client, db_session):
    session = await _make_session(db_session)
    resp = await client.get(
        f"/api/v1/sessions/{session.id}/harness-settings", headers=AUTH_HEADERS
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"model": None, "effort": None, "runtime_settings": {}, "mode_models": {}}


async def test_post_sets_then_clears_model(client, db_session):
    session = await _make_session(db_session)
    # Set
    resp = await client.post(
        f"/api/v1/sessions/{session.id}/harness-settings",
        json={"model": "claude-sonnet-4-6"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["model"] == "claude-sonnet-4-6"

    # Re-GET — model persisted, other fields untouched.
    resp = await client.get(
        f"/api/v1/sessions/{session.id}/harness-settings", headers=AUTH_HEADERS
    )
    assert resp.json()["model"] == "claude-sonnet-4-6"

    # Clear via JSON null.
    resp = await client.post(
        f"/api/v1/sessions/{session.id}/harness-settings",
        json={"model": None},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["model"] is None


async def test_partial_patch_leaves_other_fields_unchanged(client, db_session):
    session = await _make_session(db_session)
    await client.post(
        f"/api/v1/sessions/{session.id}/harness-settings",
        json={"model": "claude-sonnet", "effort": "high"},
        headers=AUTH_HEADERS,
    )
    # PATCH only effort — model stays.
    resp = await client.post(
        f"/api/v1/sessions/{session.id}/harness-settings",
        json={"effort": "medium"},
        headers=AUTH_HEADERS,
    )
    body = resp.json()
    assert body["model"] == "claude-sonnet"
    assert body["effort"] == "medium"


async def test_post_oversized_model_returns_422(client, db_session):
    session = await _make_session(db_session)
    resp = await client.post(
        f"/api/v1/sessions/{session.id}/harness-settings",
        json={"model": "x" * 500},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 422, resp.text
    assert "exceeds" in resp.json()["detail"].lower()


async def test_get_harness_settings_404_on_unknown_session(client):
    resp = await client.get(
        f"/api/v1/sessions/{uuid.uuid4()}/harness-settings", headers=AUTH_HEADERS
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Runtime capabilities endpoint
# ---------------------------------------------------------------------------


async def test_capabilities_404_on_unknown_runtime(client):
    resp = await client.get(
        "/api/v1/runtimes/totally-made-up/capabilities", headers=AUTH_HEADERS
    )
    assert resp.status_code == 404


async def test_capabilities_returns_runtime_shape(client):
    """Pin the shape — UI consumes these fields. Skipped when SDK isn't
    installed in the test image (the runtime self-registers on import)."""
    pytest.importorskip("claude_agent_sdk")
    resp = await client.get(
        "/api/v1/runtimes/claude-code/capabilities", headers=AUTH_HEADERS
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "claude-code"
    assert body["display_name"] == "Claude Code"
    assert body["model_is_freeform"] is True
    assert body["effort_values"] == []
    assert body["approval_modes"] == [
        "bypassPermissions", "acceptEdits", "default", "plan",
    ]
    allowed = set(body["slash_policy"]["allowed_command_ids"])
    assert "help" in allowed and "stop" in allowed
    assert "compact" in allowed and "runtime" in allowed
    assert "find" not in allowed
    native_commands = {cmd["id"] for cmd in body["native_commands"]}
    assert native_commands >= {"auth", "version"}
