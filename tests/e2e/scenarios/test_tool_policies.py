"""Tool policies, tool calls, and approvals endpoint tests — deterministic API contract.

Tests CRUD lifecycle for policy rules (creates own resources, cleans up in finally).
Read-only tests for tool call history, stats, and approvals. No LLM dependency.
"""

from __future__ import annotations

import pytest

from ..harness.client import E2EClient


# ---------------------------------------------------------------------------
# Policy settings (read-only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policy_settings_shape(client: E2EClient) -> None:
    """GET /tool-policies/settings returns default_action, enabled, tier_gating."""
    resp = await client.get("/api/v1/tool-policies/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "default_action" in data
    assert data["default_action"] in ("allow", "deny", "require_approval")
    assert "enabled" in data
    assert isinstance(data["enabled"], bool)
    assert "tier_gating" in data
    assert isinstance(data["tier_gating"], bool)


# ---------------------------------------------------------------------------
# Policy rules CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policy_rule_crud_lifecycle(client: E2EClient) -> None:
    """Create → list → update → delete a policy rule."""
    rule_id = None
    try:
        # Create
        resp = await client.post("/api/v1/tool-policies", json={
            "tool_name": "e2e_test_tool",
            "action": "deny",
            "reason": "E2E test rule",
            "priority": 999,
        })
        assert resp.status_code == 201
        rule = resp.json()
        rule_id = rule["id"]
        assert rule["tool_name"] == "e2e_test_tool"
        assert rule["action"] == "deny"
        assert rule["reason"] == "E2E test rule"
        assert rule["priority"] == 999
        assert rule["enabled"] is True

        # List — should include our rule
        resp = await client.get("/api/v1/tool-policies", params={"tool_name": "e2e_test_tool"})
        assert resp.status_code == 200
        rules = resp.json()
        assert any(r["id"] == rule_id for r in rules)

        # Update
        resp = await client.put(f"/api/v1/tool-policies/{rule_id}", json={
            "action": "allow",
            "reason": "E2E updated",
        })
        assert resp.status_code == 200
        updated = resp.json()
        assert updated["action"] == "allow"
        assert updated["reason"] == "E2E updated"

        # Delete
        resp = await client.delete(f"/api/v1/tool-policies/{rule_id}")
        assert resp.status_code == 204
        rule_id = None  # Already cleaned up

    finally:
        if rule_id:
            await client.delete(f"/api/v1/tool-policies/{rule_id}")


@pytest.mark.asyncio
async def test_policy_rule_invalid_action_422(client: E2EClient) -> None:
    """Creating a rule with invalid action returns 422."""
    resp = await client.post("/api/v1/tool-policies", json={
        "tool_name": "e2e_test_tool",
        "action": "invalid_action",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_policy_rule_delete_nonexistent_404(client: E2EClient) -> None:
    """Deleting a nonexistent rule returns 404."""
    resp = await client.delete("/api/v1/tool-policies/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_policy_rule_update_nonexistent_404(client: E2EClient) -> None:
    """Updating a nonexistent rule returns 404."""
    resp = await client.put(
        "/api/v1/tool-policies/00000000-0000-0000-0000-000000000000",
        json={"action": "allow"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_policy_rule_bot_scoped(client: E2EClient) -> None:
    """Rules can be scoped to a specific bot_id."""
    rule_id = None
    try:
        resp = await client.post("/api/v1/tool-policies", json={
            "tool_name": "e2e_scoped_tool",
            "action": "require_approval",
            "bot_id": client.default_bot_id,
            "reason": "E2E bot-scoped rule",
        })
        assert resp.status_code == 201
        rule = resp.json()
        rule_id = rule["id"]
        assert rule["bot_id"] == client.default_bot_id

        # Filter by bot_id
        resp = await client.get("/api/v1/tool-policies", params={"bot_id": client.default_bot_id})
        assert resp.status_code == 200
        assert any(r["id"] == rule_id for r in resp.json())

    finally:
        if rule_id:
            await client.delete(f"/api/v1/tool-policies/{rule_id}")


# ---------------------------------------------------------------------------
# Policy test (dry-run)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policy_test_dry_run(client: E2EClient) -> None:
    """POST /tool-policies/test returns a policy decision."""
    resp = await client.post("/api/v1/tool-policies/test", json={
        "bot_id": client.default_bot_id,
        "tool_name": "get_current_time",
        "arguments": {},
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "action" in data
    assert data["action"] in ("allow", "deny", "require_approval")
    assert "timeout" in data


@pytest.mark.asyncio
async def test_policy_test_with_custom_rule(client: E2EClient) -> None:
    """Dry-run reflects a custom deny rule we create."""
    rule_id = None
    try:
        # Create deny rule
        resp = await client.post("/api/v1/tool-policies", json={
            "tool_name": "e2e_deny_target",
            "action": "deny",
            "bot_id": client.default_bot_id,
            "reason": "E2E deny test",
        })
        assert resp.status_code == 201
        rule_id = resp.json()["id"]

        # Test should return deny
        resp = await client.post("/api/v1/tool-policies/test", json={
            "bot_id": client.default_bot_id,
            "tool_name": "e2e_deny_target",
            "arguments": {},
        })
        assert resp.status_code == 200
        assert resp.json()["action"] == "deny"

    finally:
        if rule_id:
            await client.delete(f"/api/v1/tool-policies/{rule_id}")


# ---------------------------------------------------------------------------
# Tool call history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_calls_list_shape(client: E2EClient) -> None:
    """GET /tool-calls returns list with expected fields."""
    resp = await client.get("/api/v1/tool-calls", params={"limit": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if data:
        call = data[0]
        for key in ("id", "tool_name", "tool_type", "arguments", "created_at"):
            assert key in call, f"Missing tool call key: {key}"


@pytest.mark.asyncio
async def test_tool_calls_filter_by_bot(client: E2EClient) -> None:
    """GET /tool-calls?bot_id=... filters correctly."""
    resp = await client.get(
        "/api/v1/tool-calls",
        params={"bot_id": client.default_bot_id, "limit": 5},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    for call in data:
        assert call["bot_id"] == client.default_bot_id


@pytest.mark.asyncio
async def test_tool_calls_stats_shape(client: E2EClient) -> None:
    """GET /tool-calls/stats returns grouped statistics."""
    resp = await client.get("/api/v1/tool-calls/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "group_by" in data
    assert data["group_by"] == "tool_name"
    assert "stats" in data
    assert isinstance(data["stats"], list)
    if data["stats"]:
        stat = data["stats"][0]
        for key in ("key", "count", "total_duration_ms", "avg_duration_ms", "error_count"):
            assert key in stat, f"Missing stat key: {key}"


@pytest.mark.asyncio
async def test_tool_calls_stats_group_by_bot(client: E2EClient) -> None:
    """GET /tool-calls/stats?group_by=bot_id groups by bot."""
    resp = await client.get("/api/v1/tool-calls/stats", params={"group_by": "bot_id"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["group_by"] == "bot_id"


@pytest.mark.asyncio
async def test_tool_call_nonexistent_404(client: E2EClient) -> None:
    """GET /tool-calls/{id} for nonexistent ID returns 404."""
    resp = await client.get("/api/v1/tool-calls/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approvals_list_shape(client: E2EClient) -> None:
    """GET /approvals returns list with expected fields."""
    resp = await client.get("/api/v1/approvals", params={"limit": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if data:
        approval = data[0]
        for key in ("id", "bot_id", "tool_name", "status", "created_at"):
            assert key in approval, f"Missing approval key: {key}"


@pytest.mark.asyncio
async def test_approvals_filter_by_status(client: E2EClient) -> None:
    """GET /approvals?status=pending filters correctly."""
    resp = await client.get("/api/v1/approvals", params={"status": "pending"})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    for approval in data:
        assert approval["status"] == "pending"


@pytest.mark.asyncio
async def test_approval_nonexistent_404(client: E2EClient) -> None:
    """GET /approvals/{id} for nonexistent ID returns 404."""
    resp = await client.get("/api/v1/approvals/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
