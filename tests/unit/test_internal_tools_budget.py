"""Tests that ``/api/v1/internal/tools/exec`` honors the
:mod:`app.services.script_budget` cap. Pin the 429 path so a future
refactor doesn't silently reopen the cost-amplification hole.

The policy-check + dispatch path is exercised by
``tests/unit/test_run_script.py`` and ``test_tool_dispatch.py``; this
module intentionally narrows to the budget guard that sits ahead of
policy.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.routers.api_v1_internal_tools import ToolExecRequest, exec_tool
from app.services import script_budget


class _FakeAuth:
    """Minimal ApiKeyAuth stand-in — real one is pydantic-ish and requires
    DB wiring. The budget check runs before `_resolve_calling_bot` is
    called, so these fields never matter for the exhausted-path test."""

    key_id = "11111111-1111-1111-1111-111111111111"
    scopes = ["chat"]


@pytest.fixture(autouse=True)
async def _clear_budgets():
    script_budget._entries.clear()
    yield
    script_budget._entries.clear()


@pytest.mark.asyncio
async def test_budget_exhausted_returns_429_before_policy():
    """A registered budget at zero trips the guard before policy check
    fires — confirms ordering + short-circuit."""
    cid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    await script_budget.open_budget(cid, 1)
    # Consume the single allowed call.
    await script_budget.spend(cid)

    req = ToolExecRequest(
        name="list_skills",
        arguments={},
        parent_correlation_id=cid,
    )

    # Policy-check + resolve_calling_bot should NOT be reached. Patch them
    # to blow up if they are.
    with patch(
        "app.routers.api_v1_internal_tools._resolve_calling_bot",
        AsyncMock(side_effect=AssertionError("resolve should not run")),
    ), patch(
        "app.agent.tool_dispatch._check_tool_policy",
        AsyncMock(side_effect=AssertionError("policy should not run")),
    ):
        with pytest.raises(HTTPException) as info:
            await exec_tool(req, auth=_FakeAuth(), db=None)  # type: ignore[arg-type]

    assert info.value.status_code == 429
    detail = info.value.detail
    assert isinstance(detail, dict)
    assert detail["error"] == "script_tool_budget_exhausted"
    assert detail["limit"] == 1


@pytest.mark.asyncio
async def test_untracked_correlation_id_passes_budget_guard():
    """A call with a parent_correlation_id that was never `open_budget`d
    (e.g. non-script caller) must NOT be 429'd by the guard. We don't
    drive the full handler — just assert that ``spend`` allows it."""
    allowed, _, _ = await script_budget.spend("not-a-known-id")
    assert allowed is True


@pytest.mark.asyncio
async def test_missing_correlation_id_is_allowed():
    allowed, _, _ = await script_budget.spend(None)
    assert allowed is True
