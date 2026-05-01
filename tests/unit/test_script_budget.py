"""Tests for :mod:`app.services.script_budget` — the per-correlation
inner-tool-call counter that caps ``run_script``'s blast radius."""
from __future__ import annotations

import pytest

from app.services import script_budget


@pytest.fixture(autouse=True)
async def _isolate_budgets():
    # Clear any entries left over from a prior test.
    script_budget._entries.clear()
    yield
    script_budget._entries.clear()


@pytest.mark.asyncio
async def test_spend_on_untracked_id_allows():
    allowed, remaining, limit = await script_budget.spend("no-such-id")
    assert allowed is True
    assert remaining == -1
    assert limit == -1


@pytest.mark.asyncio
async def test_spend_on_empty_id_allows():
    allowed, remaining, limit = await script_budget.spend("")
    assert allowed is True
    assert remaining == -1
    assert limit == -1


@pytest.mark.asyncio
async def test_spend_decrements_until_zero():
    await script_budget.open_budget("cid-A", 3)

    allowed, remaining, limit = await script_budget.spend("cid-A")
    assert (allowed, remaining, limit) == (True, 2, 3)

    allowed, remaining, _ = await script_budget.spend("cid-A")
    assert (allowed, remaining) == (True, 1)

    allowed, remaining, _ = await script_budget.spend("cid-A")
    assert (allowed, remaining) == (True, 0)

    allowed, remaining, limit = await script_budget.spend("cid-A")
    assert (allowed, remaining, limit) == (False, 0, 3)


@pytest.mark.asyncio
async def test_close_budget_returns_spent_and_limit():
    await script_budget.open_budget("cid-B", 5)
    for _ in range(2):
        await script_budget.spend("cid-B")

    result = await script_budget.close_budget("cid-B")
    assert result == (2, 5)  # (spent, limit)

    # After close, spending is allowed (untracked again).
    allowed, remaining, limit = await script_budget.spend("cid-B")
    assert (allowed, remaining, limit) == (True, -1, -1)


@pytest.mark.asyncio
async def test_close_on_unknown_id_returns_none():
    assert await script_budget.close_budget("never-opened") is None


@pytest.mark.asyncio
async def test_peek_does_not_decrement():
    await script_budget.open_budget("cid-C", 4)
    remaining, limit = await script_budget.peek("cid-C")
    assert (remaining, limit) == (4, 4)

    await script_budget.spend("cid-C")
    remaining, limit = await script_budget.peek("cid-C")
    assert (remaining, limit) == (3, 4)


@pytest.mark.asyncio
async def test_open_budget_with_zero_or_negative_is_noop():
    await script_budget.open_budget("cid-D", 0)
    assert await script_budget.peek("cid-D") == (-1, -1)

    await script_budget.open_budget("cid-D", -5)
    assert await script_budget.peek("cid-D") == (-1, -1)


@pytest.mark.asyncio
async def test_reopen_resets_remaining():
    await script_budget.open_budget("cid-E", 2)
    await script_budget.spend("cid-E")  # remaining=1
    await script_budget.open_budget("cid-E", 2)  # reopen
    remaining, limit = await script_budget.peek("cid-E")
    assert (remaining, limit) == (2, 2)


@pytest.mark.asyncio
async def test_independent_correlation_ids_do_not_interfere():
    await script_budget.open_budget("cid-F", 2)
    await script_budget.open_budget("cid-G", 2)

    await script_budget.spend("cid-F")
    await script_budget.spend("cid-F")
    allowed_f, _, _ = await script_budget.spend("cid-F")
    assert allowed_f is False

    # cid-G is untouched.
    remaining, limit = await script_budget.peek("cid-G")
    assert (remaining, limit) == (2, 2)


@pytest.mark.asyncio
async def test_peek_origin_returns_parent_origin_kind():
    await script_budget.open_budget("cid-H", 5, origin_kind="heartbeat")
    assert await script_budget.peek_origin("cid-H") == "heartbeat"

    # Unknown id → None (untracked).
    assert await script_budget.peek_origin("never-opened") is None
    assert await script_budget.peek_origin(None) is None


@pytest.mark.asyncio
async def test_peek_origin_default_none_when_not_set():
    # Without origin_kind kw — default behavior (parent had no origin).
    await script_budget.open_budget("cid-I", 5)
    assert await script_budget.peek_origin("cid-I") is None


@pytest.mark.asyncio
async def test_origin_cleared_on_close():
    await script_budget.open_budget("cid-J", 5, origin_kind="task")
    assert await script_budget.peek_origin("cid-J") == "task"
    await script_budget.close_budget("cid-J")
    assert await script_budget.peek_origin("cid-J") is None


@pytest.mark.asyncio
async def test_is_tool_allowed_no_budget_returns_true():
    assert await script_budget.is_tool_allowed("never-opened", "any_tool") is True
    assert await script_budget.is_tool_allowed(None, "any_tool") is True


@pytest.mark.asyncio
async def test_is_tool_allowed_no_allowlist_returns_true():
    # Inline-script case — no allowlist on the budget; everything passes
    # the allowlist check (origin propagation is the only protection).
    await script_budget.open_budget("cid-K", 5)
    assert await script_budget.is_tool_allowed("cid-K", "exec_command") is True


@pytest.mark.asyncio
async def test_is_tool_allowed_enforces_allowlist():
    await script_budget.open_budget(
        "cid-L", 5, allowed_tools=["list_pipelines", "send_message"],
    )
    assert await script_budget.is_tool_allowed("cid-L", "list_pipelines") is True
    assert await script_budget.is_tool_allowed("cid-L", "send_message") is True
    assert await script_budget.is_tool_allowed("cid-L", "exec_command") is False


@pytest.mark.asyncio
async def test_is_tool_allowed_empty_allowlist_blocks_everything():
    # An explicitly empty allowlist on a stored script means "this script
    # makes no tool calls." Filter out empty strings → frozenset() → all
    # tools rejected.
    await script_budget.open_budget("cid-M", 5, allowed_tools=[""])
    assert await script_budget.is_tool_allowed("cid-M", "any_tool") is False
