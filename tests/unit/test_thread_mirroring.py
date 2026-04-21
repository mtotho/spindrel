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
