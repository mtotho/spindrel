"""Real-DB tests for app/services/bot_hooks.py.

Exercises CRUD against a real SQLite session, the in-memory cache populated by
``load_bot_hooks``, and the trigger pathways (``run_before_access``,
``schedule_after_write``, ``run_after_exec``). Only ``workspace_service.exec``
is patched (E.1 — true external; runs subprocess) and ``app.agent.bots.get_bot``
is replaced via the ``bot_registry`` harness (in-memory dict, not a DB lookup).
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.agent.bots import WorkspaceConfig
from app.db.models import BotHook
from app.services import bot_hooks as hooks_mod
from tests.factories import build_bot_hook


# ---------------------------------------------------------------------------
# Module-level cache hygiene
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_hook_caches():
    hooks_mod._hooks_by_bot.clear()
    hooks_mod._cooldowns.clear()
    hooks_mod._pending_after_write.clear()
    yield
    hooks_mod._hooks_by_bot.clear()
    hooks_mod._cooldowns.clear()
    for handle in hooks_mod._pending_after_write.values():
        handle.cancel()
    hooks_mod._pending_after_write.clear()


@pytest_asyncio.fixture
async def workspace_exec_patch():
    """Patch the only external collaborator: workspace_service.exec (subprocess)."""
    from app.services.workspace import ExecResult, workspace_service

    success = ExecResult(
        stdout="ok", stderr="", exit_code=0, truncated=False, duration_ms=1, workspace_type="host",
    )
    with patch.object(workspace_service, "exec", new_callable=AsyncMock) as m:
        m.return_value = success
        yield m


def _ws_enabled() -> WorkspaceConfig:
    return WorkspaceConfig(enabled=True, type="host")


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


class TestCreateHook:
    async def test_when_create_called_then_row_persisted_and_cached(
        self, db_session, patched_async_sessions
    ):
        data = {
            "name": "lint",
            "trigger": "after_write",
            "conditions": {"path": "/workspace/src/*.py"},
            "command": "ruff check",
        }

        row = await hooks_mod.create_hook("bot-A", data)

        persisted = await db_session.get(BotHook, row.id)
        assert persisted.name == "lint"
        assert persisted.trigger == "after_write"
        assert hooks_mod._hooks_by_bot["bot-A"][0].id == row.id

    async def test_when_create_with_before_access_trigger_then_on_failure_defaults_to_block(
        self, db_session, patched_async_sessions
    ):
        data = {"name": "guard", "trigger": "before_access", "command": "true"}

        row = await hooks_mod.create_hook("bot-B", data)

        persisted = await db_session.get(BotHook, row.id)
        assert persisted.on_failure == "block"

    async def test_when_create_with_non_blocking_trigger_then_on_failure_defaults_to_warn(
        self, db_session, patched_async_sessions
    ):
        data = {"name": "notify", "trigger": "after_write", "command": "true"}

        row = await hooks_mod.create_hook("bot-C", data)

        persisted = await db_session.get(BotHook, row.id)
        assert persisted.on_failure == "warn"

    async def test_when_create_with_enabled_false_then_not_added_to_cache(
        self, db_session, patched_async_sessions
    ):
        data = {
            "name": "dormant", "trigger": "after_write", "command": "true", "enabled": False,
        }

        row = await hooks_mod.create_hook("bot-D", data)

        assert (await db_session.get(BotHook, row.id)) is not None
        assert hooks_mod._hooks_by_bot.get("bot-D") is None


class TestUpdateHook:
    async def test_when_update_called_then_fields_persist_and_cache_reloads(
        self, db_session, patched_async_sessions
    ):
        existing = build_bot_hook("bot-A", name="old", command="true", trigger="after_write")
        db_session.add(existing)
        await db_session.commit()

        updated = await hooks_mod.update_hook(
            existing.id, "bot-A", {"name": "new", "command": "make"},
        )

        assert updated.name == "new"
        assert updated.command == "make"
        assert hooks_mod._hooks_by_bot["bot-A"][0].name == "new"

    async def test_when_update_with_wrong_bot_then_returns_none(
        self, db_session, patched_async_sessions
    ):
        existing = build_bot_hook("bot-A", name="mine")
        db_session.add(existing)
        await db_session.commit()

        result = await hooks_mod.update_hook(existing.id, "bot-B", {"name": "stolen"})

        assert result is None
        await db_session.refresh(existing)
        assert existing.name == "mine"

    async def test_when_update_for_missing_id_then_returns_none(
        self, db_session, patched_async_sessions
    ):
        result = await hooks_mod.update_hook(uuid.uuid4(), "bot-A", {"name": "ghost"})

        assert result is None


class TestDeleteHook:
    async def test_when_delete_called_then_row_gone_and_sibling_untouched(
        self, db_session, patched_async_sessions
    ):
        target = build_bot_hook("bot-A", name="delete-me")
        sibling = build_bot_hook("bot-A", name="keep-me")
        db_session.add_all([target, sibling])
        await db_session.commit()
        hooks_mod._hooks_by_bot["bot-A"] = [target, sibling]
        hooks_mod._cooldowns[target.id] = 1234.0

        ok = await hooks_mod.delete_hook(target.id, "bot-A")

        # Identity-map masks cross-session deletions; round-trip via SELECT.
        remaining = (
            await db_session.execute(select(BotHook.id).where(BotHook.bot_id == "bot-A"))
        ).scalars().all()

        assert ok is True
        assert remaining == [sibling.id]
        assert [h.id for h in hooks_mod._hooks_by_bot["bot-A"]] == [sibling.id]
        assert target.id not in hooks_mod._cooldowns

    async def test_when_delete_with_wrong_bot_then_returns_false(
        self, db_session, patched_async_sessions
    ):
        existing = build_bot_hook("bot-A", name="mine")
        db_session.add(existing)
        await db_session.commit()

        ok = await hooks_mod.delete_hook(existing.id, "bot-B")

        assert ok is False
        assert (await db_session.get(BotHook, existing.id)) is not None

    async def test_when_delete_missing_id_then_returns_false(
        self, db_session, patched_async_sessions
    ):
        ok = await hooks_mod.delete_hook(uuid.uuid4(), "bot-A")

        assert ok is False


class TestListHooks:
    async def test_when_list_called_then_only_target_bot_hooks_returned(
        self, db_session, patched_async_sessions
    ):
        mine_a = build_bot_hook("bot-A", name="mine-1")
        mine_b = build_bot_hook("bot-A", name="mine-2", enabled=False)
        other = build_bot_hook("bot-B", name="someone-else")
        db_session.add_all([mine_a, mine_b, other])
        await db_session.commit()

        result = await hooks_mod.list_hooks("bot-A")

        assert {h.id for h in result} == {mine_a.id, mine_b.id}


class TestLoadBotHooks:
    async def test_when_load_called_then_only_enabled_hooks_grouped_by_bot(
        self, db_session, patched_async_sessions
    ):
        a_on = build_bot_hook("bot-A", name="a-on", enabled=True)
        a_off = build_bot_hook("bot-A", name="a-off", enabled=False)
        b_on = build_bot_hook("bot-B", name="b-on", enabled=True)
        db_session.add_all([a_on, a_off, b_on])
        await db_session.commit()

        await hooks_mod.load_bot_hooks()

        assert {h.id for h in hooks_mod._hooks_by_bot["bot-A"]} == {a_on.id}
        assert {h.id for h in hooks_mod._hooks_by_bot["bot-B"]} == {b_on.id}


# ---------------------------------------------------------------------------
# Pure helpers — no DB
# ---------------------------------------------------------------------------


class TestMatchesConditions:
    def test_when_path_glob_matches_then_returns_true(self):
        hook = build_bot_hook("bot-A", conditions={"path": "/workspace/src/*.py"})

        assert hooks_mod._matches_conditions(hook, "/workspace/src/foo.py") is True

    def test_when_path_glob_does_not_match_then_returns_false(self):
        hook = build_bot_hook("bot-A", conditions={"path": "/workspace/src/*.py"})

        assert hooks_mod._matches_conditions(hook, "/workspace/docs/readme.md") is False

    def test_when_no_conditions_then_matches_anything(self):
        hook = build_bot_hook("bot-A", conditions={})

        assert hooks_mod._matches_conditions(hook, "/anywhere") is True

    def test_when_unknown_condition_key_then_no_match(self):
        hook = build_bot_hook("bot-A", conditions={"tool": "exec_command"})

        assert hooks_mod._matches_conditions(hook, "/workspace/x") is False


class TestFindMatchingHooks:
    def test_when_trigger_does_not_match_then_hook_excluded(self):
        h = build_bot_hook("bot-A", trigger="after_write", conditions={"path": "*"})
        hooks_mod._hooks_by_bot["bot-A"] = [h]

        result = hooks_mod._find_matching_hooks("bot-A", "before_access", "/x")

        assert result == []

    def test_when_no_hooks_for_bot_then_returns_empty(self):
        result = hooks_mod._find_matching_hooks("nobody", "before_access", "/x")

        assert result == []

    def test_when_hook_currently_executing_then_returns_empty(self):
        h = build_bot_hook("bot-A", trigger="before_access", conditions={"path": "*"})
        hooks_mod._hooks_by_bot["bot-A"] = [h]
        token = hooks_mod._hook_executing.set(True)
        try:
            assert hooks_mod._find_matching_hooks("bot-A", "before_access", "/x") == []
        finally:
            hooks_mod._hook_executing.reset(token)


class TestCheckCooldown:
    def test_when_first_call_then_allowed(self):
        h = build_bot_hook("bot-A", cooldown_seconds=60)

        assert hooks_mod._check_cooldown(h) is True

    def test_when_called_within_cooldown_then_blocked(self):
        h = build_bot_hook("bot-A", cooldown_seconds=60)

        first = hooks_mod._check_cooldown(h)
        second = hooks_mod._check_cooldown(h)

        assert (first, second) == (True, False)

    def test_when_cooldown_zero_then_consecutive_calls_allowed(self):
        h = build_bot_hook("bot-A", cooldown_seconds=0)

        first = hooks_mod._check_cooldown(h)
        second = hooks_mod._check_cooldown(h)

        assert (first, second) == (True, True)

    def test_when_two_distinct_hooks_then_cooldowns_independent(self):
        h1 = build_bot_hook("bot-A", cooldown_seconds=60)
        h2 = build_bot_hook("bot-A", cooldown_seconds=60)

        hooks_mod._check_cooldown(h1)

        assert hooks_mod._check_cooldown(h2) is True
        assert hooks_mod._check_cooldown(h1) is False


# ---------------------------------------------------------------------------
# Trigger pathways
# ---------------------------------------------------------------------------


class TestRunBeforeAccess:
    async def test_when_hook_succeeds_then_returns_none(
        self, bot_registry, workspace_exec_patch
    ):
        bot_registry.register("bot-A", workspace=_ws_enabled())
        h = build_bot_hook(
            "bot-A", trigger="before_access", conditions={"path": "/workspace/*"},
            on_failure="block",
        )
        hooks_mod._hooks_by_bot["bot-A"] = [h]

        result = await hooks_mod.run_before_access("bot-A", "/workspace/notes.md")

        assert result is None
        workspace_exec_patch.assert_awaited_once()

    async def test_when_hook_fails_with_on_failure_block_then_returns_error(
        self, bot_registry, workspace_exec_patch
    ):
        from app.services.workspace import ExecResult

        workspace_exec_patch.return_value = ExecResult(
            stdout="", stderr="boom", exit_code=2, truncated=False,
            duration_ms=1, workspace_type="host",
        )
        bot_registry.register("bot-A", workspace=_ws_enabled())
        h = build_bot_hook(
            "bot-A", name="guard", trigger="before_access",
            conditions={"path": "*"}, on_failure="block",
        )
        hooks_mod._hooks_by_bot["bot-A"] = [h]

        result = await hooks_mod.run_before_access("bot-A", "/workspace/x")

        assert result is not None
        assert "guard" in result and "boom" in result

    async def test_when_hook_fails_with_on_failure_warn_then_returns_none(
        self, bot_registry, workspace_exec_patch
    ):
        from app.services.workspace import ExecResult

        workspace_exec_patch.return_value = ExecResult(
            stdout="", stderr="meh", exit_code=2, truncated=False,
            duration_ms=1, workspace_type="host",
        )
        bot_registry.register("bot-A", workspace=_ws_enabled())
        h = build_bot_hook(
            "bot-A", trigger="before_access",
            conditions={"path": "*"}, on_failure="warn",
        )
        hooks_mod._hooks_by_bot["bot-A"] = [h]

        result = await hooks_mod.run_before_access("bot-A", "/workspace/x")

        assert result is None

    async def test_when_no_matching_hooks_then_returns_none_without_exec(
        self, workspace_exec_patch
    ):
        result = await hooks_mod.run_before_access("bot-A", "/workspace/x")

        assert result is None
        workspace_exec_patch.assert_not_awaited()

    async def test_when_bot_workspace_disabled_then_failure_blocks(
        self, bot_registry, workspace_exec_patch
    ):
        bot_registry.register("bot-A", workspace=WorkspaceConfig(enabled=False))
        h = build_bot_hook(
            "bot-A", name="guard", trigger="before_access",
            conditions={"path": "*"}, on_failure="block",
        )
        hooks_mod._hooks_by_bot["bot-A"] = [h]

        result = await hooks_mod.run_before_access("bot-A", "/workspace/x")

        assert result is not None
        assert "guard" in result
        workspace_exec_patch.assert_not_awaited()


class TestRunAfterExec:
    async def test_when_after_exec_succeeds_then_exec_invoked(
        self, bot_registry, workspace_exec_patch
    ):
        bot_registry.register("bot-A", workspace=_ws_enabled())
        h = build_bot_hook(
            "bot-A", trigger="after_exec", conditions={"path": "*"}, on_failure="warn",
        )
        hooks_mod._hooks_by_bot["bot-A"] = [h]

        await hooks_mod.run_after_exec("bot-A", "/workspace")

        workspace_exec_patch.assert_awaited_once()

    async def test_when_after_exec_fails_then_swallowed_no_raise(
        self, bot_registry, workspace_exec_patch
    ):
        from app.services.workspace import ExecResult

        workspace_exec_patch.return_value = ExecResult(
            stdout="", stderr="oops", exit_code=1, truncated=False,
            duration_ms=1, workspace_type="host",
        )
        bot_registry.register("bot-A", workspace=_ws_enabled())
        h = build_bot_hook(
            "bot-A", trigger="after_exec", conditions={"path": "*"}, on_failure="warn",
        )
        hooks_mod._hooks_by_bot["bot-A"] = [h]

        await hooks_mod.run_after_exec("bot-A", "/workspace")

        workspace_exec_patch.assert_awaited_once()


class TestScheduleAfterWrite:
    def test_when_no_matching_hook_then_no_timer_scheduled(self):
        hooks_mod.schedule_after_write("bot-unknown", "/workspace/x")

        assert hooks_mod._pending_after_write == {}

    def test_when_no_running_loop_then_returns_silently(self):
        h = build_bot_hook("bot-A", trigger="after_write", conditions={"path": "*"})
        hooks_mod._hooks_by_bot["bot-A"] = [h]

        hooks_mod.schedule_after_write("bot-A", "/workspace/x")

        assert hooks_mod._pending_after_write == {}

    async def test_when_called_twice_rapidly_then_second_call_replaces_pending_timer(self):
        h = build_bot_hook("bot-A", trigger="after_write", conditions={"path": "*"})
        hooks_mod._hooks_by_bot["bot-A"] = [h]

        hooks_mod.schedule_after_write("bot-A", "/workspace/x")
        first = hooks_mod._pending_after_write[h.id]
        hooks_mod.schedule_after_write("bot-A", "/workspace/y")
        second = hooks_mod._pending_after_write[h.id]

        assert first is not second
        second.cancel()
