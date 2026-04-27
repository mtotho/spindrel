"""Spindrel ↔ Codex approval-mode + server-request translation tests.

Fixtures derived from the upstream codex app-server protocol README:
https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from integrations.codex import schema
from integrations.codex.approvals import (
    format_user_input_response_for_codex,
    handle_server_request,
    mode_to_codex_policy,
)

pytestmark = pytest.mark.asyncio


async def test_mode_translation_uses_schema_constants():
    bypass = mode_to_codex_policy("bypassPermissions")
    assert bypass["approvalPolicy"] == schema.APPROVAL_POLICY_NEVER
    assert bypass["sandbox"] == schema.SANDBOX_DANGER_FULL_ACCESS

    plan = mode_to_codex_policy("plan")
    assert plan["approvalPolicy"] == schema.APPROVAL_POLICY_NEVER
    assert plan["sandbox"] == schema.SANDBOX_READ_ONLY

    default = mode_to_codex_policy("default")
    assert default["approvalPolicy"] == schema.APPROVAL_POLICY_UNLESS_TRUSTED
    assert default["sandbox"] == schema.SANDBOX_WORKSPACE_WRITE

    accept = mode_to_codex_policy("acceptEdits")
    assert accept["approvalPolicy"] == schema.APPROVAL_POLICY_UNLESS_TRUSTED


async def test_sandbox_values_are_kebab_case():
    """Pinned against the installed codex binary's serde tag — kebab-case, not camelCase."""
    assert schema.SANDBOX_WORKSPACE_WRITE == "workspace-write"
    assert schema.SANDBOX_READ_ONLY == "read-only"
    assert schema.SANDBOX_DANGER_FULL_ACCESS == "danger-full-access"


async def test_approval_policy_values_match_binary():
    assert schema.APPROVAL_POLICY_NEVER == "never"
    assert schema.APPROVAL_POLICY_UNLESS_TRUSTED == "untrusted"
    assert schema.APPROVAL_POLICY_ON_REQUEST == "on-request"
    assert schema.APPROVAL_POLICY_ON_FAILURE == "on-failure"


@dataclass
class _FakeServerRequest:
    method: str
    params: dict
    id: int = 1
    response: Any = None
    error: dict | None = None

    async def respond(self, result: Any) -> None:
        self.response = result

    async def respond_error(self, code: int | str, message: str, data: Any = None) -> None:
        self.error = {"code": code, "message": message, "data": data}


class _FakeRuntime:
    name = "codex"


@pytest.fixture
def fake_ctx():
    class _Ctx:
        spindrel_session_id = "session"
        bot_id = "bot"
        channel_id = None
        turn_id = "turn"
        permission_mode = "default"

    return _Ctx()


async def test_unsupported_method_responds_not_supported(fake_ctx):
    req = _FakeServerRequest(method="something/random", params={})
    await handle_server_request(fake_ctx, _FakeRuntime(), req, allowed_tool_names=set())
    assert req.error is not None
    assert req.error["code"] == "not_supported"


async def test_command_approval_routes_with_decision_envelope(monkeypatch, fake_ctx):
    """Per README, item/commandExecution/requestApproval expects a decision reply."""
    captured: dict = {}

    async def _fake_request_harness_approval(*, ctx, runtime, tool_name, tool_input):
        captured["tool_name"] = tool_name
        from integrations.sdk import AllowDeny

        return AllowDeny(allow=True, reason="approved by user")

    monkeypatch.setattr(
        "integrations.codex.approvals.request_harness_approval",
        _fake_request_harness_approval,
    )

    req = _FakeServerRequest(
        method=schema.SERVER_REQUEST_COMMAND_APPROVAL,
        params={"item": {"id": "i1", "command": "rm -rf /"}, "command": "rm -rf /"},
    )
    await handle_server_request(fake_ctx, _FakeRuntime(), req, allowed_tool_names=set())
    assert captured["tool_name"] == "rm -rf /"
    assert req.response == {"decision": schema.APPROVAL_DECISION_ACCEPT}


async def test_file_change_approval_uses_decision_envelope(monkeypatch, fake_ctx):
    async def _fake_request_harness_approval(*, ctx, runtime, tool_name, tool_input):
        from integrations.sdk import AllowDeny

        return AllowDeny(allow=False, reason="user said no")

    monkeypatch.setattr(
        "integrations.codex.approvals.request_harness_approval",
        _fake_request_harness_approval,
    )

    req = _FakeServerRequest(
        method=schema.SERVER_REQUEST_FILE_CHANGE_APPROVAL,
        params={"item": {"id": "i2", "path": "/etc/passwd"}},
    )
    await handle_server_request(fake_ctx, _FakeRuntime(), req, allowed_tool_names=set())
    assert req.response is not None
    assert req.response["decision"] == schema.APPROVAL_DECISION_DECLINE
    assert req.response["reason"] == "user said no"


async def test_permissions_request_routes_through_approval(monkeypatch, fake_ctx):
    async def _fake_request_harness_approval(**kwargs):
        from integrations.sdk import AllowDeny

        return AllowDeny(allow=True, reason="ok")

    monkeypatch.setattr(
        "integrations.codex.approvals.request_harness_approval",
        _fake_request_harness_approval,
    )

    req = _FakeServerRequest(method=schema.SERVER_REQUEST_PERMISSIONS, params={})
    await handle_server_request(fake_ctx, _FakeRuntime(), req, allowed_tool_names=set())
    assert req.response == {"decision": schema.APPROVAL_DECISION_ACCEPT}


async def test_dynamic_tool_call_reads_tool_field(monkeypatch, fake_ctx):
    """Per README, item/tool/call params use `tool` (not `name` or `toolName`)."""

    async def _fake_execute(ctx, *, tool_name, arguments, allowed_tool_names):
        return f"result for {tool_name}: {arguments}"

    captured_approvals: list = []

    async def _capture_approval(**kwargs):
        captured_approvals.append(kwargs)
        from integrations.sdk import AllowDeny

        return AllowDeny(allow=True, reason="ok")

    monkeypatch.setattr(
        "integrations.codex.approvals.execute_harness_spindrel_tool",
        _fake_execute,
    )
    # Verify NO duplicate approval call for tool/call requests — Spindrel's
    # dispatch_tool_call already runs policy + approval.
    monkeypatch.setattr(
        "integrations.codex.approvals.request_harness_approval",
        _capture_approval,
    )

    req = _FakeServerRequest(
        method=schema.SERVER_REQUEST_TOOL_CALL,
        params={
            "threadId": "thread-1",
            "turnId": "turn-1",
            "callId": "call-1",
            "tool": "search_channel_knowledge",
            "arguments": {"query": "x"},
        },
    )
    await handle_server_request(
        fake_ctx, _FakeRuntime(), req, allowed_tool_names={"search_channel_knowledge"}
    )
    assert captured_approvals == [], "tool/call must not double-prompt for approval"
    assert req.response is not None
    items = req.response[schema.DYNAMIC_TOOL_RESULT_CONTENT_ITEMS]
    assert items[0]["type"] == schema.DYNAMIC_TOOL_CONTENT_ITEM_KIND_TEXT
    assert "search_channel_knowledge" in items[0]["text"]
    assert req.response[schema.DYNAMIC_TOOL_RESULT_SUCCESS] is True


async def test_dynamic_tool_call_missing_tool_field_returns_failure(fake_ctx):
    req = _FakeServerRequest(
        method=schema.SERVER_REQUEST_TOOL_CALL,
        params={"arguments": {"q": "x"}},
    )
    await handle_server_request(fake_ctx, _FakeRuntime(), req, allowed_tool_names=set())
    assert req.response is not None
    assert req.response[schema.DYNAMIC_TOOL_RESULT_SUCCESS] is False
    assert "tool" in req.response[schema.DYNAMIC_TOOL_RESULT_CONTENT_ITEMS][0]["text"]


async def test_dynamic_tool_call_dispatch_error_returns_failure_envelope(monkeypatch, fake_ctx):
    async def _fake_execute_raises(ctx, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "integrations.codex.approvals.execute_harness_spindrel_tool",
        _fake_execute_raises,
    )

    req = _FakeServerRequest(
        method=schema.SERVER_REQUEST_TOOL_CALL,
        params={"tool": "search_channel_knowledge", "arguments": {}},
    )
    await handle_server_request(
        fake_ctx, _FakeRuntime(), req, allowed_tool_names={"search_channel_knowledge"}
    )
    assert req.response[schema.DYNAMIC_TOOL_RESULT_SUCCESS] is False
    assert "boom" in req.response[schema.DYNAMIC_TOOL_RESULT_CONTENT_ITEMS][0]["text"]


async def test_user_input_request_routes_to_question_card(monkeypatch, fake_ctx):
    from integrations.sdk import HarnessQuestionResult

    async def _fake_request_question(*, ctx, runtime_name, tool_input):
        return HarnessQuestionResult(
            interaction_id="iid",
            questions=[{"id": "q1", "question": "ok?"}],
            answers=[{"question_id": "q1", "answer": "yes", "selected_options": []}],
            notes=None,
        )

    monkeypatch.setattr(
        "integrations.codex.approvals.request_harness_question",
        _fake_request_question,
    )

    req = _FakeServerRequest(
        method=schema.SERVER_REQUEST_USER_INPUT,
        params={"questions": [{"id": "q1", "question": "ok?"}]},
    )
    await handle_server_request(fake_ctx, _FakeRuntime(), req, allowed_tool_names=set())
    assert req.response == {"answers": {"q1": {"answers": ["yes"]}}}


async def test_user_input_response_schema_supports_selection_and_text():
    from integrations.sdk import HarnessQuestionResult

    result = HarnessQuestionResult(
        interaction_id="iid",
        questions=[{"id": "q1", "question": "Choose"}, {"id": "q2", "question": "Why"}],
        answers=[
            {"question_id": "q1", "answer": "", "selected_options": ["A", "B"]},
            {"question_id": "q2", "answer": "because", "selected_options": []},
        ],
        notes=None,
    )

    assert format_user_input_response_for_codex(result) == {
        "answers": {
            "q1": {"answers": ["A", "B"]},
            "q2": {"answers": ["because"]},
        }
    }
