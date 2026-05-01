"""Tests for the run_script → /internal/tools/exec security boundary.

Covers two protections introduced for the ``run_script`` arbitrary-Python
tightening pass:

1. **Parent origin_kind propagation**: when ``run_script`` opens a budget
   with the parent run's ``origin_kind``, the inner endpoint sets
   ``current_run_origin`` ContextVar to that value before calling
   ``_check_tool_policy``. Closes the gap where an autonomous-origin
   run_script would let nested tool calls run as the default ``chat``
   origin and bypass autonomous-only approval rules.

2. **Stored-script ``allowed_tools`` allowlist**: when the budget carries
   an explicit allowed-tools list, nested calls outside the list are
   rejected with HTTP 403 before policy/budget — fail-closed.

These tests stub auth, DB, and policy resolution because the focus is
the boundary behavior, not the broader dispatch pipeline.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.routers.api_v1_internal_tools import ToolExecRequest, exec_tool
from app.services import script_budget


class _FakeAuth:
    key_id = "11111111-1111-1111-1111-111111111111"
    scopes = ["chat"]


@pytest.fixture(autouse=True)
async def _clear_budgets():
    script_budget._entries.clear()
    yield
    script_budget._entries.clear()


@pytest.mark.asyncio
async def test_origin_propagated_into_policy_check():
    """Budget opened with origin_kind='heartbeat' → endpoint must set
    current_run_origin so the policy evaluator sees 'heartbeat' for the
    nested call (not the default 'chat')."""
    cid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    await script_budget.open_budget(cid, 5, origin_kind="heartbeat")

    seen: dict = {}

    async def _capture_policy(bot_id, tool_name, arguments, *, correlation_id=None):
        from app.agent.context import current_run_origin
        seen["origin"] = current_run_origin.get(None)
        seen["tool"] = tool_name
        # Allow path: returning None means policy.allow.
        return None

    req = ToolExecRequest(
        name="list_pipelines",
        arguments={},
        parent_correlation_id=cid,
    )

    with patch(
        "app.routers.api_v1_internal_tools._resolve_calling_bot",
        AsyncMock(return_value="bot-x"),
    ), patch(
        "app.agent.tool_dispatch._check_tool_policy",
        AsyncMock(side_effect=_capture_policy),
    ), patch(
        "app.tools.registry.is_local_tool", return_value=True,
    ), patch(
        "app.tools.registry.get_tool_execution_policy", return_value="normal",
    ), patch(
        "app.tools.registry.call_local_tool",
        AsyncMock(return_value='{"ok": true}'),
    ):
        await exec_tool(req, auth=_FakeAuth(), db=None)  # type: ignore[arg-type]

    assert seen["origin"] == "heartbeat", (
        "Parent origin_kind was not propagated into the policy check ContextVar; "
        "nested call would bypass autonomous-only approval rules."
    )
    assert seen["tool"] == "list_pipelines"


@pytest.mark.asyncio
async def test_no_origin_when_budget_untracked():
    """No budget for the correlation id (call did not originate from a
    tracked run_script) → no propagation, current_run_origin stays None
    inside the policy check (the default-chat fallback applies)."""
    seen: dict = {}

    async def _capture_policy(bot_id, tool_name, arguments, *, correlation_id=None):
        from app.agent.context import current_run_origin
        seen["origin"] = current_run_origin.get(None)
        return None

    req = ToolExecRequest(
        name="list_pipelines",
        arguments={},
        parent_correlation_id=None,  # Untracked.
    )

    with patch(
        "app.routers.api_v1_internal_tools._resolve_calling_bot",
        AsyncMock(return_value="bot-x"),
    ), patch(
        "app.agent.tool_dispatch._check_tool_policy",
        AsyncMock(side_effect=_capture_policy),
    ), patch(
        "app.tools.registry.is_local_tool", return_value=True,
    ), patch(
        "app.tools.registry.get_tool_execution_policy", return_value="normal",
    ), patch(
        "app.tools.registry.call_local_tool",
        AsyncMock(return_value='{"ok": true}'),
    ):
        await exec_tool(req, auth=_FakeAuth(), db=None)  # type: ignore[arg-type]

    assert seen["origin"] is None


@pytest.mark.asyncio
async def test_allowlist_rejects_off_list_tool_with_403():
    """Stored-script allowed_tools allowlist rejects nested calls outside
    the list before policy/budget."""
    cid = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    await script_budget.open_budget(
        cid, 5,
        origin_kind="chat",
        allowed_tools=["list_pipelines"],
    )

    req = ToolExecRequest(
        name="exec_command",
        arguments={"cmd": "rm -rf /"},
        parent_correlation_id=cid,
    )

    # Resolve and policy must NOT be reached.
    with patch(
        "app.routers.api_v1_internal_tools._resolve_calling_bot",
        AsyncMock(side_effect=AssertionError("resolve should not run")),
    ), patch(
        "app.agent.tool_dispatch._check_tool_policy",
        AsyncMock(side_effect=AssertionError("policy should not run")),
    ):
        with pytest.raises(HTTPException) as info:
            await exec_tool(req, auth=_FakeAuth(), db=None)  # type: ignore[arg-type]

    assert info.value.status_code == 403
    detail = info.value.detail
    assert isinstance(detail, dict)
    assert detail["error"] == "script_tool_not_in_allowlist"
    assert detail["tool"] == "exec_command"

    # Budget remaining was NOT decremented (allowlist rejection happens
    # before spend).
    remaining, limit = await script_budget.peek(cid)
    assert (remaining, limit) == (5, 5)


@pytest.mark.asyncio
async def test_allowlist_passes_in_list_tool():
    """Tool name on the allowlist proceeds to policy/dispatch normally."""
    cid = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    await script_budget.open_budget(
        cid, 5,
        origin_kind="chat",
        allowed_tools=["list_pipelines"],
    )

    req = ToolExecRequest(
        name="list_pipelines",
        arguments={},
        parent_correlation_id=cid,
    )

    with patch(
        "app.routers.api_v1_internal_tools._resolve_calling_bot",
        AsyncMock(return_value="bot-x"),
    ), patch(
        "app.agent.tool_dispatch._check_tool_policy",
        AsyncMock(return_value=None),
    ), patch(
        "app.tools.registry.is_local_tool", return_value=True,
    ), patch(
        "app.tools.registry.get_tool_execution_policy", return_value="normal",
    ), patch(
        "app.tools.registry.call_local_tool",
        AsyncMock(return_value='{"ok": true}'),
    ):
        # Should succeed without raising.
        await exec_tool(req, auth=_FakeAuth(), db=None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_allowlist_does_not_apply_to_untracked_call():
    """A call with no parent_correlation_id has no budget, so allowlist
    enforcement skips — there is no allowlist to enforce. Policy gate
    remains the only protection (same as today's non-script callers)."""
    seen: dict = {}

    async def _capture_policy(bot_id, tool_name, arguments, *, correlation_id=None):
        seen["tool"] = tool_name
        return None

    req = ToolExecRequest(
        name="exec_command",
        arguments={"cmd": "ls"},
        parent_correlation_id=None,
    )

    with patch(
        "app.routers.api_v1_internal_tools._resolve_calling_bot",
        AsyncMock(return_value="bot-x"),
    ), patch(
        "app.agent.tool_dispatch._check_tool_policy",
        AsyncMock(side_effect=_capture_policy),
    ), patch(
        "app.tools.registry.is_local_tool", return_value=True,
    ), patch(
        "app.tools.registry.get_tool_execution_policy", return_value="normal",
    ), patch(
        "app.tools.registry.call_local_tool",
        AsyncMock(return_value='{"ok": true}'),
    ):
        await exec_tool(req, auth=_FakeAuth(), db=None)  # type: ignore[arg-type]

    assert seen["tool"] == "exec_command"


@pytest.mark.asyncio
async def test_origin_contextvar_reset_after_dispatch():
    """current_run_origin must be cleared on the request boundary so a
    leaked ContextVar doesn't survive into a subsequent unrelated handler
    on the same worker."""
    from app.agent.context import current_run_origin

    cid = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    await script_budget.open_budget(cid, 5, origin_kind="task")

    req = ToolExecRequest(
        name="list_pipelines",
        arguments={},
        parent_correlation_id=cid,
    )

    assert current_run_origin.get(None) is None  # baseline

    with patch(
        "app.routers.api_v1_internal_tools._resolve_calling_bot",
        AsyncMock(return_value="bot-x"),
    ), patch(
        "app.agent.tool_dispatch._check_tool_policy",
        AsyncMock(return_value=None),
    ), patch(
        "app.tools.registry.is_local_tool", return_value=True,
    ), patch(
        "app.tools.registry.get_tool_execution_policy", return_value="normal",
    ), patch(
        "app.tools.registry.call_local_tool",
        AsyncMock(return_value='{"ok": true}'),
    ):
        await exec_tool(req, auth=_FakeAuth(), db=None)  # type: ignore[arg-type]

    assert current_run_origin.get(None) is None, (
        "current_run_origin leaked past the request boundary"
    )
