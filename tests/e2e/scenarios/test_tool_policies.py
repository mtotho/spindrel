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
async def test_tool_calls_list_nonempty(client: E2EClient) -> None:
    """GET /tool-calls returns non-empty list (E2E tests generate tool calls)."""
    resp = await client.get("/api/v1/tool-calls", params={"limit": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0, "Expected tool call history — E2E runs should generate calls"
    call = data[0]
    for key in ("id", "tool_name", "tool_type", "arguments", "created_at"):
        assert key in call, f"Missing tool call key: {key}"
    assert isinstance(call["arguments"], dict)


@pytest.mark.asyncio
async def test_tool_calls_filter_by_bot(client: E2EClient) -> None:
    """GET /tool-calls?bot_id=... filters correctly and returns only that bot."""
    resp = await client.get(
        "/api/v1/tool-calls",
        params={"bot_id": client.default_bot_id, "limit": 10},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0, (
        f"Expected tool calls for bot {client.default_bot_id} — "
        "memory/file tests should have generated some"
    )
    for call in data:
        assert call["bot_id"] == client.default_bot_id


@pytest.mark.asyncio
async def test_tool_calls_stats_nonempty(client: E2EClient) -> None:
    """GET /tool-calls/stats returns non-empty statistics with valid values."""
    resp = await client.get("/api/v1/tool-calls/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["group_by"] == "tool_name"
    assert isinstance(data["stats"], list)
    assert len(data["stats"]) > 0, "Expected tool call stats — calls exist"
    stat = data["stats"][0]
    for key in ("key", "count", "total_duration_ms", "avg_duration_ms", "error_count"):
        assert key in stat, f"Missing stat key: {key}"
    assert stat["count"] > 0


@pytest.mark.asyncio
async def test_tool_calls_stats_group_by_bot(client: E2EClient) -> None:
    """GET /tool-calls/stats?group_by=bot_id groups by bot and returns data."""
    resp = await client.get("/api/v1/tool-calls/stats", params={"group_by": "bot_id"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["group_by"] == "bot_id"
    assert len(data["stats"]) > 0, "Expected stats grouped by bot_id"


@pytest.mark.asyncio
async def test_tool_calls_stats_group_by_type(client: E2EClient) -> None:
    """GET /tool-calls/stats?group_by=tool_type groups by type."""
    resp = await client.get("/api/v1/tool-calls/stats", params={"group_by": "tool_type"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["group_by"] == "tool_type"
    types = {s["key"] for s in data["stats"]}
    assert "local" in types, f"Expected 'local' tool type in stats but got: {types}"


@pytest.mark.asyncio
async def test_tool_call_detail_by_id(client: E2EClient) -> None:
    """Fetching a real tool call by ID returns full detail."""
    # Get a real tool call ID first
    list_resp = await client.get("/api/v1/tool-calls", params={"limit": 1})
    assert list_resp.status_code == 200
    calls = list_resp.json()
    assert len(calls) > 0
    call_id = calls[0]["id"]

    # Fetch detail
    resp = await client.get(f"/api/v1/tool-calls/{call_id}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["id"] == call_id
    assert "tool_name" in detail
    assert "arguments" in detail


@pytest.mark.asyncio
async def test_tool_call_nonexistent_404(client: E2EClient) -> None:
    """GET /tool-calls/{id} for nonexistent ID returns 404."""
    resp = await client.get("/api/v1/tool-calls/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approvals_list_has_data(client: E2EClient) -> None:
    """GET /approvals returns list with expected fields (may be non-empty from prior runs)."""
    resp = await client.get("/api/v1/approvals", params={"limit": 10})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if data:
        approval = data[0]
        for key in ("id", "bot_id", "tool_name", "status", "created_at",
                     "tool_type", "arguments", "timeout_seconds"):
            assert key in approval, f"Missing approval key: {key}"
        assert approval["status"] in ("pending", "approved", "denied", "expired")


@pytest.mark.asyncio
async def test_approvals_filter_by_status(client: E2EClient) -> None:
    """GET /approvals?status=approved filters correctly (if any exist)."""
    resp = await client.get("/api/v1/approvals", params={"status": "approved", "limit": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    for approval in data:
        assert approval["status"] == "approved"


@pytest.mark.asyncio
async def test_approval_nonexistent_404(client: E2EClient) -> None:
    """GET /approvals/{id} for nonexistent ID returns 404."""
    resp = await client.get("/api/v1/approvals/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Policy rules — existing rules on server
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policy_rules_list_existing(client: E2EClient) -> None:
    """GET /tool-policies returns existing rules (server should have some configured)."""
    resp = await client.get("/api/v1/tool-policies")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0, "Expected at least one policy rule configured on the server"
    rule = data[0]
    for key in ("id", "tool_name", "action", "priority", "enabled"):
        assert key in rule, f"Missing rule key: {key}"
