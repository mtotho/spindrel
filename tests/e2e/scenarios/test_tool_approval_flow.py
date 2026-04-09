"""Tool dispatch + approval flow E2E tests — behavioral tests requiring LLM.

Tests the full lifecycle: policy rule → chat triggers approval → decide → tool proceeds.
All created rules are cleaned up in finally blocks. These tests use streaming to observe
the SSE event sequence (approval_request, approval_resolved, tool_result).

Concurrency note: chat_stream blocks until the stream completes. When an approval gate
fires, the stream pauses waiting for a decision. We run the stream in an asyncio task
and poll-then-decide from the main coroutine.
"""

from __future__ import annotations

import asyncio

import pytest

from ..harness.client import E2EClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _poll_pending_approval(
    client: E2EClient,
    bot_id: str,
    tool_name: str,
    timeout: float = 90,
    interval: float = 2,
) -> dict:
    """Poll GET /approvals until a pending approval for the given tool appears."""
    elapsed = 0.0
    while elapsed < timeout:
        resp = await client.get(
            "/api/v1/approvals",
            params={"bot_id": bot_id, "status": "pending", "limit": 10},
        )
        if resp.status_code == 200:
            for approval in resp.json():
                if approval["tool_name"] == tool_name and approval["status"] == "pending":
                    return approval
        await asyncio.sleep(interval)
        elapsed += interval
    raise TimeoutError(f"No pending approval for {tool_name} within {timeout}s")


async def _create_require_approval_rule(
    client: E2EClient,
    tool_name: str,
    bot_id: str | None = None,
    priority: int = 1,
) -> str:
    """Create a require_approval rule and return its ID."""
    resp = await client.post("/api/v1/tool-policies", json={
        "tool_name": tool_name,
        "action": "require_approval",
        "bot_id": bot_id,
        "priority": priority,
        "reason": "E2E approval flow test",
        "approval_timeout": 120,
    })
    assert resp.status_code == 201, f"Failed to create rule: {resp.text}"
    return resp.json()["id"]


async def _cleanup_rule(client: E2EClient, rule_id: str | None) -> None:
    """Delete a rule if it exists, ignoring 404."""
    if rule_id:
        resp = await client.delete(f"/api/v1/tool-policies/{rule_id}")
        assert resp.status_code in (204, 404)


# ---------------------------------------------------------------------------
# 1. Full approval lifecycle — approve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approval_flow_approve(client: E2EClient) -> None:
    """Create require_approval rule → chat → approval_request event → approve → tool runs."""
    rule_id = None
    try:
        rule_id = await _create_require_approval_rule(
            client, "get_current_time", bot_id=client.default_bot_id,
        )

        # Verify via dry-run
        dry = await client.post("/api/v1/tool-policies/test", json={
            "bot_id": client.default_bot_id,
            "tool_name": "get_current_time",
            "arguments": {},
        })
        assert dry.json()["action"] == "require_approval"

        cid = client.new_client_id()

        # Run stream in background — it will block at the approval gate
        stream_task = asyncio.create_task(
            client.chat_stream(
                "Call the get_current_time tool right now and tell me what time it is.",
                client_id=cid,
            )
        )

        # Poll for the pending approval
        approval = await _poll_pending_approval(
            client, client.default_bot_id, "get_current_time",
        )
        approval_id = approval["id"]
        assert approval["tool_name"] == "get_current_time"
        assert approval["bot_id"] == client.default_bot_id

        # Approve it
        decide_resp = await client.post(
            f"/api/v1/approvals/{approval_id}/decide",
            json={"approved": True, "decided_by": "e2e_test"},
        )
        assert decide_resp.status_code == 200
        assert decide_resp.json()["status"] == "approved"

        # Stream should now complete
        result = await asyncio.wait_for(stream_task, timeout=90)

        # Verify event sequence
        types = result.event_types
        assert "approval_request" in types, f"Expected approval_request in {types}"
        assert "approval_resolved" in types, f"Expected approval_resolved in {types}"

        # Verify the approval_resolved has verdict=approved
        resolved = [e for e in result.events if e.type == "approval_resolved"]
        assert len(resolved) >= 1
        assert resolved[0].data["verdict"] == "approved"

        # Tool should have run after approval
        assert "get_current_time" in result.tools_used

    finally:
        await _cleanup_rule(client, rule_id)


# ---------------------------------------------------------------------------
# 2. Approval flow — deny
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approval_flow_deny(client: E2EClient) -> None:
    """Deny an approval → tool does not run, bot explains denial."""
    rule_id = None
    try:
        rule_id = await _create_require_approval_rule(
            client, "get_current_time", bot_id=client.default_bot_id,
        )

        cid = client.new_client_id()
        stream_task = asyncio.create_task(
            client.chat_stream(
                "Call the get_current_time tool right now and tell me what time it is.",
                client_id=cid,
            )
        )

        approval = await _poll_pending_approval(
            client, client.default_bot_id, "get_current_time",
        )

        # Deny it
        decide_resp = await client.post(
            f"/api/v1/approvals/{approval['id']}/decide",
            json={"approved": False, "decided_by": "e2e_test"},
        )
        assert decide_resp.status_code == 200
        assert decide_resp.json()["status"] == "denied"

        result = await asyncio.wait_for(stream_task, timeout=90)

        # Verify denial events
        resolved = [e for e in result.events if e.type == "approval_resolved"]
        assert len(resolved) >= 1
        assert resolved[0].data["verdict"] == "denied"

        # Bot should still produce a response (explaining the denial)
        assert result.response_text, "Expected bot to respond after denial"

    finally:
        await _cleanup_rule(client, rule_id)


# ---------------------------------------------------------------------------
# 3. Pending approval visible in list API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_approval_in_list_api(client: E2EClient) -> None:
    """Pending approval appears in GET /approvals with correct fields."""
    rule_id = None
    try:
        rule_id = await _create_require_approval_rule(
            client, "get_current_time", bot_id=client.default_bot_id,
        )

        cid = client.new_client_id()
        stream_task = asyncio.create_task(
            client.chat_stream(
                "Call the get_current_time tool right now and tell me what time it is.",
                client_id=cid,
            )
        )

        approval = await _poll_pending_approval(
            client, client.default_bot_id, "get_current_time",
        )

        # Verify shape
        assert approval["status"] == "pending"
        assert approval["tool_name"] == "get_current_time"
        assert approval["bot_id"] == client.default_bot_id
        assert "arguments" in approval
        assert isinstance(approval["arguments"], dict)
        assert "timeout_seconds" in approval
        assert approval["timeout_seconds"] > 0

        # Clean up: approve so the stream completes
        await client.post(
            f"/api/v1/approvals/{approval['id']}/decide",
            json={"approved": True, "decided_by": "e2e_test"},
        )
        await asyncio.wait_for(stream_task, timeout=90)

    finally:
        await _cleanup_rule(client, rule_id)


# ---------------------------------------------------------------------------
# 4. Approval suggestions endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approval_suggestions_shape(client: E2EClient) -> None:
    """GET /approvals/{id}/suggestions returns a list (may be empty)."""
    rule_id = None
    try:
        rule_id = await _create_require_approval_rule(
            client, "get_current_time", bot_id=client.default_bot_id,
        )

        cid = client.new_client_id()
        stream_task = asyncio.create_task(
            client.chat_stream(
                "Call the get_current_time tool right now and tell me what time it is.",
                client_id=cid,
            )
        )

        approval = await _poll_pending_approval(
            client, client.default_bot_id, "get_current_time",
        )

        # Get suggestions
        resp = await client.get(f"/api/v1/approvals/{approval['id']}/suggestions")
        assert resp.status_code == 200
        suggestions = resp.json()
        assert isinstance(suggestions, list)

        # Clean up
        await client.post(
            f"/api/v1/approvals/{approval['id']}/decide",
            json={"approved": True, "decided_by": "e2e_test"},
        )
        await asyncio.wait_for(stream_task, timeout=90)

    finally:
        await _cleanup_rule(client, rule_id)


# ---------------------------------------------------------------------------
# 5. Double-decide is 409
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_double_decide_409(client: E2EClient) -> None:
    """Deciding an already-decided approval returns 409 Conflict."""
    rule_id = None
    try:
        rule_id = await _create_require_approval_rule(
            client, "get_current_time", bot_id=client.default_bot_id,
        )

        cid = client.new_client_id()
        stream_task = asyncio.create_task(
            client.chat_stream(
                "Call the get_current_time tool right now and tell me what time it is.",
                client_id=cid,
            )
        )

        approval = await _poll_pending_approval(
            client, client.default_bot_id, "get_current_time",
        )
        approval_id = approval["id"]

        # First decide — approve
        resp1 = await client.post(
            f"/api/v1/approvals/{approval_id}/decide",
            json={"approved": True, "decided_by": "e2e_test"},
        )
        assert resp1.status_code == 200

        # Second decide — should be 409
        resp2 = await client.post(
            f"/api/v1/approvals/{approval_id}/decide",
            json={"approved": False, "decided_by": "e2e_test"},
        )
        assert resp2.status_code == 409

        await asyncio.wait_for(stream_task, timeout=90)

    finally:
        await _cleanup_rule(client, rule_id)


# ---------------------------------------------------------------------------
# 6. Deny rule blocks tool entirely (no approval, just denied)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deny_rule_blocks_tool(client: E2EClient) -> None:
    """A deny rule prevents tool use — no approval_request, tool result shows error."""
    rule_id = None
    try:
        resp = await client.post("/api/v1/tool-policies", json={
            "tool_name": "get_current_time",
            "action": "deny",
            "bot_id": client.default_bot_id,
            "priority": 1,
            "reason": "E2E deny test",
        })
        assert resp.status_code == 201
        rule_id = resp.json()["id"]

        cid = client.new_client_id()
        result = await client.chat_stream("What is the current time?", client_id=cid)

        # No approval_request should appear — tool is outright denied
        assert "approval_request" not in result.event_types, (
            f"Deny rule should not trigger approval, got: {result.event_types}"
        )

        # The bot should still respond (either explaining denial or answering without the tool)
        assert result.response_text, "Expected bot to respond even with denied tool"

    finally:
        await _cleanup_rule(client, rule_id)


# ---------------------------------------------------------------------------
# 7. Priority ordering — lower number wins
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_priority_ordering_lower_wins(client: E2EClient) -> None:
    """A lower-priority-number rule takes precedence over a higher one."""
    rule_allow_id = None
    rule_deny_id = None
    try:
        # Create allow rule at priority 100 (low precedence)
        resp = await client.post("/api/v1/tool-policies", json={
            "tool_name": "get_current_time",
            "action": "allow",
            "bot_id": client.default_bot_id,
            "priority": 100,
            "reason": "E2E allow (low priority)",
        })
        assert resp.status_code == 201
        rule_allow_id = resp.json()["id"]

        # Create deny rule at priority 1 (high precedence)
        resp = await client.post("/api/v1/tool-policies", json={
            "tool_name": "get_current_time",
            "action": "deny",
            "bot_id": client.default_bot_id,
            "priority": 1,
            "reason": "E2E deny (high priority)",
        })
        assert resp.status_code == 201
        rule_deny_id = resp.json()["id"]

        # Dry-run should reflect the deny rule (priority 1 beats priority 100)
        dry = await client.post("/api/v1/tool-policies/test", json={
            "bot_id": client.default_bot_id,
            "tool_name": "get_current_time",
            "arguments": {},
        })
        assert dry.status_code == 200
        assert dry.json()["action"] == "deny", (
            f"Expected deny (priority 1) to beat allow (priority 100), "
            f"got: {dry.json()}"
        )

    finally:
        await _cleanup_rule(client, rule_allow_id)
        await _cleanup_rule(client, rule_deny_id)


# ---------------------------------------------------------------------------
# 8. Approve with create_rule — auto-creates allow rule
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_with_create_rule(client: E2EClient) -> None:
    """Approving with create_rule flag auto-creates an allow rule for the tool."""
    rule_id = None
    auto_rule_id = None
    try:
        rule_id = await _create_require_approval_rule(
            client, "get_current_time", bot_id=client.default_bot_id,
        )

        cid = client.new_client_id()
        stream_task = asyncio.create_task(
            client.chat_stream(
                "Call the get_current_time tool right now and tell me what time it is.",
                client_id=cid,
            )
        )

        approval = await _poll_pending_approval(
            client, client.default_bot_id, "get_current_time",
        )

        # Approve and auto-create an allow rule
        decide_resp = await client.post(
            f"/api/v1/approvals/{approval['id']}/decide",
            json={
                "approved": True,
                "decided_by": "e2e_test",
                "create_rule": {
                    "tool_name": "get_current_time",
                    "scope": "bot",
                    "priority": 50,
                },
            },
        )
        assert decide_resp.status_code == 200
        body = decide_resp.json()
        assert body["status"] == "approved"
        auto_rule_id = body.get("rule_created")
        assert auto_rule_id, "Expected rule_created in response"

        await asyncio.wait_for(stream_task, timeout=90)

        # Verify the auto-created rule exists
        rule_resp = await client.get(f"/api/v1/tool-policies/{auto_rule_id}")
        assert rule_resp.status_code == 200
        auto_rule = rule_resp.json()
        assert auto_rule["tool_name"] == "get_current_time"
        assert auto_rule["action"] == "allow"

    finally:
        await _cleanup_rule(client, rule_id)
        await _cleanup_rule(client, auto_rule_id)
