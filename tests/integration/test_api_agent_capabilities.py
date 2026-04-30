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
