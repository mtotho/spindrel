"""Integration tests for channel file pin/unpin endpoints."""
import uuid

import pytest
from sqlalchemy import select

from app.db.models import Channel, WidgetDashboardPin, WidgetInstance
from tests.integration.conftest import client, db_session, engine, _TEST_REGISTRY  # noqa: F401


async def _get_channel_pinned_files_instance(db_session, channel_id: uuid.UUID) -> WidgetInstance | None:
    return (
        await db_session.execute(
            select(WidgetInstance).where(
                WidgetInstance.widget_kind == "native_app",
                WidgetInstance.widget_ref == "core/pinned_files_native",
                WidgetInstance.scope_kind == "channel",
                WidgetInstance.scope_ref == str(channel_id),
            )
        )
    ).scalar_one_or_none()


@pytest.mark.asyncio
async def test_pin_file_creates_widget_instance_and_dock_pin(client, db_session):
    ch = Channel(id=uuid.uuid4(), name="test-ch", bot_id="test-bot", config={})
    db_session.add(ch)
    await db_session.commit()

    res = await client.post(
        f"/api/v1/channels/{ch.id}/pins",
        json={"path": "report.md", "position": "right"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["path"] == "report.md"
    assert body["position"] == "right"
    assert body["pinned_by"] == "user"
    assert "pinned_at" in body

    instance = await _get_channel_pinned_files_instance(db_session, ch.id)
    assert instance is not None
    state = instance.state or {}
    assert state["active_path"] == "report.md"
    assert state["pinned_files"] == [{
        "path": "report.md",
        "pinned_at": body["pinned_at"],
        "pinned_by": "user",
    }]

    pin = (
        await db_session.execute(
            select(WidgetDashboardPin).where(
                WidgetDashboardPin.dashboard_key == f"channel:{ch.id}",
                WidgetDashboardPin.widget_instance_id == instance.id,
            )
        )
    ).scalar_one_or_none()
    assert pin is not None
    assert pin.zone == "dock"


@pytest.mark.asyncio
async def test_pin_deduplicates_by_path_and_reuses_single_widget(client, db_session):
    ch = Channel(id=uuid.uuid4(), name="test-ch", bot_id="test-bot", config={})
    db_session.add(ch)
    await db_session.commit()

    first = await client.post(
        f"/api/v1/channels/{ch.id}/pins",
        json={"path": "report.md", "position": "right"},
    )
    assert first.status_code == 200, first.text
    await client.post(
        f"/api/v1/channels/{ch.id}/pins",
        json={"path": "notes.md", "position": "right"},
    )
    second = await client.post(
        f"/api/v1/channels/{ch.id}/pins",
        json={"path": "report.md", "position": "bottom"},
    )
    assert second.status_code == 200, second.text

    instance = await _get_channel_pinned_files_instance(db_session, ch.id)
    assert instance is not None
    state = instance.state or {}
    assert state["active_path"] == "report.md"
    assert [item["path"] for item in state["pinned_files"]] == ["report.md", "notes.md"]
    assert len(state["pinned_files"]) == 2

    pins = (
        await db_session.execute(
            select(WidgetDashboardPin).where(
                WidgetDashboardPin.dashboard_key == f"channel:{ch.id}",
                WidgetDashboardPin.widget_instance_id == instance.id,
            )
        )
    ).scalars().all()
    assert len(pins) == 1


@pytest.mark.asyncio
async def test_unpin_removes_entry_but_keeps_empty_widget(client, db_session):
    ch = Channel(id=uuid.uuid4(), name="test-ch", bot_id="test-bot", config={})
    db_session.add(ch)
    await db_session.commit()

    first = await client.post(
        f"/api/v1/channels/{ch.id}/pins",
        json={"path": "report.md", "position": "right"},
    )
    assert first.status_code == 200, first.text

    res = await client.delete(f"/api/v1/channels/{ch.id}/pins?path=report.md")
    assert res.status_code == 200, res.text

    instance = await _get_channel_pinned_files_instance(db_session, ch.id)
    assert instance is not None
    state = instance.state or {}
    assert state["active_path"] is None
    assert state["pinned_files"] == []


@pytest.mark.asyncio
async def test_unpin_nonexistent_returns_404(client, db_session):
    ch = Channel(id=uuid.uuid4(), name="test-ch", bot_id="test-bot", config={})
    db_session.add(ch)
    await db_session.commit()

    res = await client.delete(f"/api/v1/channels/{ch.id}/pins?path=nonexistent.md")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_pin_invalid_position_returns_422(client, db_session):
    ch = Channel(id=uuid.uuid4(), name="test-ch", bot_id="test-bot", config={})
    db_session.add(ch)
    await db_session.commit()

    res = await client.post(
        f"/api/v1/channels/{ch.id}/pins",
        json={"path": "report.md", "position": "left"},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_pin_channel_not_found(client, db_session):
    fake_id = uuid.uuid4()
    res = await client.post(
        f"/api/v1/channels/{fake_id}/pins",
        json={"path": "report.md"},
    )
    assert res.status_code == 404
