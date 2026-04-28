from __future__ import annotations

import uuid
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.db.models import WorkspaceSpatialNode
from app.services.workspace_attention import assign_attention_item, create_user_attention_item
from app.services.workspace_spatial import update_channel_bot_spatial_policy
from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


async def _create_channel(client, **overrides) -> dict:
    payload = {
        "bot_id": "test-bot",
        "client_id": f"mission-control-{uuid.uuid4().hex[:8]}",
        **overrides,
    }
    resp = await client.post("/api/v1/channels", json=payload, headers=AUTH_HEADERS)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_mission(client, *, channel_id: str | None = None, title: str = "Watch service") -> dict:
    body = {
        "title": title,
        "directive": "Watch the target and report actionable changes.",
        "scope": "channel" if channel_id else "workspace",
        "channel_id": channel_id,
        "bot_id": "test-bot",
        "interval_kind": "manual",
        "recurrence": None,
    }
    resp = await client.post("/api/v1/workspace/missions", json=body, headers=AUTH_HEADERS)
    assert resp.status_code == 201, resp.text
    return resp.json()["mission"]


async def _seed_and_place_nodes(client, db_session, *, channel_id: uuid.UUID, far: bool = False) -> None:
    seeded = await client.get("/api/v1/workspace/spatial/nodes", headers=AUTH_HEADERS)
    assert seeded.status_code == 200, seeded.text
    channel_node = (await db_session.execute(
        select(WorkspaceSpatialNode).where(WorkspaceSpatialNode.channel_id == channel_id)
    )).scalar_one()
    bot_node = (await db_session.execute(
        select(WorkspaceSpatialNode).where(WorkspaceSpatialNode.bot_id == "test-bot")
    )).scalar_one()
    channel_node.world_x = 100.0
    channel_node.world_y = 100.0
    bot_node.world_x = 480.0 if not far else 3000.0
    bot_node.world_y = 100.0 if not far else 3000.0
    await db_session.commit()


async def test_mission_control_groups_missions_attention_and_ready_spatial(client, db_session):
    channel = await _create_channel(client)
    channel_id = uuid.UUID(channel["id"])
    await update_channel_bot_spatial_policy(
        db_session,
        channel_id,
        "test-bot",
        {"enabled": True, "allow_movement": True, "allow_nearby_inspect": True, "step_world_units": 32, "awareness_radius_steps": 20},
    )
    mission = await _create_mission(client, channel_id=channel["id"])
    await _seed_and_place_nodes(client, db_session, channel_id=channel_id)

    attention = await create_user_attention_item(
        db_session,
        actor="tester",
        channel_id=channel_id,
        target_kind="channel",
        target_id=channel["id"],
        title="Review open incident",
        severity="warning",
        requires_response=True,
    )
    await assign_attention_item(
        db_session,
        attention.id,
        bot_id="test-bot",
        mode="next_heartbeat",
        assigned_by="tester",
    )

    resp = await client.get("/api/v1/workspace/mission-control", headers=AUTH_HEADERS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["summary"]["active_missions"] == 1
    assert body["summary"]["active_bots"] == 1
    lane = body["lanes"][0]
    assert lane["bot_id"] == "test-bot"
    assert lane["missions"][0]["mission"]["id"] == mission["id"]
    assert lane["missions"][0]["spatial_advisory"]["status"] == "ready"
    assert lane["missions"][0]["spatial_advisory"]["target_channel_name"] == channel["name"]
    assert lane["attention_signals"][0]["title"] == "Review open incident"


async def test_mission_control_spatial_far_blocked_and_unknown(client, db_session):
    channel = await _create_channel(client)
    channel_id = uuid.UUID(channel["id"])
    await update_channel_bot_spatial_policy(
        db_session,
        channel_id,
        "test-bot",
        {"enabled": True, "allow_movement": True, "allow_nearby_inspect": True, "step_world_units": 32, "awareness_radius_steps": 20},
    )
    far_mission = await _create_mission(client, channel_id=channel["id"], title="Far mission")
    await _seed_and_place_nodes(client, db_session, channel_id=channel_id, far=True)

    resp = await client.get("/api/v1/workspace/mission-control", headers=AUTH_HEADERS)
    assert resp.status_code == 200, resp.text
    far_row = resp.json()["mission_rows"][far_mission["id"]]
    assert far_row["spatial_advisory"]["status"] == "far"

    await update_channel_bot_spatial_policy(
        db_session,
        channel_id,
        "test-bot",
        {"enabled": True, "allow_movement": True, "allow_nearby_inspect": False},
    )
    blocked = await client.get("/api/v1/workspace/mission-control", headers=AUTH_HEADERS)
    assert blocked.status_code == 200, blocked.text
    blocked_row = blocked.json()["mission_rows"][far_mission["id"]]
    assert blocked_row["spatial_advisory"]["status"] == "blocked"

    workspace_mission = await _create_mission(client, title="Workspace mission")
    unknown = await client.get("/api/v1/workspace/mission-control", headers=AUTH_HEADERS)
    assert unknown.status_code == 200, unknown.text
    unknown_row = unknown.json()["mission_rows"][workspace_mission["id"]]
    assert unknown_row["spatial_advisory"]["status"] == "unknown"


class _FakeMissionControlCompletions:
    def __init__(self, channel_id: str):
        self.channel_id = channel_id

    async def create(self, **_kwargs):
        content = json.dumps({
            "brief": {
                "summary": "Recent task failures point to a channel follow-up.",
                "next_focus": "Queue a grounded sweep for the affected channel.",
                "confidence": "high",
            },
            "drafts": [
                {
                    "title": "Sweep recent channel failures",
                    "directive": "Inspect the recent failed task output, identify the first actionable fix, and report the next concrete step.",
                    "rationale": "The workspace has recent failed work that is more useful than attention noise.",
                    "scope": "channel",
                    "bot_id": "test-bot",
                    "target_channel_id": self.channel_id,
                    "interval_kind": "manual",
                    "recurrence": None,
                }
            ],
        })
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class _FakeMissionControlClient:
    def __init__(self, channel_id: str):
        self.chat = SimpleNamespace(completions=_FakeMissionControlCompletions(channel_id))


async def test_mission_control_ai_draft_lifecycle(client, monkeypatch):
    channel = await _create_channel(client)

    monkeypatch.setattr("app.services.workspace_mission_ai.get_llm_client", lambda _provider_id=None: _FakeMissionControlClient(channel["id"]))

    refresh = await client.post(
        "/api/v1/workspace/mission-control/ai/refresh",
        json={"instruction": "Find something useful to queue."},
        headers=AUTH_HEADERS,
    )
    assert refresh.status_code == 200, refresh.text
    generated = refresh.json()
    assert generated["assistant_brief"]["summary"].startswith("Recent task failures")
    assert len(generated["drafts"]) == 1
    draft = generated["drafts"][0]
    assert draft["status"] == "draft"
    assert draft["bot_id"] == "test-bot"

    control = await client.get("/api/v1/workspace/mission-control", headers=AUTH_HEADERS)
    assert control.status_code == 200, control.text
    assert control.json()["assistant_brief"]["confidence"] == "high"
    assert control.json()["drafts"][0]["id"] == draft["id"]

    patched = await client.patch(
        f"/api/v1/workspace/mission-control/drafts/{draft['id']}",
        json={"title": "Sweep the failed task queue", "scope": "channel", "target_channel_id": channel["id"]},
        headers=AUTH_HEADERS,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["draft"]["title"] == "Sweep the failed task queue"

    accepted = await client.post(
        f"/api/v1/workspace/mission-control/drafts/{draft['id']}/accept",
        headers=AUTH_HEADERS,
    )
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert body["draft"]["status"] == "accepted"
    assert body["mission"]["title"] == "Sweep the failed task queue"
    assert body["mission"]["assignments"][0]["bot_id"] == "test-bot"


async def test_mission_control_ai_dismiss_hides_draft(client, monkeypatch):
    channel = await _create_channel(client)
    monkeypatch.setattr("app.services.workspace_mission_ai.get_llm_client", lambda _provider_id=None: _FakeMissionControlClient(channel["id"]))

    refresh = await client.post("/api/v1/workspace/mission-control/ai/refresh", json={}, headers=AUTH_HEADERS)
    assert refresh.status_code == 200, refresh.text
    draft_id = refresh.json()["drafts"][0]["id"]

    dismissed = await client.post(
        f"/api/v1/workspace/mission-control/drafts/{draft_id}/dismiss",
        headers=AUTH_HEADERS,
    )
    assert dismissed.status_code == 200, dismissed.text
    assert dismissed.json()["draft"]["status"] == "dismissed"

    control = await client.get("/api/v1/workspace/mission-control", headers=AUTH_HEADERS)
    assert control.status_code == 200, control.text
    assert all(row["id"] != draft_id for row in control.json()["drafts"])
