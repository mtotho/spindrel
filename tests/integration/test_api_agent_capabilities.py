import pytest

from app.db.models import Bot
from tests.integration.conftest import AUTH_HEADERS


@pytest.mark.asyncio
async def test_agent_capability_action_preflight_dry_runs_bot_patch(client, db_session):
    db_session.add(Bot(
        id="agent-preflight",
        name="Agent Preflight",
        model="test/model",
        system_prompt="",
        local_tools=[],
        pinned_tools=[],
    ))
    await db_session.commit()

    resp = await client.post(
        "/api/v1/agent-capabilities/actions/preflight",
        headers=AUTH_HEADERS,
        json={
            "bot_id": "agent-preflight",
            "action_id": "agent-preflight:missing_api_scopes:workspace_bot",
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["schema_version"] == "agent-action-preflight.v1"
    assert payload["status"] == "ready"
    assert payload["can_apply"] is True
    assert payload["action"]["apply_type"] == "bot_patch"
    assert payload["would_change"][0]["field"] == "api_permissions"
    assert payload["would_change"][0]["changes"] is True


@pytest.mark.asyncio
async def test_agent_capability_action_request_queues_pending_repair(client, db_session):
    bot = Bot(
        id="agent-request",
        name="Agent Request",
        model="test/model",
        system_prompt="",
        local_tools=[],
        pinned_tools=[],
    )
    db_session.add(bot)
    await db_session.commit()

    action_id = "agent-request:missing_api_scopes:workspace_bot"
    resp = await client.post(
        "/api/v1/agent-capabilities/actions/request",
        headers=AUTH_HEADERS,
        json={
            "bot_id": "agent-request",
            "action_id": action_id,
            "rationale": "Agent needs API access.",
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["schema_version"] == "agent-repair-request.v1"
    assert payload["ok"] is True
    assert payload["status"] == "queued"
    assert payload["receipt"]["status"] == "needs_review"
    assert payload["receipt"]["result"]["requested_repair"] is True

    await db_session.refresh(bot)
    assert bot.api_key_id is None

    manifest_resp = await client.get(
        "/api/v1/agent-capabilities?bot_id=agent-request&include_endpoints=false",
        headers=AUTH_HEADERS,
    )
    assert manifest_resp.status_code == 200
    manifest = manifest_resp.json()
    pending = manifest["doctor"]["pending_repair_requests"]
    assert [item["target"]["action_id"] for item in pending] == [action_id]
