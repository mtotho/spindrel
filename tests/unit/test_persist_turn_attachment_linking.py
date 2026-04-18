"""Phase E.1 drift-seam tests: persist_turn attachment-link is a second transaction.

Seam class: partial-commit
Suspected drift: messages + outbox commit in one txn; attachment UPDATE runs in a
second commit inside a try/except that swallows. A partial failure leaves the channel
with persisted messages but attachments orphaned (message_id=NULL). Candidate root
cause of the 'Slack image attachment doesn't show up in web UI' loose end.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.models import Attachment, Channel, Message, Session as SessionModel
from tests.factories import build_attachment, build_channel


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


def _no_outbox_patches():
    return (
        patch("app.services.dispatch_resolution.resolve_targets",
              new=AsyncMock(return_value=[])),
        patch("app.services.outbox_publish.publish_to_bus"),
    )


class TestPersistTurnAttachmentLinking:
    """E.1: attachment-link second-transaction drift seam."""

    @pytest.mark.asyncio
    async def test_user_attachment_links_to_first_user_message(
        self, db_session, seeded
    ):
        """User-uploaded attachment (posted_by=None) links to first user message."""
        from app.services.sessions import persist_turn

        ch, sess = seeded
        att = build_attachment(channel_id=ch.id, posted_by=None, message_id=None)
        db_session.add(att)
        await db_session.commit()

        messages = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "reply"}]

        with patch("app.services.dispatch_resolution.resolve_targets",
                   new=AsyncMock(return_value=[])), \
             patch("app.services.outbox_publish.publish_to_bus"):
            first_user_id = await persist_turn(
                db_session, sess.id, _make_bot_cfg(), messages,
                from_index=0, channel_id=ch.id,
            )

        assert first_user_id is not None
        await db_session.refresh(att)
        assert att.message_id == first_user_id

    @pytest.mark.asyncio
    async def test_bot_attachment_links_to_last_assistant_message(
        self, db_session, seeded
    ):
        """Bot-created attachment (posted_by set) links to last assistant message."""
        from app.services.sessions import persist_turn

        ch, sess = seeded
        att = build_attachment(channel_id=ch.id, posted_by="bot:test-bot", message_id=None)
        db_session.add(att)
        await db_session.commit()

        messages = [
            {"role": "user", "content": "request"},
            {"role": "assistant", "content": "first reply"},
            {"role": "assistant", "content": "second reply"},
        ]

        with patch("app.services.dispatch_resolution.resolve_targets",
                   new=AsyncMock(return_value=[])), \
             patch("app.services.outbox_publish.publish_to_bus"):
            await persist_turn(
                db_session, sess.id, _make_bot_cfg(), messages,
                from_index=0, channel_id=ch.id,
            )

        result = await db_session.execute(
            select(Message)
            .where(Message.session_id == sess.id, Message.role == "assistant")
            .order_by(Message.created_at.desc())
        )
        last_asst = result.scalars().first()
        assert last_asst is not None

        await db_session.refresh(att)
        assert att.message_id == last_asst.id

    @pytest.mark.asyncio
    async def test_two_attachments_correct_messages_sibling_channel_untouched(
        self, db_session, seeded
    ):
        """User+bot attachments each link correctly; sibling channel's attachment untouched."""
        from app.services.sessions import persist_turn

        ch, sess = seeded
        sibling_ch = build_channel()
        db_session.add(sibling_ch)

        user_att = build_attachment(channel_id=ch.id, posted_by=None, message_id=None)
        bot_att = build_attachment(channel_id=ch.id, posted_by="bot:test-bot", message_id=None)
        sibling_att = build_attachment(channel_id=sibling_ch.id, posted_by=None, message_id=None)
        db_session.add(user_att)
        db_session.add(bot_att)
        db_session.add(sibling_att)
        await db_session.commit()

        messages = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "world"}]

        with patch("app.services.dispatch_resolution.resolve_targets",
                   new=AsyncMock(return_value=[])), \
             patch("app.services.outbox_publish.publish_to_bus"):
            first_user_id = await persist_turn(
                db_session, sess.id, _make_bot_cfg(), messages,
                from_index=0, channel_id=ch.id,
            )

        result = await db_session.execute(
            select(Message).where(Message.session_id == sess.id, Message.role == "assistant")
        )
        asst_msg = result.scalars().first()
        assert asst_msg is not None

        await db_session.refresh(user_att)
        await db_session.refresh(bot_att)
        await db_session.refresh(sibling_att)

        assert user_att.message_id == first_user_id
        assert bot_att.message_id == asst_msg.id
        assert sibling_att.message_id is None  # different channel → untouched

    @pytest.mark.asyncio
    async def test_no_assistant_message_bot_attachment_stays_orphaned(
        self, db_session, seeded
    ):
        """No assistant msg in batch → bot attachment (posted_by set) stays message_id=None."""
        from app.services.sessions import persist_turn

        ch, sess = seeded
        bot_att = build_attachment(channel_id=ch.id, posted_by="bot:test-bot", message_id=None)
        user_att = build_attachment(channel_id=ch.id, posted_by=None, message_id=None)
        db_session.add(bot_att)
        db_session.add(user_att)
        await db_session.commit()

        messages = [{"role": "user", "content": "hi"}]  # no assistant message

        with patch("app.services.dispatch_resolution.resolve_targets",
                   new=AsyncMock(return_value=[])), \
             patch("app.services.outbox_publish.publish_to_bus"):
            first_user_id = await persist_turn(
                db_session, sess.id, _make_bot_cfg(), messages,
                from_index=0, channel_id=ch.id,
            )

        await db_session.refresh(bot_att)
        await db_session.refresh(user_att)

        assert bot_att.message_id is None  # no assistant msg → no link
        assert user_att.message_id == first_user_id

    @pytest.mark.asyncio
    async def test_second_commit_failure_leaves_attachments_orphaned(
        self, db_session, seeded
    ):
        """Drift pin: 2nd commit failure → messages committed, attachment stays message_id=NULL.

        Documents the non-atomic contract: message inserts commit atomically in txn-1;
        attachment UPDATE runs in txn-2 inside a try/except. If txn-2 fails silently,
        callers see no exception but attachment.message_id remains NULL.
        """
        from app.services.sessions import persist_turn

        ch, sess = seeded
        att = build_attachment(channel_id=ch.id, posted_by=None, message_id=None)
        db_session.add(att)
        await db_session.commit()

        commit_count = 0
        real_commit = db_session.commit

        async def fail_on_second_commit():
            nonlocal commit_count
            commit_count += 1
            if commit_count == 2:
                raise RuntimeError("forced second commit failure — attachment txn")
            return await real_commit()

        db_session.commit = fail_on_second_commit

        messages = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "reply"}]

        # Capture IDs before the rollback to avoid SA lazy-load after expiry
        sess_id = sess.id
        att_id = att.id

        try:
            with patch("app.services.dispatch_resolution.resolve_targets",
                       new=AsyncMock(return_value=[])), \
                 patch("app.services.outbox_publish.publish_to_bus"):
                # persist_turn swallows the second commit error — no exception raised
                first_user_id = await persist_turn(
                    db_session, sess_id, _make_bot_cfg(), messages,
                    from_index=0, channel_id=ch.id,
                )
        finally:
            db_session.commit = real_commit
            await db_session.rollback()  # discard the uncommitted attachment UPDATE

        assert commit_count == 2, "proves two separate commits exist"
        assert first_user_id is not None

        # After rollback, txn-2's UPDATE is gone — reload shows message_id still NULL
        fresh_att = await db_session.get(Attachment, att_id)
        assert fresh_att is not None
        assert fresh_att.message_id is None, (
            "partial-commit contract: attachment stays NULL when txn-2 fails"
        )

        # Messages from txn-1 are still in the DB
        msgs = (await db_session.execute(
            select(Message).where(Message.session_id == sess_id)
        )).scalars().all()
        assert len(msgs) == 2, "messages from txn-1 survive the txn-2 failure"
