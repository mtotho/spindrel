from __future__ import annotations

import json
import uuid

import pytest

from app.db.models import Channel
from app.services.execution_receipts import (
    create_execution_receipt,
    list_execution_receipts,
    serialize_execution_receipt,
)


pytestmark = pytest.mark.asyncio


async def test_create_execution_receipt_serializes_contract(db_session):
    channel_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Readiness", bot_id="agent", client_id=f"receipt-{uuid.uuid4().hex[:8]}"))
    await db_session.commit()

    receipt = await create_execution_receipt(
        db_session,
        scope="agent_readiness",
        action_type="bot_patch",
        status="succeeded",
        summary="Applied readiness repair.",
        actor={"kind": "human_ui"},
        target={"bot_id": "agent", "finding_code": "missing_api_permissions"},
        before_summary="Bot could not call APIs.",
        after_summary="Bot has workspace_bot scopes.",
        approval_required=True,
        approval_ref="agent_readiness_panel",
        result={"applied": True},
        rollback_hint="Remove the added API scopes.",
        bot_id="agent",
        channel_id=channel_id,
        idempotency_key="agent_readiness:agent:api",
    )

    serialized = serialize_execution_receipt(receipt)

    assert serialized["schema_version"] == "execution-receipt.v1"
    assert serialized["scope"] == "agent_readiness"
    assert serialized["action_type"] == "bot_patch"
    assert serialized["status"] == "succeeded"
    assert serialized["actor"] == {"kind": "human_ui"}
    assert serialized["target"]["bot_id"] == "agent"
    assert serialized["approval_required"] is True
    assert serialized["result"] == {"applied": True}
    assert serialized["channel_id"] == str(channel_id)


async def test_execution_receipts_are_idempotent_by_scope_key(db_session):
    first = await create_execution_receipt(
        db_session,
        scope="agent_readiness",
        action_type="bot_patch",
        status="reported",
        summary="Original summary",
        bot_id="agent",
        idempotency_key="same",
    )
    second = await create_execution_receipt(
        db_session,
        scope="agent_readiness",
        action_type="bot_patch",
        status="succeeded",
        summary="Updated summary",
        bot_id="agent",
        idempotency_key="same",
    )

    assert second.id == first.id
    assert getattr(second, "_spindrel_created") is False
    assert second.summary == "Updated summary"
    assert second.status == "succeeded"


async def test_list_execution_receipts_filters_by_bot_and_channel(db_session):
    channel_id = uuid.uuid4()
    other_channel_id = uuid.uuid4()
    db_session.add_all([
        Channel(id=channel_id, name="Readiness", bot_id="agent", client_id=f"receipt-{uuid.uuid4().hex[:8]}"),
        Channel(id=other_channel_id, name="Other", bot_id="other", client_id=f"receipt-{uuid.uuid4().hex[:8]}"),
    ])
    await db_session.commit()
    await create_execution_receipt(
        db_session,
        scope="agent_readiness",
        action_type="bot_patch",
        summary="Target receipt",
        bot_id="agent",
        channel_id=channel_id,
    )
    await create_execution_receipt(
        db_session,
        scope="agent_readiness",
        action_type="bot_patch",
        summary="Other receipt",
        bot_id="other",
        channel_id=other_channel_id,
    )

    rows = await list_execution_receipts(
        db_session,
        scope="agent_readiness",
        bot_id="agent",
        channel_id=channel_id,
    )

    assert [row.summary for row in rows] == ["Target receipt"]


async def test_publish_execution_receipt_tool_uses_agent_context(
    db_session,
    patched_async_sessions,
    agent_context,
):
    channel_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Tool Readiness", bot_id="agent", client_id=f"receipt-{uuid.uuid4().hex[:8]}"))
    await db_session.commit()
    agent_context(bot_id="agent", channel_id=channel_id)

    from app.tools.local.execution_receipts import publish_execution_receipt

    payload = json.loads(await publish_execution_receipt(
        action_type="bot_patch",
        summary="Recorded readiness repair.",
        target={"finding_code": "missing_api_permissions"},
        idempotency_key="tool:receipt",
    ))

    assert payload["ok"] is True
    assert payload["receipt"]["bot_id"] == "agent"
    assert payload["receipt"]["channel_id"] == str(channel_id)
    assert payload["receipt"]["target"]["finding_code"] == "missing_api_permissions"
