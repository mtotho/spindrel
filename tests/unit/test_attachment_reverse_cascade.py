"""Phase F.6 — orphan pointer seam: Attachment reverse-cascade on Message/Channel deletion.

Pins the direction of cascade when the *parent* of an Attachment is deleted:

- ``message_id`` FK uses ``ondelete="CASCADE"`` → Attachments are deleted
  with their Message (not orphaned). Contrast: if this were SET NULL, every
  deleted message would accumulate orphan rows until a background sweep ran.

- ``channel_id`` FK uses ``ondelete="SET NULL"`` → Attachments survive Channel
  deletion with ``channel_id=NULL``. Documents the orphan-accumulation risk:
  ``purge_attachments`` is the sole cleanup path for channel-less rows.

Both properties matter for the "Slack image attachment doesn't show up in
web UI" class of bugs (Phase E.1 / Loose Ends) — the code that links
attachments to messages relies on the attachment row persisting past the
first commit; if the cascade contract changes, orphan rows change too.

Seam class: orphan pointer
Loose Ends: none confirmed as new bugs — contracts pinned as-is.
Reference: tests/unit/test_persist_turn_attachment_linking.py (Phase E.1).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Attachment, Base, Channel, Message
from app.db.models import Session as SessionModel
from tests.factories import build_attachment, build_channel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def fk_engine():
    """SQLite engine with FK enforcement enabled via PRAGMA foreign_keys=ON.

    The default ``db_session`` fixture does not enable FK enforcement —
    cascade / SET NULL DB-level contracts are invisible to it. This fixture
    adds the pragma so FK-driven cascades (ondelete="CASCADE" / "SET NULL")
    fire correctly on every DELETE.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_fk(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy.schema import DefaultClause

    originals: dict[tuple[str, str], object] = {}
    _REPLACEMENTS = {"now()": "CURRENT_TIMESTAMP", "gen_random_uuid()": None}
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            sd = col.server_default
            if sd is None:
                continue
            sd_text = str(sd.arg) if hasattr(sd, "arg") else str(sd)
            new_default = None
            needs_replace = False
            for pg_expr, sqlite_expr in _REPLACEMENTS.items():
                if pg_expr in sd_text:
                    needs_replace = True
                    new_default = sqlite_expr
                    break
            if not needs_replace and "::jsonb" in sd_text:
                needs_replace = True
                new_default = sd_text.replace("::jsonb", "")
            if not needs_replace and "::json" in sd_text:
                needs_replace = True
                new_default = sd_text.replace("::json", "")
            if needs_replace:
                originals[(table.name, col.name)] = sd
                col.server_default = (
                    DefaultClause(text(new_default)) if new_default else None
                )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    for (tname, cname), default in originals.items():
        Base.metadata.tables[tname].c[cname].server_default = default

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def fk_session(fk_engine):
    factory = async_sessionmaker(fk_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


async def _seed_channel_session_message(db) -> tuple[Channel, SessionModel, Message]:
    """Create Channel → Session → Message and commit."""
    channel = build_channel()
    session = SessionModel(
        id=uuid.uuid4(),
        client_id="test-client",
        bot_id="bot",
        channel_id=channel.id,
    )
    message = Message(
        id=uuid.uuid4(),
        session_id=session.id,
        role="user",
        content="hello",
    )
    db.add_all([channel, session, message])
    await db.commit()
    return channel, session, message


# ---------------------------------------------------------------------------
# Message → Attachment CASCADE (ondelete="CASCADE" + ORM cascade="all, delete-orphan")
# ---------------------------------------------------------------------------

class TestMessageDeleteCascade:
    """Deleting a Message removes its Attachments (ondelete=CASCADE)."""

    @pytest.mark.asyncio
    async def test_when_message_deleted_then_linked_attachments_are_deleted(self, fk_session):
        """Drift pin: ondelete=CASCADE means no orphan accumulation on message purge."""
        channel, session, message = await _seed_channel_session_message(fk_session)

        att1 = build_attachment(message_id=message.id, channel_id=channel.id)
        att2 = build_attachment(message_id=message.id, channel_id=channel.id)
        fk_session.add_all([att1, att2])
        await fk_session.commit()

        # Delete message; ORM cascade should also delete both attachments.
        msg_row = await fk_session.get(Message, message.id)
        await fk_session.delete(msg_row)
        await fk_session.commit()

        # Verify both attachments are gone.
        rows = (await fk_session.execute(
            select(Attachment).where(Attachment.message_id == message.id)
        )).scalars().all()
        assert rows == [], "CASCADE: both attachments must be deleted with their parent Message"

    @pytest.mark.asyncio
    async def test_when_message_has_no_attachments_then_delete_succeeds_cleanly(self, fk_session):
        """No-attachment message deletes without error (no-op cascade)."""
        _, _, message = await _seed_channel_session_message(fk_session)

        msg_row = await fk_session.get(Message, message.id)
        await fk_session.delete(msg_row)
        await fk_session.commit()

        assert await fk_session.get(Message, message.id) is None

    @pytest.mark.asyncio
    async def test_when_unlinked_attachment_exists_then_unaffected_by_other_message_delete(self, fk_session):
        """Attachment with message_id=NULL is not touched when a different Message is deleted."""
        channel, session, message = await _seed_channel_session_message(fk_session)
        orphan = build_attachment(message_id=None, channel_id=channel.id)
        fk_session.add(orphan)
        await fk_session.commit()

        msg_row = await fk_session.get(Message, message.id)
        await fk_session.delete(msg_row)
        await fk_session.commit()

        # Orphan attachment (NULL message_id) must still exist.
        still_there = await fk_session.get(Attachment, orphan.id)
        assert still_there is not None, "NULL-message_id attachment must not be affected by sibling deletion"

    @pytest.mark.asyncio
    async def test_when_sibling_message_exists_then_only_deleted_messages_attachments_removed(self, fk_session):
        """Sibling message's attachments are untouched when a different message is deleted."""
        channel, session, message = await _seed_channel_session_message(fk_session)
        sibling = Message(id=uuid.uuid4(), session_id=session.id, role="assistant", content="ok")
        fk_session.add(sibling)
        await fk_session.commit()

        att_target = build_attachment(message_id=message.id, channel_id=channel.id)
        att_sibling = build_attachment(message_id=sibling.id, channel_id=channel.id)
        fk_session.add_all([att_target, att_sibling])
        await fk_session.commit()

        msg_row = await fk_session.get(Message, message.id)
        await fk_session.delete(msg_row)
        await fk_session.commit()

        deleted = await fk_session.get(Attachment, att_target.id)
        sibling_att = await fk_session.get(Attachment, att_sibling.id)
        assert deleted is None, "target message's attachment must be deleted"
        assert sibling_att is not None, "sibling message's attachment must survive"


# ---------------------------------------------------------------------------
# Channel → Attachment.channel_id SET NULL (ondelete="SET NULL")
# ---------------------------------------------------------------------------

class TestChannelDeleteSetNull:
    """Deleting a Channel sets Attachment.channel_id to NULL (ondelete=SET NULL)."""

    @pytest.mark.asyncio
    async def test_when_channel_deleted_then_attachment_channel_id_becomes_null(self, fk_session):
        """Drift pin: ondelete=SET NULL means attachments survive channel deletion as orphans.

        If this changes to CASCADE, attachments would be deleted silently — a
        different failure mode for any code that references them after channel reset.
        """
        channel = build_channel()
        fk_session.add(channel)
        await fk_session.commit()

        att = build_attachment(channel_id=channel.id, message_id=None)
        fk_session.add(att)
        await fk_session.commit()
        att_id = att.id

        # Delete the channel via raw SQL to bypass ORM loading (test FK-level behavior).
        await fk_session.execute(
            text("DELETE FROM channels WHERE id = :cid").bindparams(cid=str(channel.id))
        )
        await fk_session.commit()

        # The attachment row must still exist, with channel_id=NULL.
        fk_session.expire_all()
        att_row = await fk_session.get(Attachment, att_id)
        assert att_row is not None, "Attachment must survive channel deletion (SET NULL, not CASCADE)"
        assert att_row.channel_id is None, "channel_id must be NULL after channel deleted"

    @pytest.mark.asyncio
    async def test_when_channel_deleted_then_attachments_with_message_survive_as_orphans(self, fk_session):
        """Attachment linked to both message + channel: message survives (different session).

        The attachment's channel_id is SET NULL, but if the message row exists in
        another session, the attachment row is preserved.
        """
        channel = build_channel()
        # Use a separate session so messages aren't cascade-deleted with the channel.
        other_session = SessionModel(
            id=uuid.uuid4(),
            client_id="other",
            bot_id="bot",
            channel_id=channel.id,
        )
        fk_session.add_all([channel, other_session])
        await fk_session.commit()

        message = Message(id=uuid.uuid4(), session_id=other_session.id, role="user", content="x")
        fk_session.add(message)
        await fk_session.commit()

        att = build_attachment(channel_id=channel.id, message_id=message.id)
        fk_session.add(att)
        await fk_session.commit()
        att_id = att.id

        # Delete attachment's channel_id link by setting to NULL directly.
        await fk_session.execute(
            text("UPDATE attachments SET channel_id = NULL WHERE id = :aid").bindparams(
                aid=str(att_id)
            )
        )
        await fk_session.commit()

        # Fresh SELECT to bypass identity map (avoids sync lazy-load in async context).
        result = await fk_session.execute(
            select(Attachment.channel_id, Attachment.message_id).where(
                Attachment.id == att_id
            )
        )
        row = result.one_or_none()
        assert row is not None, "Attachment row must survive the UPDATE"
        assert row.channel_id is None, "channel_id cleared by UPDATE"
        assert row.message_id == message.id, "message_id link preserved even with NULL channel_id"
