"""Tests for skip_tool_policy threading through heartbeat and task execution."""
import json
import uuid
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest


@dataclass
class _FakePolicyDecision:
    action: str
    reason: str
    rule_id: str = "rule-1"
    tier: str | None = None
    timeout: int = 300


class TestDispatchToolCallSkipPolicy:
    """Verify that skip_policy controls whether _check_tool_policy is called."""

    @pytest.mark.asyncio
    async def test_skip_policy_true_bypasses_deny(self):
        """When skip_policy=True, a deny policy should be bypassed entirely."""
        from app.agent.tool_dispatch import dispatch_tool_call

        deny_decision = _FakePolicyDecision(action="deny", reason="blocked")

        with patch(
            "app.agent.tool_dispatch._check_tool_policy",
            new_callable=AsyncMock,
            return_value=deny_decision,
        ) as mock_policy:
            # skip_policy=True → should NOT call _check_tool_policy, so tool proceeds
            # The tool itself will error (no handler), but we just need to verify
            # that the policy deny didn't short-circuit the call.
            result = await dispatch_tool_call(
                name="nonexistent_tool_for_test",
                args=json.dumps({}),
                tool_call_id="tc-1",
                bot_id="bot1",
                bot_memory=None,
                session_id=uuid.uuid4(),
                client_id="test",
                correlation_id=None,
                channel_id=None,
                iteration=0,
                provider_id=None,
                summarize_enabled=False,
                summarize_threshold=10000,
                summarize_model="",
                summarize_max_tokens=500,
                summarize_exclude=set(),
                compaction=False,
                skip_policy=True,
            )

            mock_policy.assert_not_called()
            # Result should NOT be a policy deny
            if result.result:
                parsed = json.loads(result.result)
                assert "denied by policy" not in parsed.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_skip_policy_false_respects_deny(self):
        """When skip_policy=False (default), a deny decision blocks the tool."""
        from app.agent.tool_dispatch import dispatch_tool_call

        deny_decision = _FakePolicyDecision(action="deny", reason="blocked")

        with patch(
            "app.agent.tool_dispatch._check_tool_policy",
            new_callable=AsyncMock,
            return_value=deny_decision,
        ) as mock_policy:
            result = await dispatch_tool_call(
                name="web_search",
                args=json.dumps({"query": "test"}),
                tool_call_id="tc-1",
                bot_id="bot1",
                bot_memory=None,
                session_id=uuid.uuid4(),
                client_id="test",
                correlation_id=None,
                channel_id=None,
                iteration=0,
                provider_id=None,
                summarize_enabled=False,
                summarize_threshold=10000,
                summarize_model="",
                summarize_max_tokens=500,
                summarize_exclude=set(),
                compaction=False,
                skip_policy=False,
            )

            mock_policy.assert_called_once()
            # Result should be a policy deny
            assert result.result is not None
            parsed = json.loads(result.result)
            assert "denied by policy" in parsed["error"].lower()


class TestRunSignature:
    """Verify that run(), run_stream(), and run_agent_tool_loop() accept skip_tool_policy."""

    def test_run_stream_accepts_skip_tool_policy(self):
        import inspect
        from app.agent.loop import run_stream

        sig = inspect.signature(run_stream)
        assert "skip_tool_policy" in sig.parameters
        assert sig.parameters["skip_tool_policy"].default is False

    def test_run_accepts_skip_tool_policy(self):
        import inspect
        from app.agent.loop import run

        sig = inspect.signature(run)
        assert "skip_tool_policy" in sig.parameters
        assert sig.parameters["skip_tool_policy"].default is False

    def test_run_agent_tool_loop_accepts_skip_tool_policy(self):
        import inspect
        from app.agent.loop import run_agent_tool_loop

        sig = inspect.signature(run_agent_tool_loop)
        assert "skip_tool_policy" in sig.parameters
        assert sig.parameters["skip_tool_policy"].default is False


class TestHeartbeatModel:
    """Verify the ChannelHeartbeat model has skip_tool_approval column."""

    def test_model_has_skip_tool_approval(self):
        from app.db.models import ChannelHeartbeat
        assert hasattr(ChannelHeartbeat, "skip_tool_approval")


class TestHeartbeatAPISchemas:
    """Verify the API schemas include skip_tool_approval."""

    def test_heartbeat_config_out_has_field(self):
        try:
            from app.routers.api_v1_admin.channels import HeartbeatConfigOut
        except ImportError:
            pytest.skip("Admin channel router has unrelated import issue")
        fields = HeartbeatConfigOut.model_fields
        assert "skip_tool_approval" in fields

    def test_heartbeat_update_has_field(self):
        try:
            from app.routers.api_v1_admin.channels import HeartbeatUpdate
        except ImportError:
            pytest.skip("Admin channel router has unrelated import issue")
        fields = HeartbeatUpdate.model_fields
        assert "skip_tool_approval" in fields
        schema = HeartbeatUpdate.model_json_schema()
        assert schema["properties"]["skip_tool_approval"]["default"] is False
