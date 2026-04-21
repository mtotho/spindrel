"""Unit tests for Phase 7 — integration thread mirroring hooks + plumbing.

Covers:
1. ``IntegrationMeta`` thread hooks registered for Slack (apply /
   build / extract / persist).
2. ``apply_session_thread_refs`` rewrites a SlackTarget with ``thread_ts``
   + ``reply_in_thread=True`` when the session carries a ref.
3. Slack hook round-trip: ``build_thread_ref_from_message`` reads what
   ``persist_delivery_metadata`` wrote onto ``Message.metadata_``.
4. ``resolve_or_spawn_external_thread_session`` — existing-session,
   parent-found-via-metadata, and orphan-parent paths.
5. ``POST /messages/{id}/thread`` pre-mints ``integration_thread_refs``
   when the parent message has ``slack_ts`` + ``slack_channel``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

import integrations.slack.hooks  # noqa: F401 — registers IntegrationMeta at import time
from app.agent.hooks import get_integration_meta
from app.db.models import Channel, Message, Session
from app.services.dispatch_resolution import apply_session_thread_refs
from app.services.sub_sessions import (
    SESSION_TYPE_THREAD,
    resolve_or_spawn_external_thread_session,
    spawn_thread_session,
)
from integrations.slack.target import SlackTarget


pytestmark = pytest.mark.asyncio


class TestSlackIntegrationMetaHooks:
    def test_slack_registers_all_thread_hooks(self):
        meta = get_integration_meta("slack")
        assert meta is not None
        assert meta.apply_thread_ref is not None
        assert meta.build_thread_ref_from_message is not None
        assert meta.extract_thread_ref_from_dispatch is not None
        assert meta.persist_delivery_metadata is not None

    def test_extract_thread_ref_from_dispatch_with_thread(self):
        meta = get_integration_meta("slack")
        ref = meta.extract_thread_ref_from_dispatch(
            {"channel_id": "C1", "thread_ts": "1700000000.1", "token": "xoxb"}
        )
        assert ref == {"channel": "C1", "thread_ts": "1700000000.1"}

    def test_extract_thread_ref_from_dispatch_without_thread(self):
        meta = get_integration_meta("slack")
        assert meta.extract_thread_ref_from_dispatch(
            {"channel_id": "C1", "token": "xoxb"}
        ) is None
        assert meta.extract_thread_ref_from_dispatch({}) is None

    def test_build_thread_ref_from_message_prefers_explicit_thread_ts(self):
        meta = get_integration_meta("slack")
        ref = meta.build_thread_ref_from_message(
            {
                "source": "slack",
                "slack_channel": "C1",
                "slack_ts": "1700000000.2",
                "slack_thread_ts": "1700000000.1",
            }
        )
        # ``slack_thread_ts`` (the root of an existing Slack thread) wins over
        # the message's own ``slack_ts`` so a reply to a reply still binds to
        # the thread root rather than forking a fresh thread.
        assert ref == {"channel": "C1", "thread_ts": "1700000000.1"}

    def test_build_thread_ref_from_message_falls_back_to_slack_ts(self):
        meta = get_integration_meta("slack")
        ref = meta.build_thread_ref_from_message(
            {"slack_channel": "C1", "slack_ts": "1700000000.2"}
        )
        assert ref == {"channel": "C1", "thread_ts": "1700000000.2"}

    def test_build_thread_ref_returns_none_when_missing_channel(self):
        meta = get_integration_meta("slack")
        assert meta.build_thread_ref_from_message({"slack_ts": "1.1"}) is None
        assert meta.build_thread_ref_from_message({"slack_channel": "C1"}) is None
        assert meta.build_thread_ref_from_message({}) is None

    def test_apply_thread_ref_rewrites_target(self):
        meta = get_integration_meta("slack")
        target = SlackTarget(channel_id="C1", token="xoxb-test", thread_ts=None)
        rewritten = meta.apply_thread_ref(
            target, {"channel": "C1", "thread_ts": "1700000000.1"}
        )
        assert isinstance(rewritten, SlackTarget)
        assert rewritten.thread_ts == "1700000000.1"
        assert rewritten.reply_in_thread is True

    def test_apply_thread_ref_noop_on_non_slack_target(self):
        meta = get_integration_meta("slack")

        class _FakeTarget:
            pass

        t = _FakeTarget()
        assert meta.apply_thread_ref(t, {"thread_ts": "1.1"}) is t

    def test_persist_delivery_metadata_stamps_fields(self):
        meta = get_integration_meta("slack")
        target = SlackTarget(
            channel_id="C1",
            token="xoxb",
            thread_ts="1700000000.1",
            reply_in_thread=True,
        )
        out: dict = {}
        meta.persist_delivery_metadata(out, "1700000000.2", target)
        assert out == {
            "slack_ts": "1700000000.2",
            "slack_channel": "C1",
            "slack_thread_ts": "1700000000.1",
        }

    def test_persist_delivery_metadata_noop_without_external_id(self):
        meta = get_integration_meta("slack")
        target = SlackTarget(channel_id="C1", token="xoxb")
        out: dict = {}
        meta.persist_delivery_metadata(out, "", target)
        assert out == {}


class TestApplySessionThreadRefs:
    def test_swaps_slack_target_with_thread_ts(self):
        class _FakeSession:
            integration_thread_refs = {
                "slack": {"channel": "C1", "thread_ts": "1700000000.1"}
            }

        target = SlackTarget(channel_id="C1", token="xoxb-test")
        out = apply_session_thread_refs(_FakeSession(), [("slack", target)])
        assert len(out) == 1
        assert out[0][0] == "slack"
        assert out[0][1].thread_ts == "1700000000.1"
        assert out[0][1].reply_in_thread is True

    def test_noop_when_no_refs_on_session(self):
        class _FakeSession:
            integration_thread_refs = None

        target = SlackTarget(channel_id="C1", token="xoxb")
        out = apply_session_thread_refs(_FakeSession(), [("slack", target)])
        assert out[0][1] is target  # same instance, untouched

    def test_integration_without_ref_untouched(self):
        class _FakeSession:
            integration_thread_refs = {
                "slack": {"channel": "C1", "thread_ts": "1.1"}
            }

        other = SlackTarget(channel_id="C9", token="xoxb")
        out = apply_session_thread_refs(
            _FakeSession(), [("discord", other), ("slack", other)]
        )
        # Discord has no ref under "discord" key → left alone. Slack does.
        assert out[0][1] is other
        assert out[1][1].thread_ts == "1.1"


def engine_session(db_session):
    """Open a fresh ``AsyncSession`` bound to the same engine as ``db_session``.

    Used by the rollback-on-failure test: after ``persist_turn`` raises, the
    caller's transactional state is broken and reusing it to verify
    post-rollback state triggers greenlet errors in SQLAlchemy. A sibling
    session on the same engine avoids the contaminated state.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(
        db_session.bind, class_=AsyncSession, expire_on_commit=False,
    )
    return factory()


async def _make_channel_session(db_session, bot_id: str = "bot1"):
    parent_session = Session(
        id=uuid.uuid4(),
        client_id="web",
        bot_id=bot_id,
        channel_id=None,
        depth=0,
        session_type="channel",
    )
    db_session.add(parent_session)
    await db_session.flush()

    channel = Channel(
        id=uuid.uuid4(),
        name="test",
        bot_id=bot_id,
        active_session_id=parent_session.id,
    )
    parent_session.channel_id = channel.id
    db_session.add(channel)
    await db_session.flush()
    return channel, parent_session


async def _add_msg(db_session, *, session_id, role, content, metadata=None):
    msg = Message(
        id=uuid.uuid4(),
        session_id=session_id,
        role=role,
        content=content,
        metadata_=metadata or {},
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(msg)
    await db_session.flush()
    return msg


class TestResolveOrSpawnExternalThreadSession:
    async def test_returns_existing_session_when_ref_matches(self, db_session):
        channel, parent_session = await _make_channel_session(db_session)
        existing = Session(
            id=uuid.uuid4(),
            client_id="thread",
            bot_id="bot1",
            channel_id=None,
            parent_session_id=parent_session.id,
            depth=1,
            session_type=SESSION_TYPE_THREAD,
            integration_thread_refs={
                "slack": {"channel": "C1", "thread_ts": "1700000000.1"}
            },
        )
        db_session.add(existing)
        await db_session.flush()

        out = await resolve_or_spawn_external_thread_session(
            db_session,
            integration_id="slack",
            channel=channel,
            ref={"channel": "C1", "thread_ts": "1700000000.1"},
            bot_id="bot1",
        )
        assert out.id == existing.id

    async def test_spawns_anchored_at_matching_message_when_found(self, db_session):
        channel, parent_session = await _make_channel_session(db_session)
        # Parent message carries the Slack ts the inbound event refers to.
        parent_msg = await _add_msg(
            db_session,
            session_id=parent_session.id,
            role="assistant",
            content="hello",
            metadata={
                "slack_channel": "C1",
                "slack_ts": "1700000000.5",
            },
        )
        out = await resolve_or_spawn_external_thread_session(
            db_session,
            integration_id="slack",
            channel=channel,
            ref={"channel": "C1", "thread_ts": "1700000000.5"},
            bot_id="bot1",
        )
        assert out.session_type == SESSION_TYPE_THREAD
        assert out.parent_message_id == parent_msg.id
        assert (out.integration_thread_refs or {}).get("slack") == {
            "channel": "C1",
            "thread_ts": "1700000000.5",
        }

    async def test_orphan_spawn_when_no_message_matches(self, db_session):
        channel, _parent_session = await _make_channel_session(db_session)
        out = await resolve_or_spawn_external_thread_session(
            db_session,
            integration_id="slack",
            channel=channel,
            ref={"channel": "C1", "thread_ts": "1700000000.9"},
            bot_id="bot1",
        )
        assert out.session_type == SESSION_TYPE_THREAD
        assert out.parent_message_id is None
        assert (out.integration_thread_refs or {}).get("slack") == {
            "channel": "C1",
            "thread_ts": "1700000000.9",
        }


class TestResolveOrSpawnExternalThreadSessionRace:
    """Concurrent inbound replies for the same external thread must not spawn duplicates.

    SQLite doesn't enforce migration 231's partial unique index, so these
    tests drive the app-level retry branch by simulating an
    ``IntegrityError`` on the savepoint flush. In production on postgres
    the index is the actual gatekeeper; this test pins the handling path.
    """

    async def test_integrity_error_during_spawn_returns_winner(
        self, db_session, monkeypatch,
    ):
        """If the spawn flush raises IntegrityError, re-lookup returns the winner."""
        from sqlalchemy.exc import IntegrityError

        from app.services import sub_sessions as mod

        channel, parent_session = await _make_channel_session(db_session)

        ref = {"channel": "C1", "thread_ts": "1700000000.42"}

        # Seed the "winner" row — the concurrent insert that beat us.
        winner = Session(
            id=uuid.uuid4(),
            client_id="thread",
            bot_id="bot1",
            channel_id=None,
            parent_session_id=parent_session.id,
            root_session_id=parent_session.id,
            depth=1,
            session_type=SESSION_TYPE_THREAD,
            integration_thread_refs={"slack": ref},
        )
        db_session.add(winner)
        await db_session.flush()

        # Hide the winner from the initial lookup so the code falls through
        # to the spawn branch. The post-conflict re-lookup uses the real
        # helper and finds it.
        call_count = 0
        real_finder = mod._find_external_thread_session

        async def finder(db, integration_id, r):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None
            return await real_finder(db, integration_id, r)

        monkeypatch.setattr(
            "app.services.sub_sessions._find_external_thread_session",
            finder,
        )

        # Force the flush inside the savepoint to raise IntegrityError,
        # simulating the partial-unique-index rejection.
        real_flush = db_session.flush
        flush_calls = 0

        async def flaky_flush(*args, **kwargs):
            nonlocal flush_calls
            flush_calls += 1
            if flush_calls == 1:
                raise IntegrityError(
                    "uq_sessions_slack_thread_ref", None,
                    Exception("simulated unique violation"),
                )
            return await real_flush(*args, **kwargs)

        monkeypatch.setattr(db_session, "flush", flaky_flush)

        out = await mod.resolve_or_spawn_external_thread_session(
            db_session,
            integration_id="slack",
            channel=channel,
            ref=ref,
            bot_id="bot1",
        )
        assert out.id == winner.id
        assert call_count == 2  # initial miss, then post-conflict resolve

        # Restore the real flush before asserting final state.
        monkeypatch.setattr(db_session, "flush", real_flush)

        # Exactly one thread session exists for that ref — the winner,
        # not a second orphan from our rolled-back savepoint.
        from sqlalchemy import select

        rows = (await db_session.execute(
            select(Session).where(
                Session.session_type == SESSION_TYPE_THREAD,
            )
        )).scalars().all()
        matching = [
            s for s in rows
            if (s.integration_thread_refs or {}).get("slack") == ref
        ]
        assert len(matching) == 1
        assert matching[0].id == winner.id


class TestPersistTurnThreadOutboxAtomic:
    """Thread-session outbox enqueue must be transactional with message persist.

    The channel path enqueues outbox rows inside the same ``persist_turn``
    transaction as the message inserts; the thread path was previously
    committing messages first, then enqueueing in a fresh session with a
    broad try/except that silently swallowed failures. That split allowed
    the assistant message to be persisted with no outbox row, so the
    drainer never attempted delivery — a hard-to-detect message loss mode
    for threaded integrations. These tests pin the post-fix invariant.
    """

    async def _make_thread_session(self, db_session):
        channel, parent_session = await _make_channel_session(db_session)
        parent_msg = await _add_msg(
            db_session,
            session_id=parent_session.id,
            role="assistant",
            content="parent",
            metadata={"slack_channel": "C1", "slack_ts": "1700000000.5"},
        )
        thread = Session(
            id=uuid.uuid4(),
            client_id="thread",
            bot_id="bot1",
            channel_id=None,
            parent_session_id=parent_session.id,
            root_session_id=parent_session.id,
            depth=1,
            parent_message_id=parent_msg.id,
            session_type=SESSION_TYPE_THREAD,
            integration_thread_refs={
                "slack": {"channel": "C1", "thread_ts": "1700000000.5"},
            },
        )
        db_session.add(thread)
        await db_session.commit()
        return channel, thread

    async def test_thread_enqueue_success_writes_outbox_row_in_txn(
        self, db_session, monkeypatch,
    ):
        """Success path: one assistant message → one outbox row on the parent channel."""
        from unittest.mock import AsyncMock

        from app.db.models import Outbox
        from app.services.sessions import persist_turn
        from sqlalchemy import select

        channel, thread = await self._make_thread_session(db_session)
        fake_target = SlackTarget(channel_id="C1", token="xoxb-test")
        monkeypatch.setattr(
            "app.services.dispatch_resolution.resolve_targets",
            AsyncMock(return_value=[("slack", fake_target)]),
        )

        from app.agent.bots import BotConfig
        bot = BotConfig(id="bot1", name="Bot", model="gpt-4o", system_prompt="")

        await persist_turn(
            db_session, thread.id, bot,
            [{"role": "assistant", "content": "reply"}],
            from_index=0, channel_id=None,
        )

        rows = (await db_session.execute(
            select(Outbox).where(Outbox.channel_id == channel.id)
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].target_integration_id == "slack"
        # apply_session_thread_refs should have rewritten the target with the thread_ts.
        assert rows[0].target.get("thread_ts") == "1700000000.5"

    async def test_thread_enqueue_failure_rolls_back_message_insert(
        self, db_session, monkeypatch,
    ):
        """If outbox.enqueue raises mid-turn, the message insert is rolled back.

        Pre-fix, the assistant message was committed before the thread
        enqueue ran (in a separate session), so a failure left a persisted
        message with no corresponding outbox row. Post-fix the whole turn
        shares one transaction — a raise here must propagate AND take the
        message insert with it.
        """
        from unittest.mock import AsyncMock

        from app.db.models import Message as MessageModel, Outbox
        from app.services.sessions import persist_turn
        from sqlalchemy import select

        channel, thread = await self._make_thread_session(db_session)
        channel_id = channel.id
        thread_id = thread.id
        fake_target = SlackTarget(channel_id="C1", token="xoxb-test")
        monkeypatch.setattr(
            "app.services.dispatch_resolution.resolve_targets",
            AsyncMock(return_value=[("slack", fake_target)]),
        )
        monkeypatch.setattr(
            "app.services.outbox.enqueue",
            AsyncMock(side_effect=RuntimeError("simulated dispatch failure")),
        )

        from app.agent.bots import BotConfig
        bot = BotConfig(id="bot1", name="Bot", model="gpt-4o", system_prompt="")

        with pytest.raises(RuntimeError, match="simulated dispatch failure"):
            await persist_turn(
                db_session, thread_id, bot,
                [{"role": "assistant", "content": "reply"}],
                from_index=0, channel_id=None,
            )

        # Verify with a fresh session — the outer db_session is in a broken
        # transactional state after the raise and can't be safely reused.
        await db_session.rollback()
        async with engine_session(db_session) as verify:
            msgs = (await verify.execute(
                select(MessageModel).where(MessageModel.session_id == thread_id)
            )).scalars().all()
            assert msgs == []  # no orphan message persisted
            outbox_rows = (await verify.execute(
                select(Outbox).where(Outbox.channel_id == channel_id)
            )).scalars().all()
            assert outbox_rows == []  # no orphan outbox row either


class TestSpawnThreadSessionRefsPremint:
    async def test_pre_mint_via_api_endpoint_sets_slack_ref(self, db_session):
        """End-to-end: parent Message has slack_ts → spawn → refs set.

        Shape check only. The full HTTP round-trip lives in
        ``tests/integration/test_api_messages_thread.py`` — here we just
        exercise the pre-mint branch of the endpoint module by calling
        the registry walker directly.
        """
        from app.agent.hooks import iter_integration_meta

        parent_meta = {
            "source": "slack",
            "slack_channel": "C1",
            "slack_ts": "1700000000.5",
        }
        refs: dict = {}
        for meta in iter_integration_meta():
            if meta.build_thread_ref_from_message is None:
                continue
            ref = meta.build_thread_ref_from_message(parent_meta)
            if ref:
                refs[meta.integration_type] = ref

        assert "slack" in refs
        assert refs["slack"] == {"channel": "C1", "thread_ts": "1700000000.5"}

        # Anchor a real thread to verify the column accepts the dict shape.
        channel, parent_session = await _make_channel_session(db_session)
        parent_msg = await _add_msg(
            db_session,
            session_id=parent_session.id,
            role="assistant",
            content="hello",
            metadata=parent_meta,
        )
        sub = await spawn_thread_session(
            db_session, parent_message_id=parent_msg.id, bot_id="bot1"
        )
        sub.integration_thread_refs = refs
        await db_session.flush()
        assert sub.integration_thread_refs["slack"]["thread_ts"] == "1700000000.5"
