"""Integration tests for /api/v1/widget-debug/events and the tool-signature endpoint.

Uses the admin-scoped test client — widget-JWT pin-scoping is exercised via a
forced dependency override so we don't need to mint a real widget token.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.dependencies import ApiKeyAuth, verify_auth_or_user
from app.services import widget_debug


@pytest.fixture(autouse=True)
def _reset_ring():
    widget_debug.reset_all()
    yield
    widget_debug.reset_all()


@pytest.mark.asyncio
async def test_post_and_get_events_roundtrip(client):
    pin = str(uuid4())
    # POST one event
    resp = await client.post(
        "/api/v1/widget-debug/events",
        json={
            "pin_id": pin,
            "kind": "tool-call",
            "ts": 1700000000000,
            "payload": {"tool": "frigate_snapshot", "ok": True, "response": {"attachment_id": "abc"}},
        },
        headers={"Authorization": "Bearer test-key"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True}

    # GET — newest first, includes our event
    resp = await client.get(
        f"/api/v1/widget-debug/events?pin_id={pin}",
        headers={"Authorization": "Bearer test-key"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pin_id"] == pin
    assert len(body["events"]) == 1
    ev = body["events"][0]
    assert ev["kind"] == "tool-call"
    assert ev["tool"] == "frigate_snapshot"
    assert ev["response"]["attachment_id"] == "abc"


@pytest.mark.asyncio
async def test_get_empty_pin_returns_empty_list(client):
    pin = str(uuid4())
    resp = await client.get(
        f"/api/v1/widget-debug/events?pin_id={pin}",
        headers={"Authorization": "Bearer test-key"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"pin_id": pin, "events": []}


@pytest.mark.asyncio
async def test_limit_bounds_response(client):
    pin = str(uuid4())
    for i in range(10):
        await client.post(
            "/api/v1/widget-debug/events",
            json={"pin_id": pin, "kind": "log", "ts": 0, "payload": {"seq": i}},
            headers={"Authorization": "Bearer test-key"},
        )
    resp = await client.get(
        f"/api/v1/widget-debug/events?pin_id={pin}&limit=3",
        headers={"Authorization": "Bearer test-key"},
    )
    assert resp.status_code == 200
    evs = resp.json()["events"]
    assert len(evs) == 3
    # Newest first — last posted was seq=9
    assert evs[0]["seq"] == 9


@pytest.mark.asyncio
async def test_delete_clears_events(client):
    pin = str(uuid4())
    await client.post(
        "/api/v1/widget-debug/events",
        json={"pin_id": pin, "kind": "log", "ts": 0, "payload": {"msg": "hi"}},
        headers={"Authorization": "Bearer test-key"},
    )
    resp = await client.delete(
        f"/api/v1/widget-debug/events?pin_id={pin}",
        headers={"Authorization": "Bearer test-key"},
    )
    assert resp.status_code == 200
    resp = await client.get(
        f"/api/v1/widget-debug/events?pin_id={pin}",
        headers={"Authorization": "Bearer test-key"},
    )
    assert resp.json()["events"] == []


@pytest.mark.asyncio
async def test_widget_token_cannot_post_for_other_pin(client):
    """A widget-scoped ApiKeyAuth carries pin_id and must only write that pin."""
    own_pin = uuid4()
    other_pin = uuid4()

    async def _widget_auth():
        return ApiKeyAuth(
            key_id=UUID("00000000-0000-0000-0000-000000000001"),
            scopes=[],
            name="widget:bot-x",
            pin_id=own_pin,
        )

    # Override auth on the live ASGI app inside the client
    app = client._transport.app
    original = app.dependency_overrides.get(verify_auth_or_user)
    app.dependency_overrides[verify_auth_or_user] = _widget_auth
    try:
        # Allowed write: own pin
        r = await client.post(
            "/api/v1/widget-debug/events",
            json={"pin_id": str(own_pin), "kind": "log", "ts": 0, "payload": {}},
            headers={"Authorization": "Bearer test-key"},
        )
        assert r.status_code == 200, r.text
        # Forbidden write: different pin
        r = await client.post(
            "/api/v1/widget-debug/events",
            json={"pin_id": str(other_pin), "kind": "log", "ts": 0, "payload": {}},
            headers={"Authorization": "Bearer test-key"},
        )
        assert r.status_code == 403
        # Forbidden read: different pin
        r = await client.get(
            f"/api/v1/widget-debug/events?pin_id={other_pin}",
            headers={"Authorization": "Bearer test-key"},
        )
        assert r.status_code == 403
    finally:
        if original is not None:
            app.dependency_overrides[verify_auth_or_user] = original
        else:
            app.dependency_overrides.pop(verify_auth_or_user, None)


# ---------------------------------------------------------------------------
# Tool signature endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_signature_local_tool_with_returns(client):
    # inspect_widget_pin declares a `returns=` schema — use it as the fixture.
    resp = await client.get(
        "/api/v1/tools/inspect_widget_pin/signature",
        headers={"Authorization": "Bearer test-key"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "inspect_widget_pin"
    assert body["kind"] == "local"
    assert body["input_schema"] is not None
    # Declared returns schema
    assert body["returns_schema"] is not None
    props = (body["returns_schema"] or {}).get("properties", {})
    assert "events" in props


@pytest.mark.asyncio
async def test_tool_signature_unknown_tool_404(client):
    resp = await client.get(
        "/api/v1/tools/this_tool_does_not_exist/signature",
        headers={"Authorization": "Bearer test-key"},
    )
    assert resp.status_code == 404
