"""Pure decision matrix for request_harness_approval.

Covers the short-circuit paths only — the four mode × runtime classification
combinations that should NOT touch the DB or ask the user. The actual
ask path (DB write + future + SSE event + await) is exercised by
``tests/integration/test_harness_approvals.py`` against a real session.
"""
from __future__ import annotations

import contextlib
import uuid

import pytest

from app.services.agent_harnesses.approvals import (
    AllowDeny,
    grant_turn_bypass,
    request_harness_approval,
    revoke_turn_bypass,
)
from app.services.agent_harnesses.base import TurnContext


# ----------------------------------------------------------------------------
# Stubs — keep the test pure (no DB, no SDK).
# ----------------------------------------------------------------------------


class _StubRuntime:
    """Minimal HarnessRuntime stand-in implementing the classification trio."""

    def readonly_tools(self) -> frozenset[str]:
        return frozenset({"Read", "Glob"})

    def prompts_in_accept_edits(self, tool_name: str) -> bool:
        # Asks on Bash/ExitPlanMode; auto-approves Edit/Write/readonly.
        return tool_name in {"Bash", "ExitPlanMode", "WebFetch"}

    def autoapprove_in_plan(self, tool_name: str) -> bool:
        return tool_name == "ExitPlanMode"


_UNSET = object()


def _ctx(*, mode: str, channel_id=_UNSET) -> TurnContext:
    @contextlib.asynccontextmanager
    async def _never_called():
        # Sentinel — no short-circuit path should open a DB scope.
        raise AssertionError("DB session should not be opened on short-circuit path")
        yield  # pragma: no cover

    if channel_id is _UNSET:
        channel_id_value: uuid.UUID | None = uuid.uuid4()
    else:
        channel_id_value = channel_id  # may be None — channel-less turn
    return TurnContext(
        spindrel_session_id=uuid.uuid4(),
        channel_id=channel_id_value,
        bot_id="test-bot",
        turn_id=uuid.uuid4(),
        workdir="/tmp",
        harness_session_id=None,
        permission_mode=mode,
        db_session_factory=_never_called,
    )


# ----------------------------------------------------------------------------
# Mode short-circuits
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bypass_mode_allows_anything():
    decision = await request_harness_approval(
        ctx=_ctx(mode="bypassPermissions"),
        runtime=_StubRuntime(),
        tool_name="Bash",
        tool_input={"cmd": "rm -rf /"},
    )
    assert decision == AllowDeny.allow_()


@pytest.mark.asyncio
async def test_readonly_tool_allows_in_every_ask_mode():
    """Read/Glob auto-approve regardless of mode (except bypass already handled)."""
    rt = _StubRuntime()
    for mode in ("acceptEdits", "default", "plan"):
        for tool in ("Read", "Glob"):
            decision = await request_harness_approval(
                ctx=_ctx(mode=mode), runtime=rt,
                tool_name=tool, tool_input={"path": "x"},
            )
            assert decision.allow, f"mode={mode} tool={tool}"


@pytest.mark.asyncio
async def test_plan_mode_auto_approves_exit_plan_mode():
    decision = await request_harness_approval(
        ctx=_ctx(mode="plan"),
        runtime=_StubRuntime(),
        tool_name="ExitPlanMode",
        tool_input={"plan": "step 1, step 2"},
    )
    assert decision.allow


@pytest.mark.asyncio
async def test_accept_edits_short_circuits_for_native_edits():
    """In acceptEdits mode, Edit/Write/readonly auto-approve (SDK or runtime)."""
    rt = _StubRuntime()
    for tool in ("Edit", "Write"):
        decision = await request_harness_approval(
            ctx=_ctx(mode="acceptEdits"), runtime=rt,
            tool_name=tool, tool_input={},
        )
        assert decision.allow, f"acceptEdits {tool} should auto-approve"


# ----------------------------------------------------------------------------
# Per-turn bypass
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_turn_bypass_short_circuits_even_in_default_mode():
    ctx = _ctx(mode="default")
    grant_turn_bypass(ctx.turn_id)
    try:
        decision = await request_harness_approval(
            ctx=ctx, runtime=_StubRuntime(),
            tool_name="Bash", tool_input={"cmd": "ls"},
        )
        assert decision.allow
    finally:
        revoke_turn_bypass(ctx.turn_id)


@pytest.mark.asyncio
async def test_revoke_turn_bypass_returns_to_ask_path():
    """After revoke, Bash in default mode should attempt the ask path
    (we observe that by the AssertionError in our stub db factory)."""
    ctx = _ctx(mode="default")
    grant_turn_bypass(ctx.turn_id)
    revoke_turn_bypass(ctx.turn_id)
    with pytest.raises(AssertionError, match="DB session should not be opened"):
        await request_harness_approval(
            ctx=ctx, runtime=_StubRuntime(),
            tool_name="Bash", tool_input={"cmd": "ls"},
        )


# ----------------------------------------------------------------------------
# Channel-less guard
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channel_less_turn_denies_safely_on_ask_path():
    """No channel → no UI to surface the approval through → deny safely."""
    ctx = _ctx(mode="default", channel_id=None)
    decision = await request_harness_approval(
        ctx=ctx, runtime=_StubRuntime(),
        tool_name="Bash", tool_input={"cmd": "ls"},
    )
    assert not decision.allow
    assert "channel" in (decision.reason or "").lower()


# ----------------------------------------------------------------------------
# AllowDeny constructors
# ----------------------------------------------------------------------------


def test_allow_deny_constructors():
    assert AllowDeny.allow_() == AllowDeny(allow=True, reason=None)
    assert AllowDeny.deny("nope") == AllowDeny(allow=False, reason="nope")
