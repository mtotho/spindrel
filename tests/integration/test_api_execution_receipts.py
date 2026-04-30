from __future__ import annotations

import uuid

import pytest

from app.db.models import Channel
from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


async def test_execution_receipt_api_creates_and_lists_receipts(client, db_session):
    channel_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Receipt API", bot_id="agent", client_id=f"receipt-{uuid.uuid4().hex[:8]}"))
    await db_session.commit()

    created = await client.post(
        "/api/v1/execution-receipts",
        headers=AUTH_HEADERS,
        json={
            "scope": "agent_readiness",
            "action_type": "bot_patch",
            "status": "succeeded",
            "summary": "Applied readiness repair.",
            "actor": {"kind": "human_ui"},
            "target": {"bot_id": "agent", "finding_code": "missing_tools"},
            "before_summary": "Core tools were missing.",
            "after_summary": "Core tools were added.",
            "approval_required": True,
            "approval_ref": "agent_readiness_panel",
            "result": {"applied": True},
            "rollback_hint": "Remove the added tools in Bot settings.",
            "bot_id": "agent",
            "channel_id": str(channel_id),
            "idempotency_key": "api:receipt",
        },
    )

    assert created.status_code == 201
    body = created.json()
    assert body["schema_version"] == "execution-receipt.v1"
    assert body["scope"] == "agent_readiness"
    assert body["target"]["finding_code"] == "missing_tools"
    assert body["approval_required"] is True

    listed = await client.get(
        "/api/v1/execution-receipts",
        params={"scope": "agent_readiness", "bot_id": "agent", "channel_id": str(channel_id)},
        headers=AUTH_HEADERS,
    )

    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [body["id"]]
