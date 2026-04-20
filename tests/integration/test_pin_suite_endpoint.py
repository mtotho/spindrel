"""Integration tests for the /dashboard/pins/suite endpoint (Phase B.6)."""
from __future__ import annotations

import uuid

import pytest

from app.agent.bots import BotConfig, MemoryConfig
from tests.integration.conftest import AUTH_HEADERS


_BOT = BotConfig(
    id="test-bot",
    name="Test Bot",
    model="test/model",
    system_prompt="",
    memory=MemoryConfig(enabled=False),
)


@pytest.fixture()
async def seeded(db_session, tmp_path, monkeypatch):
    from app.db.models import ApiKey, Bot

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

    # Isolate suite DB paths per test.
    from app.services import paths as paths_mod
    monkeypatch.setattr(
        paths_mod, "local_workspace_base", lambda: str(tmp_path),
    )
    from unittest.mock import patch
    mock_bot_ctx = patch("app.agent.bots.get_bot", return_value=_BOT)
    mock_bot_ctx.start()
    yield tmp_path
    mock_bot_ctx.stop()


@pytest.mark.asyncio
async def test_list_suites_includes_mission_control(client, seeded):
    resp = await client.get(
        "/api/v1/widgets/suites",
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    suites = resp.json()["suites"]
    slugs = [s["suite_id"] for s in suites]
    assert "mission-control" in slugs
    mc = next(s for s in suites if s["suite_id"] == "mission-control")
    assert mc["members"] == ["mc_timeline", "mc_kanban", "mc_tasks"]


@pytest.mark.asyncio
async def test_pin_suite_creates_all_members(client, seeded):
    resp = await client.post(
        "/api/v1/widgets/dashboard/pins/suite",
        json={
            "suite_id": "mission-control",
            "dashboard_key": "default",
            "source_bot_id": "test-bot",
        },
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["suite_id"] == "mission-control"
    assert body["dashboard_key"] == "default"
    assert len(body["pins"]) == 3
    labels = sorted(p["display_label"] for p in body["pins"])
    assert labels == ["mc_kanban", "mc_tasks", "mc_timeline"]


@pytest.mark.asyncio
async def test_pin_suite_rejects_unknown_suite(client, seeded):
    resp = await client.post(
        "/api/v1/widgets/dashboard/pins/suite",
        json={
            "suite_id": "nope-nope",
            "dashboard_key": "default",
        },
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_pin_suite_narrow_members(client, seeded):
    """`members` narrows the set; bad member → 400."""
    resp_bad = await client.post(
        "/api/v1/widgets/dashboard/pins/suite",
        json={
            "suite_id": "mission-control",
            "dashboard_key": "default",
            "members": ["not_a_member"],
            "source_bot_id": "test-bot",
        },
        headers=AUTH_HEADERS,
    )
    assert resp_bad.status_code == 400

    resp_ok = await client.post(
        "/api/v1/widgets/dashboard/pins/suite",
        json={
            "suite_id": "mission-control",
            "dashboard_key": "default",
            "members": ["mc_kanban", "mc_tasks"],
            "source_bot_id": "test-bot",
        },
        headers=AUTH_HEADERS,
    )
    assert resp_ok.status_code == 200, resp_ok.text
    labels = sorted(p["display_label"] for p in resp_ok.json()["pins"])
    assert labels == ["mc_kanban", "mc_tasks"]
