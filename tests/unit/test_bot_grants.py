"""Unit tests for ``app/services/bots_visibility.py``.

Covers the visibility filter + per-user access check. Admin bypass, owner
bypass, grantee access, stranger denial.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.models import ApiKey, Bot, BotGrant, User
from app.services.bots_visibility import apply_bot_visibility, can_user_use_bot


pytestmark = pytest.mark.asyncio


async def _make_user(db_session, *, is_admin: bool = False) -> User:
    user = User(
        email=f"u-{uuid.uuid4().hex[:6]}@test",
        display_name="U",
        password_hash="x",
        auth_method="local",
        is_admin=is_admin,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _make_bot(db_session, owner_id: uuid.UUID | None) -> Bot:
    bot = Bot(
        id=f"bot-{uuid.uuid4().hex[:8]}",
        name="Test Bot",
        display_name="Test Bot",
        model="test/model",
        system_prompt="",
        user_id=owner_id,
    )
    db_session.add(bot)
    await db_session.commit()
    await db_session.refresh(bot)
    return bot


async def _visible_bot_ids(db_session, user) -> set[str]:
    stmt = apply_bot_visibility(select(Bot.id), user)
    return {row[0] for row in (await db_session.execute(stmt)).all()}


class TestApplyBotVisibility:
    async def test_admin_sees_all(self, db_session):
        admin = await _make_user(db_session, is_admin=True)
        other = await _make_user(db_session, is_admin=False)
        b1 = await _make_bot(db_session, owner_id=None)
        b2 = await _make_bot(db_session, owner_id=other.id)

        visible = await _visible_bot_ids(db_session, admin)
        assert {b1.id, b2.id}.issubset(visible)

    async def test_owner_sees_own(self, db_session):
        owner = await _make_user(db_session, is_admin=False)
        other = await _make_user(db_session, is_admin=False)
        mine = await _make_bot(db_session, owner_id=owner.id)
        theirs = await _make_bot(db_session, owner_id=other.id)

        visible = await _visible_bot_ids(db_session, owner)
        assert mine.id in visible
        assert theirs.id not in visible

    async def test_grantee_sees_granted(self, db_session):
        owner = await _make_user(db_session, is_admin=False)
        grantee = await _make_user(db_session, is_admin=False)
        bot = await _make_bot(db_session, owner_id=owner.id)
        db_session.add(BotGrant(bot_id=bot.id, user_id=grantee.id, role="view"))
        await db_session.commit()

        visible = await _visible_bot_ids(db_session, grantee)
        assert bot.id in visible

    async def test_stranger_sees_none(self, db_session):
        owner = await _make_user(db_session, is_admin=False)
        stranger = await _make_user(db_session, is_admin=False)
        bot = await _make_bot(db_session, owner_id=owner.id)

        visible = await _visible_bot_ids(db_session, stranger)
        assert bot.id not in visible

    async def test_none_user_means_no_filter(self, db_session):
        """A non-User auth principal (static api key, etc.) sees everything."""
        bot = await _make_bot(db_session, owner_id=None)
        visible = await _visible_bot_ids(db_session, None)
        assert bot.id in visible


class TestCanUserUseBot:
    async def test_admin_bypass(self, db_session):
        admin = await _make_user(db_session, is_admin=True)
        other = await _make_user(db_session, is_admin=False)
        bot = await _make_bot(db_session, owner_id=other.id)
        assert await can_user_use_bot(db_session, admin, bot) is True

    async def test_owner(self, db_session):
        owner = await _make_user(db_session, is_admin=False)
        bot = await _make_bot(db_session, owner_id=owner.id)
        assert await can_user_use_bot(db_session, owner, bot) is True

    async def test_grantee(self, db_session):
        owner = await _make_user(db_session, is_admin=False)
        grantee = await _make_user(db_session, is_admin=False)
        bot = await _make_bot(db_session, owner_id=owner.id)
        db_session.add(BotGrant(bot_id=bot.id, user_id=grantee.id, role="view"))
        await db_session.commit()
        assert await can_user_use_bot(db_session, grantee, bot) is True

    async def test_stranger_denied(self, db_session):
        stranger = await _make_user(db_session, is_admin=False)
        bot = await _make_bot(db_session, owner_id=None)
        assert await can_user_use_bot(db_session, stranger, bot) is False

    async def test_non_user_principal_denied(self, db_session):
        """Per the helper's contract: API-key principals do not use this path."""
        bot = await _make_bot(db_session, owner_id=None)
        assert await can_user_use_bot(db_session, None, bot) is False


class TestSchema:
    """Schema-level invariants that don't require exercising DB cascade
    behavior (the SQLite test backend doesn't enforce ``ON DELETE CASCADE``
    by default). Migration ``221_bot_grants.py`` declares the cascades for
    Postgres; this test guards the ORM mirror.
    """

    def test_bot_grant_columns_declare_cascade(self):
        bot_fk = next(
            fk for fk in BotGrant.__table__.columns["bot_id"].foreign_keys
        )
        user_fk = next(
            fk for fk in BotGrant.__table__.columns["user_id"].foreign_keys
        )
        granted_by_fk = next(
            fk for fk in BotGrant.__table__.columns["granted_by"].foreign_keys
        )
        assert bot_fk.ondelete == "CASCADE"
        assert user_fk.ondelete == "CASCADE"
        # granted_by is audit-only; losing the granter shouldn't wipe the grant.
        assert granted_by_fk.ondelete == "SET NULL"
