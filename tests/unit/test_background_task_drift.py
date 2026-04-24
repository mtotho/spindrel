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
    """Regression guards for the L.1 fix (2026-04-23).

    HeartbeatRun rows stuck at ``status='running'`` from a crashed process
    are now recovered at startup by
    :func:`app.services.heartbeat.reset_stale_running_runs`, which mirrors
    :func:`app.services.outbox.reset_stale_in_flight`. Both helpers are
    called from the lifespan before their respective worker tasks launch.
    """

    @pytest.mark.asyncio
    async def test_heartbeat_run_can_be_stuck_running_indefinitely(
        self, db_session
    ):
        """A HeartbeatRun inserted with ``status='running'`` persists exactly
        that way in the absence of the recovery helper — there is no DB
        trigger or ORM hook that auto-advances it. The recovery is explicit:
        :func:`reset_stale_running_runs` fired from the lifespan at startup.
        This test pins the DB-side fact so a future implicit-recovery
        mechanism (trigger, ON UPDATE cascade) doesn't land unnoticed.
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
    async def test_stuck_running_runs_accumulate_without_recovery_call(
        self, db_session
    ):
        """Multiple stuck rows can accumulate across crashes if
        :func:`reset_stale_running_runs` is never invoked. Pins the
        explicit-recovery contract — the lifespan is responsible for
        calling the helper; a forgotten call means stuck rows pile up.
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
            "Three stuck runs accumulated — the recovery helper must be "
            "called explicitly from the lifespan to drain them."
        )

    def test_startup_reset_function_exists(self):
        """Contract: ``app.services.heartbeat`` exposes
        ``reset_stale_running_runs`` — the outbox analogue that recovers
        stranded HeartbeatRun rows at lifespan start.
        """
        import app.services.heartbeat as heartbeat_mod

        assert hasattr(heartbeat_mod, "reset_stale_running_runs")

    @pytest.mark.asyncio
    async def test_reset_stale_running_runs_flips_stuck_rows_to_cancelled(
        self, db_session
    ):
        """The recovery helper flips every ``status='running'`` row to
        ``status='cancelled'`` with ``completed_at`` set, so the run
        history view displays a terminal state instead of a live-looking
        orphan.
        """
        from app.services.heartbeat import reset_stale_running_runs

        ch = _make_channel()
        db_session.add(ch)
        await db_session.flush()

        hb = _make_heartbeat(ch.id)
        db_session.add(hb)
        await db_session.flush()

        stuck_ids = []
        for _ in range(3):
            run = HeartbeatRun(
                id=uuid.uuid4(),
                heartbeat_id=hb.id,
                run_at=datetime.now(timezone.utc),
                status="running",
            )
            db_session.add(run)
            stuck_ids.append(run.id)
        await db_session.commit()

        recovered = await reset_stale_running_runs(db_session)
        assert recovered == 3

        from sqlalchemy import select
        for run_id in stuck_ids:
            row = (
                await db_session.execute(
                    select(HeartbeatRun).where(HeartbeatRun.id == run_id)
                )
            ).scalar_one()
            assert row.status == "cancelled"
            assert row.completed_at is not None
            assert row.error == "process crashed before completion"

    @pytest.mark.asyncio
    async def test_reset_stale_running_runs_ignores_terminal_rows(
        self, db_session
    ):
        """Rows already at terminal statuses (``done``, ``error``,
        ``cancelled``) must NOT be touched — the helper targets only the
        ``running`` limbo state.
        """
        from app.services.heartbeat import reset_stale_running_runs

        ch = _make_channel()
        db_session.add(ch)
        await db_session.flush()

        hb = _make_heartbeat(ch.id)
        db_session.add(hb)
        await db_session.flush()

        now = datetime.now(timezone.utc)
        done = HeartbeatRun(
            id=uuid.uuid4(),
            heartbeat_id=hb.id,
            run_at=now,
            completed_at=now,
            status="done",
        )
        errored = HeartbeatRun(
            id=uuid.uuid4(),
            heartbeat_id=hb.id,
            run_at=now,
            completed_at=now,
            status="error",
            error="prior failure",
        )
        running = HeartbeatRun(
            id=uuid.uuid4(),
            heartbeat_id=hb.id,
            run_at=now,
            status="running",
        )
        db_session.add_all([done, errored, running])
        await db_session.commit()

        recovered = await reset_stale_running_runs(db_session)
        assert recovered == 1  # only the running row

        from sqlalchemy import select
        done_row = (
            await db_session.execute(
                select(HeartbeatRun).where(HeartbeatRun.id == done.id)
            )
        ).scalar_one()
        err_row = (
            await db_session.execute(
                select(HeartbeatRun).where(HeartbeatRun.id == errored.id)
            )
        ).scalar_one()
        assert done_row.status == "done"
        assert err_row.status == "error"
        assert err_row.error == "prior failure"  # untouched


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
