from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from app.agent.tool_dispatch import dispatch_tool_call
from app.services.widget_templates import _register_widgets, _widget_templates, apply_widget_template


@pytest.fixture
def dkw():
    return dict(
        args="{}",
        tool_call_id="tc_machine_1",
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


def _swallow_task(coro):
    try:
        coro.close()
    except Exception:
        pass
    return None


class TestMachineControlExecutionPolicyEnvelope:
    @pytest.mark.asyncio
    async def test_dispatch_denial_returns_machine_access_required_envelope(self, dkw):
        @asynccontextmanager
        async def _fake_db():
            yield object()

        payload = {
            "reason": "Grant machine control for this session before using that tool.",
            "execution_policy": "live_target_lease",
            "requested_tool": "local_exec_command",
            "session_id": str(dkw["session_id"]),
            "lease": None,
            "targets": [
                {
                    "target_id": "target-1",
                    "driver": "companion",
                    "label": "Desk",
                    "hostname": "workstation",
                    "platform": "linux",
                    "capabilities": ["shell"],
                    "connected": True,
                    "connection_id": "conn-1",
                },
            ],
            "connected_targets": [
                {
                    "target_id": "target-1",
                    "driver": "companion",
                    "label": "Desk",
                    "hostname": "workstation",
                    "platform": "linux",
                    "capabilities": ["shell"],
                    "connected": True,
                    "connection_id": "conn-1",
                },
            ],
            "connected_target_count": 1,
            "integration_admin_href": "/admin/integrations/local_companion",
        }

        with (
            patch("app.agent.tool_dispatch.is_client_tool", return_value=False),
            patch("app.agent.tool_dispatch.is_local_tool", return_value=True),
            patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False),
            patch("app.tools.registry.get_tool_execution_policy", return_value="live_target_lease"),
            patch(
                "app.services.local_machine_control.validate_current_execution_policy",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(
                    allowed=False,
                    reason=payload["reason"],
                    lease=None,
                ),
            ),
            patch(
                "app.services.local_machine_control.build_machine_access_required_payload",
                new_callable=AsyncMock,
                return_value=payload,
            ),
            patch("app.agent.tool_dispatch.async_session", side_effect=lambda: _fake_db()),
            patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock) as mock_record,
            patch("app.agent.tool_dispatch.safe_create_task", side_effect=_swallow_task),
        ):
            result = await dispatch_tool_call(
                name="local_exec_command",
                allowed_tool_names=None,
                **dkw,
            )

        parsed = json.loads(result.result)
        assert parsed["error"] == "local_control_required"
        assert result.envelope.view_key == "core.machine_access_required"
        assert result.envelope.content_type == "application/vnd.spindrel.components+json"
        assert result.envelope.data == payload
        recorded_envelope = mock_record.call_args.kwargs["envelope"]
        assert recorded_envelope["view_key"] == "core.machine_access_required"
        assert recorded_envelope["data"]["connected_target_count"] == 1


class TestLocalCompanionWidgets:
    def _register_local_companion_widgets(self):
        manifest_path = Path("integrations/local_companion/integration.yaml")
        manifest = yaml.safe_load(manifest_path.read_text())
        _widget_templates.clear()
        _register_widgets(
            "test:local_companion",
            manifest["tool_widgets"],
            base_dir=manifest_path.parent,
        )

    def test_local_status_widget_is_refreshable_semantic_view(self):
        self._register_local_companion_widgets()
        env = apply_widget_template(
            "local_status",
            json.dumps(
                {
                    "session_id": "session-1",
                    "lease": None,
                    "connected_target_count": 1,
                    "targets": [
                        {
                            "target_id": "target-1",
                            "driver": "companion",
                            "label": "Desk",
                            "hostname": "workstation",
                            "platform": "linux",
                            "capabilities": ["shell"],
                            "connected": True,
                            "connection_id": "conn-1",
                        },
                    ],
                }
            ),
        )
        assert env is not None
        assert env.view_key == "core.machine_target_status"
        assert env.refreshable is True

    def test_local_exec_widget_uses_command_result_view(self):
        self._register_local_companion_widgets()
        env = apply_widget_template(
            "local_exec_command",
            json.dumps(
                {
                    "command": "npm test",
                    "working_dir": "/repo",
                    "target_id": "target-1",
                    "target_label": "Desk",
                    "target_hostname": "workstation",
                    "target_platform": "linux",
                    "stdout": "PASS\n",
                    "stderr": "",
                    "exit_code": 0,
                    "duration_ms": 42,
                    "truncated": False,
                }
            ),
        )
        assert env is not None
        assert env.view_key == "core.command_result"
        assert env.display_label == "Desk"
