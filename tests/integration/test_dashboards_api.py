"""Integration tests for /api/v1/widgets/dashboards CRUD + slug-scoped pins."""
from __future__ import annotations

import pytest


AUTH_HEADERS = {"Authorization": "Bearer test-key"}


def _envelope(label: str = "x") -> dict:
    return {
        "content_type": "application/vnd.spindrel.components+json",
        "body": "{}",
        "plain_body": "ok",
        "display": "inline",
        "truncated": False,
        "record_id": None,
        "byte_size": 2,
        "display_label": label,
    }


@pytest.mark.asyncio
async def test_list_includes_default(client):
    r = await client.get("/api/v1/widgets/dashboards", headers=AUTH_HEADERS)
    assert r.status_code == 200
    slugs = [d["slug"] for d in r.json()["dashboards"]]
    assert "default" in slugs


@pytest.mark.asyncio
async def test_create_and_fetch(client):
    r = await client.post(
        "/api/v1/widgets/dashboards",
        json={"slug": "home", "name": "Home", "icon": "Home", "pin_to_rail": True},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["slug"] == "home"
    assert created["pin_to_rail"] is True

    g = await client.get("/api/v1/widgets/dashboards/home", headers=AUTH_HEADERS)
    assert g.status_code == 200
    assert g.json()["name"] == "Home"


@pytest.mark.asyncio
async def test_create_rejects_reserved_slug(client):
    r = await client.post(
        "/api/v1/widgets/dashboards",
        json={"slug": "dev", "name": "Dev"},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_update_metadata(client):
    await client.post(
        "/api/v1/widgets/dashboards",
        json={"slug": "home", "name": "Home"},
        headers=AUTH_HEADERS,
    )
    r = await client.patch(
        "/api/v1/widgets/dashboards/home",
        json={"name": "Home Office", "pin_to_rail": True},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Home Office"
    assert body["pin_to_rail"] is True


@pytest.mark.asyncio
async def test_delete_nondefault(client):
    await client.post(
        "/api/v1/widgets/dashboards",
        json={"slug": "home", "name": "Home"},
        headers=AUTH_HEADERS,
    )
    r = await client.delete("/api/v1/widgets/dashboards/home", headers=AUTH_HEADERS)
    assert r.status_code == 200
    g = await client.get("/api/v1/widgets/dashboards/home", headers=AUTH_HEADERS)
    assert g.status_code == 404


@pytest.mark.asyncio
async def test_delete_default_forbidden(client):
    r = await client.delete("/api/v1/widgets/dashboards/default", headers=AUTH_HEADERS)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_pins_are_scoped_by_slug(client):
    # Create two dashboards, pin a widget to each, verify isolation.
    await client.post(
        "/api/v1/widgets/dashboards",
        json={"slug": "home", "name": "Home"},
        headers=AUTH_HEADERS,
    )
    await client.post(
        "/api/v1/widgets/dashboard/pins",
        json={
            "source_kind": "adhoc", "tool_name": "a", "envelope": _envelope("a"),
            "dashboard_key": "default",
        },
        headers=AUTH_HEADERS,
    )
    await client.post(
        "/api/v1/widgets/dashboard/pins",
        json={
            "source_kind": "adhoc", "tool_name": "b", "envelope": _envelope("b"),
            "dashboard_key": "home",
        },
        headers=AUTH_HEADERS,
    )
    d = await client.get("/api/v1/widgets/dashboard?slug=default", headers=AUTH_HEADERS)
    h = await client.get("/api/v1/widgets/dashboard?slug=home", headers=AUTH_HEADERS)
    assert [p["tool_name"] for p in d.json()["pins"]] == ["a"]
    assert [p["tool_name"] for p in h.json()["pins"]] == ["b"]


@pytest.mark.asyncio
async def test_get_unknown_dashboard_returns_404(client):
    r = await client.get("/api/v1/widgets/dashboard?slug=nope", headers=AUTH_HEADERS)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_redirect_target_falls_back_to_default(client):
    r = await client.get(
        "/api/v1/widgets/dashboards/redirect-target", headers=AUTH_HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["slug"] == "default"


@pytest.mark.asyncio
async def test_redirect_target_uses_most_recent(client):
    await client.post(
        "/api/v1/widgets/dashboards",
        json={"slug": "home", "name": "Home"},
        headers=AUTH_HEADERS,
    )
    # Touch 'home' by viewing it
    await client.get("/api/v1/widgets/dashboard?slug=home", headers=AUTH_HEADERS)
    r = await client.get(
        "/api/v1/widgets/dashboards/redirect-target", headers=AUTH_HEADERS,
    )
    assert r.json()["slug"] == "home"
