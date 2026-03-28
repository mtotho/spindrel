"""Integration tests for tool policy rules and approvals API."""
import uuid

import pytest

from app.services.tool_policies import invalidate_cache

AUTH_HEADERS = {"Authorization": "Bearer test-key"}


@pytest.fixture(autouse=True)
def clear_policy_cache():
    """Ensure policy cache is fresh for each test."""
    invalidate_cache()
    yield
    invalidate_cache()


@pytest.mark.asyncio
async def test_policy_crud_lifecycle(client):
    """Create, list, update, delete a policy rule."""
    # Create
    r = await client.post("/api/v1/tool-policies", json={
        "tool_name": "exec_command",
        "action": "deny",
        "conditions": {"arguments": {"command": {"pattern": "^rm "}}},
        "priority": 10,
        "reason": "Destructive command",
    }, headers=AUTH_HEADERS)
    assert r.status_code == 201
    rule = r.json()
    rule_id = rule["id"]
    assert rule["tool_name"] == "exec_command"
    assert rule["action"] == "deny"
    assert rule["priority"] == 10

    # List
    r = await client.get("/api/v1/tool-policies", headers=AUTH_HEADERS)
    assert r.status_code == 200
    rules = r.json()
    assert any(r["id"] == rule_id for r in rules)

    # List with filter
    r = await client.get("/api/v1/tool-policies?tool_name=exec_command", headers=AUTH_HEADERS)
    assert r.status_code == 200
    assert all(r["tool_name"] == "exec_command" for r in r.json())

    # Update
    r = await client.put(f"/api/v1/tool-policies/{rule_id}", json={
        "action": "require_approval",
        "reason": "Needs approval for rm",
    }, headers=AUTH_HEADERS)
    assert r.status_code == 200
    assert r.json()["action"] == "require_approval"
    assert r.json()["reason"] == "Needs approval for rm"

    # Delete
    r = await client.delete(f"/api/v1/tool-policies/{rule_id}", headers=AUTH_HEADERS)
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_policy_validation(client):
    """Invalid action should be rejected."""
    r = await client.post("/api/v1/tool-policies", json={
        "tool_name": "exec_command",
        "action": "invalid_action",
    }, headers=AUTH_HEADERS)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_policy_test_endpoint(client):
    """The /test endpoint should evaluate rules and return the decision."""
    # Create a deny rule for rm commands
    r = await client.post("/api/v1/tool-policies", json={
        "tool_name": "exec_command",
        "action": "deny",
        "conditions": {"arguments": {"command": {"pattern": "^rm "}}},
        "priority": 10,
        "reason": "No rm allowed",
    }, headers=AUTH_HEADERS)
    assert r.status_code == 201

    # Test: rm command should be denied
    r = await client.post("/api/v1/tool-policies/test", json={
        "bot_id": "test-bot",
        "tool_name": "exec_command",
        "arguments": {"command": "rm -rf /tmp"},
    }, headers=AUTH_HEADERS)
    assert r.status_code == 200
    assert r.json()["action"] == "deny"
    assert r.json()["reason"] == "No rm allowed"

    # Test: ls command should fall through to default action (deny by default)
    r = await client.post("/api/v1/tool-policies/test", json={
        "bot_id": "test-bot",
        "tool_name": "exec_command",
        "arguments": {"command": "ls -la"},
    }, headers=AUTH_HEADERS)
    assert r.status_code == 200
    assert r.json()["action"] == "deny"  # default is deny when no rule matches


@pytest.mark.asyncio
async def test_policy_bot_specific_over_global(client):
    """Bot-specific rules should take precedence over global at same priority."""
    # Global allow
    r = await client.post("/api/v1/tool-policies", json={
        "tool_name": "exec_command",
        "action": "allow",
        "priority": 10,
    }, headers=AUTH_HEADERS)
    assert r.status_code == 201

    # Bot-specific deny
    r = await client.post("/api/v1/tool-policies", json={
        "bot_id": "restricted-bot",
        "tool_name": "exec_command",
        "action": "deny",
        "priority": 10,
        "reason": "Bot restricted",
    }, headers=AUTH_HEADERS)
    assert r.status_code == 201

    # restricted-bot should be denied (bot-specific wins)
    r = await client.post("/api/v1/tool-policies/test", json={
        "bot_id": "restricted-bot",
        "tool_name": "exec_command",
        "arguments": {},
    }, headers=AUTH_HEADERS)
    assert r.status_code == 200
    assert r.json()["action"] == "deny"


@pytest.mark.asyncio
async def test_policy_not_found(client):
    """Non-existent rule should return 404."""
    r = await client.put(f"/api/v1/tool-policies/{uuid.uuid4()}", json={
        "action": "allow",
    }, headers=AUTH_HEADERS)
    assert r.status_code == 404

    r = await client.delete(f"/api/v1/tool-policies/{uuid.uuid4()}", headers=AUTH_HEADERS)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_approvals_list_empty(client):
    """Approvals list should return empty when no approvals exist."""
    r = await client.get("/api/v1/approvals", headers=AUTH_HEADERS)
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_approval_not_found(client):
    r = await client.get(f"/api/v1/approvals/{uuid.uuid4()}", headers=AUTH_HEADERS)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_approval_decide_not_found(client):
    r = await client.post(f"/api/v1/approvals/{uuid.uuid4()}/decide", json={
        "approved": True,
        "decided_by": "test",
    }, headers=AUTH_HEADERS)
    assert r.status_code == 404
