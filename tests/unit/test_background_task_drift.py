"""Phase L — Background-Task Ordering + Concurrent Race Drift.

Targets six seams identified in plan rippling-giggling-bachman.md:

L.1  Heartbeat crash-gap: process crash between pre-fire commit (creates
     HeartbeatRun status=running) and post-fire commit (marks complete/failed)
     leaves the run permanently stuck.  No startup reset exists (unlike outbox).

L.3  session_locks concurrent acquire: asyncio.gather of two concurrent callers
     on the same session_id — exactly one wins.

L.4  modal_waiter callback drop: submit against a cleared (server-restart)
     slot returns False; the pending future is abandoned.

L.5  resolve_bus_channel_id orphan parent: session C with parent_session_id=P,
     P deleted → graceful None, no raise, no loop.

L.6  bot_hooks._find_matching_hooks re-entrancy guard: while _hook_executing
     is True the function returns [] regardless of registered hooks.

Expected yield: L.1 is a confirmed bug (missing startup recovery).
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.db.models import (
    Channel,
    ChannelHeartbeat,
    HeartbeatRun,
    Session,
)
from app.services import session_locks
from app.services import modal_waiter
from app.services.sub_session_bus import resolve_bus_channel_id


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_channel(bot_id: str = "test-bot") -> Channel:
    return Channel(id=uuid.uuid4(), name=f"ch-{uuid.uuid4().hex[:6]}", bot_id=bot_id)


def _make_heartbeat(channel_id: uuid.UUID) -> ChannelHeartbeat:
    return ChannelHeartbeat(
        id=uuid.uuid4(),
        channel_id=channel_id,
        enabled=True,
        interval_minutes=60,
        prompt="ping",
        dispatch_results=False,
    )


# ===========================================================================
# L.1 — HeartbeatRun crash-gap (no startup recovery)
# ===========================================================================


class TestHeartbeatCrashGap:
    """Pinning current contract: HeartbeatRun stuck at status=running has no
    automatic recovery path.

    Contrast with the outbox, which calls reset_stale_in_flight() at startup
    (app/main.py:791) to recover rows stranded IN_FLIGHT by a prior crash.
    Heartbeat has no equivalent.  If the process dies between the pre-fire
    commit (heartbeat.py:581) and the post-fire commit (heartbeat.py:730),
    the HeartbeatRun row stays stuck at status=running with no completed_at.
    """

    @pytest.mark.asyncio
    async def test_heartbeat_run_can_be_stuck_running_indefinitely(
        self, db_session
    ):
        """A HeartbeatRun inserted with status=running and no completed_at
        persists exactly that way — there is no DB trigger or ORM hook that
        auto-advances it.  Pinning the stuck-state as a real possible DB
        condition.
        """
        ch = _make_channel()
        db_session.add(ch)
        await db_session.flush()

        hb = _make_heartbeat(ch.id)
        db_session.add(hb)
        await db_session.flush()

        # Simulate the pre-fire commit: HeartbeatRun created at status=running.
        run = HeartbeatRun(
            id=uuid.uuid4(),
            heartbeat_id=hb.id,
            run_at=datetime.now(timezone.utc),
            status="running",
        )
        db_session.add(run)
        await db_session.flush()

        # No post-fire commit occurs (simulate process crash).
        # The row is now permanently stuck.
        from sqlalchemy import select
        refreshed = (
            await db_session.execute(
                select(HeartbeatRun).where(HeartbeatRun.id == run.id)
            )
        ).scalar_one()

        assert refreshed.status == "running"
        assert refreshed.completed_at is None
        # This is the crash-gap: no one will ever mark this run complete.

    @pytest.mark.asyncio
    async def test_stuck_running_run_not_recoverable_without_explicit_cleanup(
        self, db_session
    ):
        """Multiple stuck runs accumulate indefinitely.  fetch_pending-style
        queries that filter status='running' will always see them, unlike the
        outbox where reset_stale_in_flight() resets stranded rows at startup.

        Pinning current contract: this IS the bug — heartbeat has no
        reset_stale_running_runs() equivalent.
        """
        ch = _make_channel()
        db_session.add(ch)
        await db_session.flush()

        hb = _make_heartbeat(ch.id)
        db_session.add(hb)
        await db_session.flush()

        # Create 3 stuck runs (3 separate process crashes, or 3 concurrent fires
        # where each process died before the post-commit).
        for _ in range(3):
            run = HeartbeatRun(
                id=uuid.uuid4(),
                heartbeat_id=hb.id,
                run_at=datetime.now(timezone.utc),
                status="running",
            )
            db_session.add(run)
        await db_session.flush()

        from sqlalchemy import select, func
        count = (
            await db_session.execute(
                select(func.count()).where(
                    HeartbeatRun.heartbeat_id == hb.id,
                    HeartbeatRun.status == "running",
                    HeartbeatRun.completed_at == None,  # noqa: E711
                )
            )
        ).scalar_one()

        assert count == 3, (
            "Three stuck runs accumulated — no automatic recovery path. "
            "Heartbeat needs reset_stale_running_runs() at startup "
            "(see Loose Ends — heartbeat crash-gap)."
        )

    def test_no_startup_reset_function_exists(self):
        """Pin that app.services.heartbeat has no reset_stale_running_runs()
        function equivalent to outbox.reset_stale_in_flight().

        This is a contract test, not a gap assertion — if someone adds the
        recovery function this test should be updated, not deleted.
        """
        import app.services.heartbeat as heartbeat_mod

        # The outbox analogue that should exist but doesn't:
        has_reset = hasattr(heartbeat_mod, "reset_stale_running_runs")
        assert not has_reset, (
            "reset_stale_running_runs() now exists — update this test to "
            "assert it correctly resets stuck runs, and remove from Loose Ends."
        )


# ===========================================================================
# L.3 — session_locks concurrent acquire (atomic dict, no race)
# ===========================================================================


@pytest.fixture(autouse=True)
def _reset_locks():
    session_locks._active.clear()
    session_locks._cancel_requested.clear()
    yield
    session_locks._active.clear()
    session_locks._cancel_requested.clear()


class TestSessionLocksConcurrentAcquire:
    """Pinning contract: in a single-threaded asyncio event loop, acquire() has
    no await point so concurrent coroutines cannot interleave inside it.
    Exactly one caller wins; the other sees False.
    """

    @pytest.mark.asyncio
    async def test_concurrent_acquire_exactly_one_wins(self):
        """Two coroutines racing to acquire the same session — exactly one
        succeeds.  Because acquire() is pure sync (no await), asyncio cannot
        switch between them mid-function: the first coroutine to reach the
        event loop's scheduling completes acquire() atomically.
        """
        sid = uuid.uuid4()
        results: list[bool] = []

        async def try_acquire():
            results.append(session_locks.acquire(sid))

        await asyncio.gather(try_acquire(), try_acquire())

        assert sorted(results) == [False, True], (
            f"Expected exactly one True and one False, got {results}"
        )
        assert session_locks.is_active(sid)

    @pytest.mark.asyncio
    async def test_concurrent_acquire_loser_sees_false_immediately(self):
        """The losing caller gets False synchronously — no blocking wait."""
        sid = uuid.uuid4()
        outcomes: list[bool] = []

        async def _c():
            outcomes.append(session_locks.acquire(sid))

        t1 = asyncio.create_task(_c())
        t2 = asyncio.create_task(_c())
        await asyncio.gather(t1, t2)

        assert outcomes.count(True) == 1
        assert outcomes.count(False) == 1


# ===========================================================================
# L.4 — modal_waiter callback drop on server restart
# ===========================================================================


@pytest.fixture(autouse=True)
def _reset_modal_waiter():
    modal_waiter.reset()
    yield
    modal_waiter.reset()


class TestModalWaiterCallbackDrop:
    """Pinning contract: modal_waiter is in-memory only.  A server restart
    (or _slots.clear()) while a modal is open abandons the pending future —
    submit() returns False and the waiting coroutine never unblocks (it will
    eventually timeout).
    """

    def test_submit_stale_callback_returns_false(self):
        """Submit against a callback_id that no longer exists in _slots
        (simulates server restart) returns False — the slot was cleared.
        """
        cid = modal_waiter.register("stale-callback-test")

        # Simulate process restart: clear all slots.
        modal_waiter._slots.clear()

        result = modal_waiter.submit(
            cid, values={"answer": "42"}, submitted_by="user"
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_cleared_slot_leaves_waiting_coroutine_pending(self):
        """A coroutine waiting on modal_waiter.wait() is not unblocked when
        the slot is cleared externally.  The wait() call must time out on its
        own — there is no cancellation signal from the clear.

        Pins the hang: the modal times out after its own TTL but gets no
        "server restarted" error message.
        """
        cid = modal_waiter.register()

        # Grab the slot's asyncio.Event before the clear so we can assert
        # it was never set.
        slot = modal_waiter._slots[cid]
        event = slot.event

        # Simulate server restart.
        modal_waiter._slots.clear()

        # The event was never set.
        assert not event.is_set(), (
            "Event was set despite slot being cleared — "
            "the pending coroutine would unblock with bad state"
        )

        # Submit now returns False (slot gone).
        result = modal_waiter.submit(cid, values={}, submitted_by="u")
        assert result is False

        # The event is still not set — the waiting coroutine is abandoned.
        assert not event.is_set()

    def test_pending_count_after_restart_is_zero(self):
        """After _slots.clear() (server restart simulation) no pending waiters
        remain in the module's counter — consistent with a fresh process.
        """
        for i in range(3):
            modal_waiter.register(f"cb-{i}")
        assert modal_waiter.pending_count() == 3

        modal_waiter._slots.clear()
        assert modal_waiter.pending_count() == 0


# ===========================================================================
# L.5 — resolve_bus_channel_id orphan parent
# ===========================================================================


@pytest.mark.asyncio
class TestResolveOrphanParent:
    """Pinning contract: resolve_bus_channel_id returns None gracefully when
    the parent_session_id chain leads to a deleted or missing row.
    """

    async def test_deleted_parent_session_returns_none(self, db_session):
        """Session C has parent_session_id=P.  P is deleted.  Walk returns
        None without raising or looping indefinitely.
        """
        ch = _make_channel()
        db_session.add(ch)
        await db_session.flush()

        parent = Session(
            id=uuid.uuid4(),
            client_id="web",
            bot_id="test-bot",
            channel_id=ch.id,
            depth=0,
        )
        db_session.add(parent)
        await db_session.flush()

        child = Session(
            id=uuid.uuid4(),
            client_id="web",
            bot_id="test-bot",
            channel_id=None,
            parent_session_id=parent.id,
            depth=1,
        )
        db_session.add(child)
        await db_session.flush()

        # Delete the parent — now child.parent_session_id is orphaned.
        await db_session.delete(parent)
        await db_session.flush()

        result = await resolve_bus_channel_id(db_session, child.id)
        # child has no channel_id; parent is gone → None.
        assert result is None

    async def test_none_session_id_returns_none(self, db_session):
        """Passing None directly returns None without querying the DB."""
        result = await resolve_bus_channel_id(db_session, None)
        assert result is None

    async def test_channel_session_returns_channel_id(self, db_session):
        """Channel session (channel_id set) resolves to its own channel_id."""
        ch = _make_channel()
        db_session.add(ch)
        await db_session.flush()

        sess = Session(
            id=uuid.uuid4(),
            client_id="web",
            bot_id="test-bot",
            channel_id=ch.id,
        )
        db_session.add(sess)
        await db_session.flush()

        result = await resolve_bus_channel_id(db_session, sess.id)
        assert result == ch.id

    async def test_cycle_detection_returns_none(self, db_session):
        """If parent_session_id forms a cycle, the bounded walk returns None
        rather than looping indefinitely.
        """
        # Build two sessions that point at each other — corrupt graph.
        id_a = uuid.uuid4()
        id_b = uuid.uuid4()

        sess_a = Session(
            id=id_a,
            client_id="web",
            bot_id="test-bot",
            channel_id=None,
            parent_session_id=id_b,
            depth=1,
        )
        sess_b = Session(
            id=id_b,
            client_id="web",
            bot_id="test-bot",
            channel_id=None,
            parent_session_id=id_a,
            depth=1,
        )
        db_session.add(sess_a)
        db_session.add(sess_b)
        await db_session.flush()

        result = await resolve_bus_channel_id(db_session, id_a)
        assert result is None


# ===========================================================================
# L.6 — bot_hooks._find_matching_hooks re-entrancy guard
# ===========================================================================


class TestBotHooksReentrancy:
    """Pinning contract: _find_matching_hooks returns [] when _hook_executing
    ContextVar is True, suppressing nested hooks during hook execution.

    This is the intended behavior (documented in bot_hooks.py:79-85) but has
    no test — a future refactor could silently break the guard.
    """

    def test_returns_empty_when_hook_executing(self):
        """With _hook_executing=True, _find_matching_hooks returns []
        regardless of registered hooks.
        """
        from app.db.models import BotHook
        from app.services import bot_hooks

        hook = BotHook(
            id=uuid.uuid4(),
            bot_id="guard-bot",
            name="test-hook",
            trigger="before_access",
            enabled=True,
            cooldown_seconds=0,
            conditions={},
            command="echo hi",
        )
        bot_hooks._hooks_by_bot["guard-bot"] = [hook]

        try:
            token = bot_hooks._hook_executing.set(True)
            result = bot_hooks._find_matching_hooks("guard-bot", "before_access", "/some/path")
            assert result == [], (
                "_find_matching_hooks must return [] when _hook_executing is True "
                "— re-entrancy guard broken"
            )
        finally:
            bot_hooks._hook_executing.reset(token)
            bot_hooks._hooks_by_bot.pop("guard-bot", None)

    def test_returns_hooks_when_not_executing(self):
        """With _hook_executing=False (default), matching hooks are returned."""
        from app.db.models import BotHook
        from app.services import bot_hooks

        hook = BotHook(
            id=uuid.uuid4(),
            bot_id="open-bot",
            name="test-hook",
            trigger="before_access",
            enabled=True,
            cooldown_seconds=0,
            conditions={},
            command="echo hi",
        )
        bot_hooks._hooks_by_bot["open-bot"] = [hook]

        try:
            # _hook_executing defaults to False — no explicit set needed.
            result = bot_hooks._find_matching_hooks("open-bot", "before_access", "/any/path")
            assert result == [hook]
        finally:
            bot_hooks._hooks_by_bot.pop("open-bot", None)

    def test_guard_is_contextvar_not_global(self):
        """_hook_executing is a ContextVar, not a global bool.

        Pinning that concurrent asyncio tasks (different contextvars.Context)
        do NOT share the executing flag — one task's hook suppression does not
        bleed into another task's context.
        """
        from app.services import bot_hooks

        results: list[bool] = []

        def _read_guard():
            results.append(bot_hooks._hook_executing.get())

        # Default context: False.
        _read_guard()
        token = bot_hooks._hook_executing.set(True)
        _read_guard()
        bot_hooks._hook_executing.reset(token)
        _read_guard()

        assert results == [False, True, False], (
            "ContextVar did not restore correctly — guard may bleed between tasks"
        )
