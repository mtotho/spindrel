"""E2E coverage for Agent Readiness dry-run repair preflight."""

import uuid

import pytest

from tests.e2e.harness.client import E2EClient
from tests.e2e.harness.config import E2EConfig


@pytest.mark.e2e
async def test_agent_readiness_preflight_checks_repair_before_mutation(
    client: E2EClient,
    e2e_config: E2EConfig,
) -> None:
    bot_id = f"e2e-readiness-{uuid.uuid4().hex[:8]}"
    await client.create_bot({
        "id": bot_id,
        "name": "E2E Readiness Preflight",
        "model": e2e_config.default_model,
        "system_prompt": "Used by the Agent Readiness preflight e2e test.",
        "local_tools": [],
        "pinned_tools": [],
        "api_permissions": [],
    })
    try:
        response = await client.post(
            "/api/v1/agent-capabilities/actions/preflight",
            json={
                "bot_id": bot_id,
                "action_id": f"{bot_id}:missing_api_scopes:workspace_bot",
            },
        )
        response.raise_for_status()
        payload = response.json()

        assert payload["schema_version"] == "agent-action-preflight.v1"
        assert payload["status"] == "ready"
        assert payload["can_apply"] is True
        assert payload["action"]["apply_type"] == "bot_patch"
        assert any(
            change["field"] == "api_permissions" and change["changes"] is True
            for change in payload["would_change"]
        )

        bot = await client.get_bot(bot_id)
        assert bot.get("api_permissions") in ([], None)
    finally:
        await client.delete_bot(bot_id, force=True)
