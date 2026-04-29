from __future__ import annotations

import uuid

import pytest

from app.db.models import Channel
from app.services.widget_agency_receipts import (
    build_widget_agency_state,
    create_widget_agency_receipt,
    list_channel_widget_agency_receipts,
)


def test_build_widget_agency_state_keeps_compact_pin_snapshot() -> None:
    state = build_widget_agency_state(
        dashboard={"slug": "channel:one", "name": "Channel One", "grid_config": {"borderless": True}},
        pins=[
            {
                "id": str(uuid.uuid4()),
                "display_label": "Operations",
                "tool_name": "ops_widget",
                "zone": "rail",
                "grid_layout": {"x": 0, "y": 0, "w": 1, "h": 8},
                "envelope": {"body": {"large": "ignored"}},
            }
        ],
    )

    assert state["dashboard"]["grid_config"] == {"borderless": True}
    assert state["pins"][0]["label"] == "Operations"
    assert state["pins"][0]["zone"] == "rail"
    assert "envelope" not in state["pins"][0]


@pytest.mark.asyncio
async def test_create_and_list_channel_widget_agency_receipts(db_session):
    channel_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name="Receipts", bot_id="bot-1"))
    await db_session.commit()

    receipt = await create_widget_agency_receipt(
        db_session,
        channel_id=channel_id,
        dashboard_key=f"channel:{channel_id}",
        action="move_pins",
        summary="Moved 1 widget pin into the rail.",
        reason="The dock is hidden in chat.",
        bot_id="bot-1",
        affected_pin_ids=[str(uuid.uuid4())],
        before_state={"pins": []},
        after_state={"pins": [{"label": "Ops"}]},
    )

    rows = await list_channel_widget_agency_receipts(db_session, channel_id)

    assert rows[0]["id"] == str(receipt.id)
    assert rows[0]["action"] == "move_pins"
    assert rows[0]["summary"] == "Moved 1 widget pin into the rail."
    assert rows[0]["reason"] == "The dock is hidden in chat."
    assert rows[0]["after_state"]["pins"][0]["label"] == "Ops"
