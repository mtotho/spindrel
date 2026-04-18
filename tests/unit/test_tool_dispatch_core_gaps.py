"""Phase B.4 targeted sweep of tool_dispatch.py core gaps (#10).

Covers audit entry #10: dispatch_tool_call approval-tier + policy flow.
Behaviors exercised:
- Authorization (allowed_tool_names guard)
- Policy deny — early return, no tool execution, error JSON
- Policy exception → deny-by-default
- skip_policy=True bypasses _check_tool_policy entirely
- require_approval: needs_approval=True, approval_id/timeout propagated
- require_approval: tier prefix injected into approval_reason
- require_approval: result_for_llm is pending_approval JSON
- require_approval: tool_type (local/mcp) forwarded to _create_approval_record
- Capability activation approval (CAPABILITY_APPROVAL=required)
- MCP bare-name resolution (resolve_mcp_tool_name fallback)
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.tool_dispatch import dispatch_tool_call
from app.config import settings


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _policy_decision(action, *, reason="test reason", rule_id="rule-1", tier=None, timeout=300):
    d = MagicMock()
    d.action = action
    d.reason = reason
    d.rule_id = rule_id
    d.tier = tier
    d.timeout = timeout
    return d


@pytest.fixture
def dkw():
    """Minimal dispatch_tool_call kwargs — mirrors the timeout test fixture."""
    return dict(
        args="{}",
        tool_call_id="tc_1",
        bot_id="test-bot",
        bot_memory=None,
        session_id=uuid.uuid4(),
        client_id="test-client",
        correlation_id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        iteration=1,
        provider_id=None,
        summarize_enabled=False,
        summarize_threshold=10000,
        summarize_model="gpt-4",
        summarize_max_tokens=500,
        summarize_exclude=set(),
        compaction=False,
    )


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------

class TestAuthorizationCheck:
    @pytest.mark.asyncio
    async def test_when_tool_not_in_allowed_names_then_auth_error_no_execution(self, dkw):
        with patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock), \
             patch("app.agent.tool_dispatch.call_local_tool", new_callable=AsyncMock) as mock_call:
            result = await dispatch_tool_call(
                name="forbidden_tool",
                allowed_tool_names={"other_tool"},
                **dkw,
            )

        parsed = json.loads(result.result)
        assert "error" in parsed
        assert "not available" in parsed["error"]
        mock_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_tool_in_allowed_names_then_proceeds_to_execution(self, dkw):
        with patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch._check_tool_policy", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.tool_dispatch.call_local_tool", new_callable=AsyncMock, return_value='{"ok": true}'), \
             patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock):
            result = await dispatch_tool_call(
                name="allowed_tool",
                allowed_tool_names={"allowed_tool"},
                **dkw,
            )

        assert "error" not in json.loads(result.result)

    @pytest.mark.asyncio
    async def test_when_allowed_names_none_then_no_auth_check(self, dkw):
        with patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch._check_tool_policy", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.tool_dispatch.call_local_tool", new_callable=AsyncMock, return_value='{"value": 1}'), \
             patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock):
            result = await dispatch_tool_call(
                name="any_tool",
                allowed_tool_names=None,
                **dkw,
            )

        assert "error" not in json.loads(result.result)


# ---------------------------------------------------------------------------
# Policy deny
# ---------------------------------------------------------------------------

class TestPolicyDeny:
    @pytest.mark.asyncio
    async def test_when_policy_denies_then_error_json_and_no_execution(self, dkw):
        decision = _policy_decision("deny", reason="security violation")
        with patch("app.agent.tool_dispatch._check_tool_policy", new_callable=AsyncMock, return_value=decision), \
             patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch.call_local_tool", new_callable=AsyncMock) as mock_call, \
             patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock):
            result = await dispatch_tool_call(name="dangerous_tool", allowed_tool_names=None, **dkw)

        parsed = json.loads(result.result)
        assert "error" in parsed
        assert "security violation" in parsed["error"]
        mock_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_policy_returns_none_then_tool_executes(self, dkw):
        with patch("app.agent.tool_dispatch._check_tool_policy", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch.call_local_tool", new_callable=AsyncMock, return_value='{"value": 42}'), \
             patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock):
            result = await dispatch_tool_call(name="safe_tool", allowed_tool_names=None, **dkw)

        assert json.loads(result.result) == {"value": 42}

    @pytest.mark.asyncio
    async def test_when_policy_check_raises_then_deny_by_default(self, dkw):
        with patch("app.agent.tool_dispatch._check_tool_policy", new_callable=AsyncMock, side_effect=RuntimeError("db down")), \
             patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch.call_local_tool", new_callable=AsyncMock) as mock_call:
            result = await dispatch_tool_call(name="any_tool", allowed_tool_names=None, **dkw)

        parsed = json.loads(result.result)
        assert "error" in parsed
        assert "policy evaluation error" in parsed["error"]
        mock_call.assert_not_called()


# ---------------------------------------------------------------------------
# Policy require_approval
# ---------------------------------------------------------------------------

class TestPolicyRequireApproval:
    @pytest.mark.asyncio
    async def test_when_approval_required_then_needs_approval_and_execution_skipped(self, dkw):
        decision = _policy_decision("require_approval", reason="sensitive op", tier=None, timeout=300)
        with patch("app.agent.tool_dispatch._check_tool_policy", new_callable=AsyncMock, return_value=decision), \
             patch("app.agent.tool_dispatch._create_approval_record", new_callable=AsyncMock, return_value="appr-001"), \
             patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch.call_local_tool", new_callable=AsyncMock) as mock_call:
            result = await dispatch_tool_call(name="write_file", allowed_tool_names=None, **dkw)

        assert result.needs_approval is True
        assert result.approval_id == "appr-001"
        assert result.approval_timeout == 300
        mock_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_tier_set_then_reason_has_tier_prefix(self, dkw):
        decision = _policy_decision("require_approval", reason="exec access", tier="exec_capable")
        with patch("app.agent.tool_dispatch._check_tool_policy", new_callable=AsyncMock, return_value=decision), \
             patch("app.agent.tool_dispatch._create_approval_record", new_callable=AsyncMock, return_value="appr-002"), \
             patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False):
            result = await dispatch_tool_call(name="run_code", allowed_tool_names=None, **dkw)

        assert result.approval_reason == "[exec_capable] exec access"

    @pytest.mark.asyncio
    async def test_when_tier_none_then_reason_unchanged(self, dkw):
        decision = _policy_decision("require_approval", reason="plain reason", tier=None)
        with patch("app.agent.tool_dispatch._check_tool_policy", new_callable=AsyncMock, return_value=decision), \
             patch("app.agent.tool_dispatch._create_approval_record", new_callable=AsyncMock, return_value="appr-003"), \
             patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False):
            result = await dispatch_tool_call(name="read_file", allowed_tool_names=None, **dkw)

        assert result.approval_reason == "plain reason"

    @pytest.mark.asyncio
    async def test_when_approval_required_then_result_for_llm_is_pending_json(self, dkw):
        decision = _policy_decision("require_approval", reason="policy match")
        with patch("app.agent.tool_dispatch._check_tool_policy", new_callable=AsyncMock, return_value=decision), \
             patch("app.agent.tool_dispatch._create_approval_record", new_callable=AsyncMock, return_value="appr-004"), \
             patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False):
            result = await dispatch_tool_call(name="send_email", allowed_tool_names=None, **dkw)

        parsed = json.loads(result.result_for_llm)
        assert parsed["status"] == "pending_approval"
        assert "policy match" in parsed["reason"]

    @pytest.mark.asyncio
    async def test_when_skip_policy_true_then_policy_not_checked(self, dkw):
        with patch("app.agent.tool_dispatch._check_tool_policy", new_callable=AsyncMock) as mock_policy, \
             patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch.call_local_tool", new_callable=AsyncMock, return_value='{"ok": true}'), \
             patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock):
            await dispatch_tool_call(name="tool", allowed_tool_names=None, skip_policy=True, **dkw)

        mock_policy.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_mcp_tool_requires_approval_then_tool_type_is_mcp(self, dkw):
        """tool_type="mcp" (not "local") is forwarded to _create_approval_record."""
        decision = _policy_decision("require_approval", reason="mcp access")
        create_mock = AsyncMock(return_value="appr-005")
        with patch("app.agent.tool_dispatch._check_tool_policy", new_callable=AsyncMock, return_value=decision), \
             patch("app.agent.tool_dispatch._create_approval_record", create_mock), \
             patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=True):
            await dispatch_tool_call(name="firecrawl_search", allowed_tool_names=None, **dkw)

        assert create_mock.call_args.kwargs["tool_type"] == "mcp"


# ---------------------------------------------------------------------------
# MCP bare-name resolution
# ---------------------------------------------------------------------------

class TestMcpBareNameResolution:
    @pytest.mark.asyncio
    async def test_when_bare_mcp_name_resolved_then_resolved_name_dispatched(self, dkw):
        """Unknown 'search' → resolved to 'firecrawl-search' before dispatch."""
        with patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_mcp_tool", side_effect=lambda n: n == "firecrawl-search"), \
             patch("app.agent.tool_dispatch.resolve_mcp_tool_name", return_value="firecrawl-search"), \
             patch("app.agent.tool_dispatch.get_mcp_server_for_tool", return_value="firecrawl"), \
             patch("app.agent.tool_dispatch.call_mcp_tool", new_callable=AsyncMock, return_value='{"result": "found"}'), \
             patch("app.agent.tool_dispatch._check_tool_policy", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock):
            result = await dispatch_tool_call(name="search", allowed_tool_names=None, **dkw)

        assert "error" not in json.loads(result.result)

    @pytest.mark.asyncio
    async def test_when_no_resolution_then_unknown_tool_error(self, dkw):
        with patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch.resolve_mcp_tool_name", return_value=None), \
             patch("app.agent.tool_dispatch._check_tool_policy", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock):
            result = await dispatch_tool_call(name="mystery_tool", allowed_tool_names=None, **dkw)

        parsed = json.loads(result.result)
        assert "error" in parsed
        assert "mystery_tool" in parsed["error"]

    @pytest.mark.asyncio
    async def test_when_resolution_returns_same_name_then_still_unknown(self, dkw):
        """resolve_mcp_tool_name returning the same name does not reroute."""
        with patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch.resolve_mcp_tool_name", return_value="mystery_tool"), \
             patch("app.agent.tool_dispatch._check_tool_policy", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock):
            result = await dispatch_tool_call(name="mystery_tool", allowed_tool_names=None, **dkw)

        parsed = json.loads(result.result)
        assert "error" in parsed
        assert "mystery_tool" in parsed["error"]


# ---------------------------------------------------------------------------
# Capability activation approval
# ---------------------------------------------------------------------------

class TestCapabilityActivationApproval:
    @pytest.mark.asyncio
    async def test_when_capability_approval_required_and_not_approved_then_needs_approval(
        self, dkw, monkeypatch
    ):
        monkeypatch.setattr(settings, "CAPABILITY_APPROVAL", "required")
        dkw["args"] = '{"id": "my-cap"}'
        create_mock = AsyncMock(return_value="cap-appr-001")
        with patch("app.agent.tool_dispatch._check_tool_policy", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.tool_dispatch._create_approval_record", create_mock), \
             patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.capability_session.is_approved", return_value=False), \
             patch("app.agent.bots.get_bot", return_value=MagicMock(carapaces=[])), \
             patch("app.agent.carapaces.get_carapace", return_value={"name": "My Cap", "description": "test", "local_tools": []}):
            result = await dispatch_tool_call(name="activate_capability", allowed_tool_names=None, **dkw)

        assert result.needs_approval is True
        assert result.approval_id == "cap-appr-001"

    @pytest.mark.asyncio
    async def test_when_capability_already_pinned_then_no_approval(self, dkw, monkeypatch):
        """Bot has the cap in carapaces list → pinned → skip approval, run tool."""
        monkeypatch.setattr(settings, "CAPABILITY_APPROVAL", "required")
        dkw["args"] = '{"id": "pinned-cap"}'
        create_mock = AsyncMock(return_value="should-not-be-called")
        with patch("app.agent.tool_dispatch._check_tool_policy", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.tool_dispatch._create_approval_record", create_mock), \
             patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.capability_session.is_approved", return_value=False), \
             patch("app.agent.bots.get_bot", return_value=MagicMock(carapaces=["pinned-cap"])), \
             patch("app.agent.tool_dispatch.call_local_tool", new_callable=AsyncMock, return_value='{"ok": true}'), \
             patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock):
            result = await dispatch_tool_call(name="activate_capability", allowed_tool_names=None, **dkw)

        create_mock.assert_not_called()
        assert result.needs_approval is False

    @pytest.mark.asyncio
    async def test_when_capability_already_session_approved_then_no_approval(self, dkw, monkeypatch):
        """is_approved returns True → session-allow → skip approval gate."""
        monkeypatch.setattr(settings, "CAPABILITY_APPROVAL", "required")
        dkw["args"] = '{"id": "session-approved-cap"}'
        create_mock = AsyncMock(return_value="should-not-be-called")
        with patch("app.agent.tool_dispatch._check_tool_policy", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.tool_dispatch._create_approval_record", create_mock), \
             patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.capability_session.is_approved", return_value=True), \
             patch("app.agent.bots.get_bot", return_value=MagicMock(carapaces=[])), \
             patch("app.agent.tool_dispatch.call_local_tool", new_callable=AsyncMock, return_value='{"ok": true}'), \
             patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock):
            result = await dispatch_tool_call(name="activate_capability", allowed_tool_names=None, **dkw)

        create_mock.assert_not_called()
        assert result.needs_approval is False

    @pytest.mark.asyncio
    async def test_when_capability_approval_setting_off_then_no_approval(self, dkw, monkeypatch):
        monkeypatch.setattr(settings, "CAPABILITY_APPROVAL", "off")
        dkw["args"] = '{"id": "any-cap"}'
        create_mock = AsyncMock(return_value="should-not-be-called")
        with patch("app.agent.tool_dispatch._check_tool_policy", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.tool_dispatch._create_approval_record", create_mock), \
             patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch.call_local_tool", new_callable=AsyncMock, return_value='{"ok": true}'), \
             patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock):
            result = await dispatch_tool_call(name="activate_capability", allowed_tool_names=None, **dkw)

        create_mock.assert_not_called()
        assert result.needs_approval is False
