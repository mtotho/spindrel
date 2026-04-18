"""Tests for the modal submission endpoints.

Exercised at the route-handler level (bypassing auth Depends) because the
only interesting behavior is the bridge between HTTP → modal_waiter.
"""
from __future__ import annotations

import asyncio

import pytest

from app.routers.api_v1_modals import (
    ModalSubmitRequest,
    cancel_modal,
    submit_modal,
)
from app.services import modal_waiter

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset():
    modal_waiter.reset()
    yield
    modal_waiter.reset()


async def test_submit_resolves_waiter():
    modal_waiter.register("cb-1")

    async def wait_and_return():
        return await modal_waiter.wait("cb-1", timeout=5.0)

    task = asyncio.create_task(wait_and_return())
    await asyncio.sleep(0)

    resp = await submit_modal(
        "cb-1",
        ModalSubmitRequest(
            values={"name": "alice"},
            submitted_by="UA",
            metadata={"source": "slack"},
        ),
        _auth=True,
    )
    assert resp.accepted is True

    result = await asyncio.wait_for(task, timeout=1.0)
    assert result["ok"] is True
    assert result["values"] == {"name": "alice"}
    assert result["submitted_by"] == "UA"


async def test_submit_for_unknown_callback_returns_not_accepted():
    resp = await submit_modal(
        "missing",
        ModalSubmitRequest(values={}, submitted_by="UA"),
        _auth=True,
    )
    assert resp.accepted is False
    assert resp.reason == "unknown_callback_id"


async def test_cancel_resolves_waiter_with_error():
    modal_waiter.register("cb-2")

    async def wait_and_return():
        return await modal_waiter.wait("cb-2", timeout=5.0)

    task = asyncio.create_task(wait_and_return())
    await asyncio.sleep(0)

    resp = await cancel_modal("cb-2", _auth=True)
    assert resp.accepted is True

    result = await asyncio.wait_for(task, timeout=1.0)
    assert result["ok"] is False
    assert result["error"] == "user_dismissed"


async def test_submit_with_channel_id_publishes_bus_event(monkeypatch):
    from app.routers import api_v1_modals as mod

    published: list = []

    def fake_publish(channel_id, event):
        published.append((channel_id, event))
        return 1

    monkeypatch.setattr(mod, "publish_typed", fake_publish)

    modal_waiter.register("cb-3")
    resp = await submit_modal(
        "cb-3",
        ModalSubmitRequest(
            values={"x": "y"},
            submitted_by="UX",
            channel_id="33333333-3333-3333-3333-333333333333",
        ),
        _auth=True,
    )
    assert resp.accepted is True
    assert len(published) == 1
    _, event = published[0]
    assert event.kind.value == "modal_submitted"
    assert event.payload.callback_id == "cb-3"
    assert event.payload.values == {"x": "y"}
