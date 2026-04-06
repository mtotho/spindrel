"""Integration tests for tool policy rules and approvals API."""
import uuid

import pytest

from app.config import settings
from app.services.tool_policies import invalidate_cache

AUTH_HEADERS = {"Authorization": "Bearer test-key"}


@pytest.fixture(autouse=True)
def clear_policy_cache():
    """Ensure policy cache is fresh for each test."""
    invalidate_cache()
    yield
    invalidate_cache()


@pytest.fixture(autouse=True)
def reset_policy_settings():
    """Save and restore policy settings so tests don't leak."""
    orig_action = settings.TOOL_POLICY_DEFAULT_ACTION
    orig_enabled = settings.TOOL_POLICY_ENABLED
    orig_tier_gating = settings.TOOL_POLICY_TIER_GATING
    yield
    settings.TOOL_POLICY_DEFAULT_ACTION = orig_action
    settings.TOOL_POLICY_ENABLED = orig_enabled
    settings.TOOL_POLICY_TIER_GATING = orig_tier_gating


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

    # Test: ls command should be gated by tier (exec_capable → require_approval)
    r = await client.post("/api/v1/tool-policies/test", json={
        "bot_id": "test-bot",
        "tool_name": "exec_command",
        "arguments": {"command": "ls -la"},
    }, headers=AUTH_HEADERS)
    assert r.status_code == 200
    # exec_command is exec_capable, tier gating returns require_approval before global default
    assert r.json()["action"] == "require_approval"
    assert r.json()["tier"] == "exec_capable"


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


# ---------------------------------------------------------------------------
# Policy settings endpoints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_policy_settings(client):
    """GET /settings should return current default_action and enabled."""
    r = await client.get("/api/v1/tool-policies/settings", headers=AUTH_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert "default_action" in data
    assert "enabled" in data
    assert isinstance(data["enabled"], bool)
    assert "tier_gating" in data
    assert isinstance(data["tier_gating"], bool)


@pytest.mark.asyncio
async def test_update_policy_settings_default_action(client):
    """PUT /settings should update default_action."""
    # Set to allow
    r = await client.put("/api/v1/tool-policies/settings", json={
        "default_action": "allow",
    }, headers=AUTH_HEADERS)
    assert r.status_code == 200
    assert r.json()["default_action"] == "allow"

    # Verify GET reflects the change
    r = await client.get("/api/v1/tool-policies/settings", headers=AUTH_HEADERS)
    assert r.json()["default_action"] == "allow"


@pytest.mark.asyncio
async def test_update_policy_settings_require_approval(client):
    """PUT /settings should accept require_approval as default_action."""
    r = await client.put("/api/v1/tool-policies/settings", json={
        "default_action": "require_approval",
    }, headers=AUTH_HEADERS)
    assert r.status_code == 200
    assert r.json()["default_action"] == "require_approval"

    # Verify the test endpoint uses it — unmatched tool should get require_approval
    r = await client.post("/api/v1/tool-policies/test", json={
        "bot_id": "any-bot",
        "tool_name": "some_unmatched_tool",
        "arguments": {},
    }, headers=AUTH_HEADERS)
    assert r.status_code == 200
    assert r.json()["action"] == "require_approval"


@pytest.mark.asyncio
async def test_update_policy_settings_enabled_toggle(client):
    """PUT /settings should toggle enabled state."""
    r = await client.put("/api/v1/tool-policies/settings", json={
        "enabled": False,
    }, headers=AUTH_HEADERS)
    assert r.status_code == 200
    assert r.json()["enabled"] is False

    r = await client.put("/api/v1/tool-policies/settings", json={
        "enabled": True,
    }, headers=AUTH_HEADERS)
    assert r.status_code == 200
    assert r.json()["enabled"] is True


@pytest.mark.asyncio
async def test_update_policy_settings_invalid_action(client):
    """PUT /settings should reject invalid default_action values."""
    r = await client.put("/api/v1/tool-policies/settings", json={
        "default_action": "invalid_garbage",
    }, headers=AUTH_HEADERS)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Approval suggestions + decide-with-rule
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approval_suggestions(client, db_session):
    """GET /approvals/{id}/suggestions should return smart suggestions."""
    from app.db.models import ToolApproval
    approval = ToolApproval(
        bot_id="test-bot",
        tool_name="exec_command",
        tool_type="local",
        arguments={"command": "ls /home/user"},
        status="pending",
        timeout_seconds=300,
    )
    db_session.add(approval)
    await db_session.commit()
    await db_session.refresh(approval)

    r = await client.get(f"/api/v1/approvals/{approval.id}/suggestions", headers=AUTH_HEADERS)
    assert r.status_code == 200
    suggestions = r.json()
    assert len(suggestions) >= 2  # at least a prefix match + tool-always
    labels = [s["label"] for s in suggestions]
    assert any("ls" in l for l in labels), f"Expected ls suggestion in {labels}"
    assert any("exec_command" in l for l in labels)


@pytest.mark.asyncio
async def test_decide_with_rule_creates_policy(client, db_session):
    """POST /approvals/{id}/decide with create_rule should approve + create an allow rule."""
    from app.db.models import ToolApproval
    approval = ToolApproval(
        bot_id="rule-bot",
        tool_name="exec_command",
        tool_type="local",
        arguments={"command": "cat /etc/hostname"},
        status="pending",
        timeout_seconds=300,
    )
    db_session.add(approval)
    await db_session.commit()
    await db_session.refresh(approval)

    r = await client.post(f"/api/v1/approvals/{approval.id}/decide", json={
        "approved": True,
        "decided_by": "test:admin",
        "create_rule": {
            "tool_name": "exec_command",
            "conditions": {"arguments": {"command": {"pattern": "^cat(\\s|$)"}}},
        },
    }, headers=AUTH_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "approved"
    assert data["rule_created"] is not None

    # Verify the rule was actually created
    r2 = await client.get("/api/v1/tool-policies", headers=AUTH_HEADERS)
    rules = r2.json()
    created_rule = next((r for r in rules if r["id"] == data["rule_created"]), None)
    assert created_rule is not None
    assert created_rule["action"] == "allow"
    assert created_rule["bot_id"] == "rule-bot"
    assert "cat" in str(created_rule["conditions"])
