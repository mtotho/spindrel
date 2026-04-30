from __future__ import annotations

import uuid

import pytest

from app.db.models import Channel
from app.services.widget_agency_receipts import (
    MAX_SCREENSHOT_DATA_URL_CHARS,
    build_widget_authoring_metadata,
    build_widget_agency_state,
    create_widget_agency_receipt,
    create_widget_authoring_receipt,
    list_channel_widget_agency_receipts,
    serialize_widget_agency_receipt,
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


def test_build_widget_authoring_metadata_keeps_compact_evidence() -> None:
    metadata, warning = build_widget_authoring_metadata(
        library_ref="bot/project_status",
        touched_files=["widget://bot/project_status/index.html"],
        health_status="healthy",
        health_summary="Runtime smoke check rendered the widget.",
        check_phases=[{"name": "runtime", "ok": True}],
        screenshot_data_url="data:image/png;base64,small",
    )

    assert warning is None
    assert metadata["kind"] == "authoring"
    assert metadata["library_ref"] == "bot/project_status"
    assert metadata["health_status"] == "healthy"
    assert metadata["touched_files"] == ["widget://bot/project_status/index.html"]
    assert metadata["screenshot"]["data_url"] == "data:image/png;base64,small"


def test_build_widget_authoring_metadata_omits_large_screenshot() -> None:
    metadata, warning = build_widget_authoring_metadata(
        screenshot_data_url="x" * (MAX_SCREENSHOT_DATA_URL_CHARS + 1),
    )

    assert warning
    assert "screenshot" not in metadata
    assert metadata["screenshot_omitted"]["reason"] == "too_large"


@pytest.mark.asyncio
async def test_create_widget_authoring_receipt_serializes_kind_and_action(db_session):
    receipt, warning = await create_widget_authoring_receipt(
        db_session,
        channel_id=None,
        dashboard_key="workspace:spatial",
        action="checked",
        summary="Checked the project status widget in the runtime host.",
        bot_id="bot-1",
        pin_id=str(uuid.uuid4()),
        library_ref="workspace/project_status",
        health_status="healthy",
        check_phases=[{"name": "runtime", "ok": True}],
    )

    serialized = serialize_widget_agency_receipt(receipt)

    assert warning is None
    assert serialized["kind"] == "authoring"
    assert serialized["channel_id"] is None
    assert serialized["dashboard_key"] == "workspace:spatial"
    assert serialized["action"] == "authoring_checked"
    assert serialized["metadata"]["kind"] == "authoring"
    assert serialized["metadata"]["library_ref"] == "workspace/project_status"
    assert serialized["affected_pin_ids"]
