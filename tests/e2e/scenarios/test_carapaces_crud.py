"""Carapaces (capabilities) CRUD tests — deterministic, no LLM dependency.

All tests create e2e-prefixed carapaces and clean up in finally blocks.
No existing carapaces are modified or deleted.
"""

from __future__ import annotations

import uuid

import pytest

from ..harness.client import E2EClient

_TEST_PREFIX = "e2e-carapace-"
_ADMIN = "/api/v1/admin/carapaces"


def _test_carapace_id() -> str:
    return f"{_TEST_PREFIX}{uuid.uuid4().hex[:8]}"


def _carapace_payload(carapace_id: str, **overrides) -> dict:
    """Build a minimal carapace create payload."""
    base = {
        "id": carapace_id,
        "name": f"E2E Test ({carapace_id})",
        "description": "Created by E2E tests — safe to delete",
        "local_tools": ["get_current_time"],
        "tags": ["e2e-testing"],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# CRUD lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_carapace_create_and_get(client: E2EClient) -> None:
    """POST creates a carapace, GET returns matching fields."""
    cid = _test_carapace_id()
    try:
        resp = await client.post(_ADMIN, json=_carapace_payload(cid))
        assert resp.status_code == 201
        created = resp.json()
        assert created["id"] == cid
        assert created["name"] == f"E2E Test ({cid})"
        assert "get_current_time" in created["local_tools"]
        assert "e2e-testing" in created["tags"]

        # GET should match
        resp = await client.get(f"{_ADMIN}/{cid}")
        assert resp.status_code == 200
        fetched = resp.json()
        assert fetched["id"] == cid
        assert fetched["name"] == created["name"]
    finally:
        await client.delete(f"{_ADMIN}/{cid}")


@pytest.mark.asyncio
async def test_carapace_list_includes_created(client: E2EClient) -> None:
    """List all carapaces includes the newly created one."""
    cid = _test_carapace_id()
    try:
        await client.post(_ADMIN, json=_carapace_payload(cid))

        resp = await client.get(_ADMIN)
        assert resp.status_code == 200
        ids = [c["id"] for c in resp.json()]
        assert cid in ids
    finally:
        await client.delete(f"{_ADMIN}/{cid}")


@pytest.mark.asyncio
async def test_carapace_update_fields(client: E2EClient) -> None:
    """PUT updates name/description, verified via GET."""
    cid = _test_carapace_id()
    try:
        await client.post(_ADMIN, json=_carapace_payload(cid))

        resp = await client.put(
            f"{_ADMIN}/{cid}",
            json={"name": "Updated E2E Name", "description": "Updated desc"},
        )
        assert resp.status_code == 200
        updated = resp.json()
        assert updated["name"] == "Updated E2E Name"
        assert updated["description"] == "Updated desc"

        # Verify persistence
        fetched = (await client.get(f"{_ADMIN}/{cid}")).json()
        assert fetched["name"] == "Updated E2E Name"
        assert fetched["description"] == "Updated desc"
    finally:
        await client.delete(f"{_ADMIN}/{cid}")


@pytest.mark.asyncio
async def test_carapace_delete(client: E2EClient) -> None:
    """DELETE removes carapace, GET returns 404."""
    cid = _test_carapace_id()
    await client.post(_ADMIN, json=_carapace_payload(cid))

    resp = await client.delete(f"{_ADMIN}/{cid}")
    assert resp.status_code == 200

    resp = await client.get(f"{_ADMIN}/{cid}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_carapace_partial_update_preserves(client: E2EClient) -> None:
    """PUT with only name doesn't wipe tools/tags."""
    cid = _test_carapace_id()
    try:
        await client.post(
            _ADMIN,
            json=_carapace_payload(cid, local_tools=["get_current_time", "get_current_local_time"]),
        )

        # Update only the name
        await client.put(f"{_ADMIN}/{cid}", json={"name": "Renamed"})

        fetched = (await client.get(f"{_ADMIN}/{cid}")).json()
        assert fetched["name"] == "Renamed"
        # Original tools and tags should be preserved
        assert "get_current_time" in fetched["local_tools"]
        assert "get_current_local_time" in fetched["local_tools"]
        assert "e2e-testing" in fetched["tags"]
    finally:
        await client.delete(f"{_ADMIN}/{cid}")


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_carapace_create_duplicate_409(client: E2EClient) -> None:
    """POST with duplicate ID returns 409."""
    cid = _test_carapace_id()
    try:
        resp = await client.post(_ADMIN, json=_carapace_payload(cid))
        assert resp.status_code == 201

        resp = await client.post(_ADMIN, json=_carapace_payload(cid))
        assert resp.status_code == 409
    finally:
        await client.delete(f"{_ADMIN}/{cid}")


@pytest.mark.asyncio
async def test_carapace_get_nonexistent_404(client: E2EClient) -> None:
    """GET with unknown ID returns 404."""
    resp = await client.get(f"{_ADMIN}/e2e-nonexistent-{uuid.uuid4().hex[:8]}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_carapace_delete_nonexistent_404(client: E2EClient) -> None:
    """DELETE with unknown ID returns 404."""
    resp = await client.delete(f"{_ADMIN}/e2e-nonexistent-{uuid.uuid4().hex[:8]}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_carapace_update_nonexistent_404(client: E2EClient) -> None:
    """PUT with unknown ID returns 404."""
    resp = await client.put(
        f"{_ADMIN}/e2e-nonexistent-{uuid.uuid4().hex[:8]}",
        json={"name": "Ghost"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Resolve / Usage / Export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_carapace_resolve(client: E2EClient) -> None:
    """GET .../resolve returns flattened capability preview."""
    cid = _test_carapace_id()
    try:
        await client.post(
            _ADMIN,
            json=_carapace_payload(cid, local_tools=["get_current_time"]),
        )

        resp = await client.get(f"{_ADMIN}/{cid}/resolve")
        assert resp.status_code == 200
        data = resp.json()
        assert "local_tools" in data
        assert "resolved_ids" in data
        assert cid in data["resolved_ids"]
    finally:
        await client.delete(f"{_ADMIN}/{cid}")


@pytest.mark.asyncio
async def test_carapace_usage_empty(client: E2EClient) -> None:
    """GET .../usage for a fresh carapace returns empty list."""
    cid = _test_carapace_id()
    try:
        await client.post(_ADMIN, json=_carapace_payload(cid))

        resp = await client.get(f"{_ADMIN}/{cid}/usage")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 0
    finally:
        await client.delete(f"{_ADMIN}/{cid}")


@pytest.mark.asyncio
async def test_carapace_usage_after_bot_assign(client: E2EClient) -> None:
    """Assigning carapace to a bot shows up in usage endpoint."""
    cid = _test_carapace_id()
    bot_id = f"e2e-cap-usage-{uuid.uuid4().hex[:8]}"
    try:
        # Create carapace
        await client.post(_ADMIN, json=_carapace_payload(cid))

        # Create bot, then assign carapace via PATCH (BotCreateIn lacks carapaces field)
        await client.create_bot({
            "id": bot_id,
            "name": "Carapace Usage Test Bot",
            "model": "gemini-2.5-flash",
        })
        await client.update_bot(bot_id, {"carapaces": [cid]})

        # Check usage
        resp = await client.get(f"{_ADMIN}/{cid}/usage")
        assert resp.status_code == 200
        data = resp.json()
        bot_ids = [item["id"] for item in data if item["type"] == "bot"]
        assert bot_id in bot_ids
    finally:
        await client.delete_bot(bot_id)
        await client.delete(f"{_ADMIN}/{cid}")


@pytest.mark.asyncio
async def test_carapace_export_yaml(client: E2EClient) -> None:
    """POST .../export returns YAML content."""
    cid = _test_carapace_id()
    try:
        await client.post(_ADMIN, json=_carapace_payload(cid))

        resp = await client.post(f"{_ADMIN}/{cid}/export")
        assert resp.status_code == 200
        assert "text/yaml" in resp.headers.get("content-type", "")
        # Body should contain the carapace ID
        assert cid in resp.text
    finally:
        await client.delete(f"{_ADMIN}/{cid}")


@pytest.mark.asyncio
async def test_carapace_out_fields_complete(client: E2EClient) -> None:
    """CarapaceOut includes all expected fields (regression guard)."""
    cid = _test_carapace_id()
    try:
        resp = await client.post(_ADMIN, json=_carapace_payload(cid))
        assert resp.status_code == 201
        data = resp.json()

        required_fields = [
            "id", "name", "description", "local_tools",
            "mcp_tools", "pinned_tools", "system_prompt_fragment",
            "includes", "delegates", "tags", "source_type",
            "created_at", "updated_at",
        ]
        for field in required_fields:
            assert field in data, f"CarapaceOut missing field: {field}"
    finally:
        await client.delete(f"{_ADMIN}/{cid}")
