"""Phase E.2 drift-seam tests: persist_turn publish_to_bus swallows per-row failures.

Seam class: partial-commit + silent-UPDATE adjacent
Suspected drift: if publish_to_bus raises for one of N persisted rows, outbox delivers
all N to integrations but web-UI SSE subscribers miss that row. The per-row try/except
around publish_to_bus isolates failures, but callers cannot tell which rows were missed.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
import pytest_asyncio

from app.db.models import Session as SessionModel
from tests.factories import build_channel


def _make_bot_cfg(**overrides):
    from app.agent.bots import BotConfig
    defaults = dict(id="test-bot", name="Test", model="gpt-4o", system_prompt="")
    defaults.update(overrides)
    return BotConfig(**defaults)


@pytest_asyncio.fixture
async def seeded(db_session):
    ch = build_channel()
    sess = SessionModel(
        id=uuid.uuid4(),
        client_id="test-client",
        bot_id="test-bot",
        channel_id=ch.id,
    )
    db_session.add(ch)
    db_session.add(sess)
    await db_session.commit()
    return ch, sess


class TestPersistTurnPublishToBus:
    """E.2: publish_to_bus per-row swallow drift seam."""

    @pytest.mark.asyncio
    async def test_happy_path_two_rows_two_publish_calls(self, db_session, seeded):
        """Two persisted messages → two publish_to_bus calls, both with NEW_MESSAGE kind."""
        from app.domain.channel_events import ChannelEventKind
        from app.services.sessions import persist_turn

        ch, sess = seeded
        messages = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "world"}]

        mock_publish = MagicMock()
        with patch("app.services.dispatch_resolution.resolve_targets",
                   new=AsyncMock(return_value=[])), \
             patch("app.services.outbox_publish.publish_to_bus", mock_publish):
            await persist_turn(
                db_session, sess.id, _make_bot_cfg(), messages,
                from_index=0, channel_id=ch.id,
            )

        assert mock_publish.call_count == 2
        for c in mock_publish.call_args_list:
            _, event = c.args
            assert event.kind == ChannelEventKind.NEW_MESSAGE
            assert event.channel_id == ch.id

    @pytest.mark.asyncio
    async def test_publish_raise_on_second_call_first_still_published(
        self, db_session, seeded
    ):
        """publish_to_bus raising on 2nd row: first published, exception swallowed, function returns cleanly."""
        from app.services.sessions import persist_turn

        ch, sess = seeded
        messages = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "world"}]

        publish_call_count = 0

        def raise_on_second(*args, **kwargs):
            nonlocal publish_call_count
            publish_call_count += 1
            if publish_call_count == 2:
                raise RuntimeError("bus publish failed for second row")

        with patch("app.services.dispatch_resolution.resolve_targets",
                   new=AsyncMock(return_value=[])), \
             patch("app.services.outbox_publish.publish_to_bus", side_effect=raise_on_second):
            # Must not raise — per-row exception is swallowed
            result = await persist_turn(
                db_session, sess.id, _make_bot_cfg(), messages,
                from_index=0, channel_id=ch.id,
            )

        assert result is not None  # function returned cleanly
        assert publish_call_count == 2  # both rows attempted; second failure swallowed

    @pytest.mark.asyncio
    async def test_outbox_enqueue_called_even_when_bus_publish_fails(
        self, db_session, seeded
    ):
        """Durability contract: outbox.enqueue runs before bus publish in a separate txn.

        Even when publish_to_bus fails for every row, outbox.enqueue was already called
        inside the first commit — integrations still get delivery via the drainer.
        """
        from app.services.sessions import persist_turn

        ch, sess = seeded
        messages = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]

        mock_enqueue = AsyncMock()
        with patch("app.services.dispatch_resolution.resolve_targets",
                   new=AsyncMock(return_value=[("slack", MagicMock())])), \
             patch("app.services.outbox.enqueue", mock_enqueue), \
             patch("app.services.outbox_publish.publish_to_bus",
                   side_effect=RuntimeError("bus down")):
            await persist_turn(
                db_session, sess.id, _make_bot_cfg(), messages,
                from_index=0, channel_id=ch.id,
            )

        # outbox.enqueue was called once per message BEFORE bus publish attempted
        assert mock_enqueue.await_count == 2, (
            "outbox enqueue runs in txn-1 and is unaffected by txn-2 / bus publish failures"
        )

    @pytest.mark.asyncio
    async def test_no_publish_when_session_has_no_channel_ancestor(self, db_session):
        """When the session has neither channel_id nor a parent_session that resolves
        to a channel, publish is skipped entirely.

        Note: when ``channel_id`` arg is None but the session IS channel-bound
        (directly or via ``parent_session_id`` walkup — the sub-session case),
        persist_turn DOES publish on that resolved channel's bus so the
        run-view modal receives live events. This test pins the orphan-only
        drop path.
        """
        from app.services.sessions import persist_turn

        orphan_sess = SessionModel(
            id=uuid.uuid4(),
            client_id="test-client",
            bot_id="test-bot",
            channel_id=None,
            parent_session_id=None,
        )
        db_session.add(orphan_sess)
        await db_session.commit()

        messages = [{"role": "user", "content": "hello"}]

        mock_publish = MagicMock()
        with patch("app.services.outbox_publish.publish_to_bus", mock_publish):
            await persist_turn(
                db_session, orphan_sess.id, _make_bot_cfg(), messages,
                from_index=0,  # no channel_id — session is orphan → no bus target
            )

        mock_publish.assert_not_called()

    async def test_publishes_via_parent_walkup_when_session_is_sub_session(
        self, db_session, seeded,
    ):
        """Sub-session bridge: channel_id arg None + session has parent channel →
        publish hits the parent channel's bus (enables the run-view modal)."""
        from app.services.sessions import persist_turn

        ch, parent_sess = seeded
        sub_sess = SessionModel(
            id=uuid.uuid4(),
            client_id="task",
            bot_id="test-bot",
            channel_id=None,
            parent_session_id=parent_sess.id,
            session_type="pipeline_run",
        )
        db_session.add(sub_sess)
        await db_session.commit()

        messages = [{"role": "assistant", "content": "step output"}]

        mock_publish = MagicMock()
        with patch("app.services.outbox_publish.publish_to_bus", mock_publish):
            await persist_turn(
                db_session, sub_sess.id, _make_bot_cfg(), messages,
                from_index=0,  # no channel_id — resolved via parent_session walkup
            )

        # Publish fires on the PARENT channel's id; the row's session_id is
        # still the sub-session so list endpoints naturally exclude it.
        assert mock_publish.call_count == 1
        (published_channel_id, _event) = mock_publish.call_args.args
        assert published_channel_id == ch.id
