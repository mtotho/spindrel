"""Unit tests for app/services/dashboard_rail.py.

Focus: scope-based admin gating, personal-vs-everyone row semantics, and
the ``resolved_rail_state`` "personal wins" rule.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.domain.errors import ForbiddenError, ValidationError

from app.db.models import DashboardRailPin, User
from app.services.dashboard_rail import (
    resolved_rail_state,
    resolved_rail_state_bulk,
    set_rail_pin,
    unset_rail_pin,
)
from app.services.dashboards import create_dashboard


def _make_user(db, *, is_admin: bool = False) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"u-{uuid.uuid4().hex[:8]}@test.com",
        display_name="Test User",
        auth_method="local",
        password_hash="x",
        is_admin=is_admin,
        integration_config={},
    )
    db.add(user)
    return user


@pytest.mark.asyncio
async def test_admin_can_pin_everyone(db_session):
    await create_dashboard(db_session, slug="home", name="Home")

    row = await set_rail_pin(
        db_session, "home",
        scope="everyone", user_id=None, is_admin=True, rail_position=3,
    )
    assert row.user_id is None
    assert row.rail_position == 3


@pytest.mark.asyncio
async def test_non_admin_cannot_pin_everyone(db_session):
    await create_dashboard(db_session, slug="home", name="Home")
    alice = _make_user(db_session)
    await db_session.commit()

    with pytest.raises(ForbiddenError) as exc:
        await set_rail_pin(
            db_session, "home",
            scope="everyone", user_id=alice.id, is_admin=False,
        )
    assert exc.value.http_status == 403


@pytest.mark.asyncio
async def test_non_admin_can_pin_me(db_session):
    await create_dashboard(db_session, slug="home", name="Home")
    alice = _make_user(db_session)
    await db_session.commit()

    row = await set_rail_pin(
        db_session, "home",
        scope="me", user_id=alice.id, is_admin=False,
    )
    assert row.user_id == alice.id


@pytest.mark.asyncio
async def test_scope_me_without_user_rejected(db_session):
    await create_dashboard(db_session, slug="home", name="Home")
    with pytest.raises(ValidationError) as exc:
        await set_rail_pin(
            db_session, "home",
            scope="me", user_id=None, is_admin=True,
        )
    assert exc.value.http_status == 400


@pytest.mark.asyncio
async def test_personal_and_everyone_coexist(db_session):
    await create_dashboard(db_session, slug="home", name="Home")
    alice = _make_user(db_session)
    await db_session.commit()

    await set_rail_pin(
        db_session, "home",
        scope="everyone", user_id=None, is_admin=True, rail_position=5,
    )
    await set_rail_pin(
        db_session, "home",
        scope="me", user_id=alice.id, is_admin=False, rail_position=1,
    )

    state = await resolved_rail_state(db_session, "home", alice.id)
    assert state == {
        "me_pinned": True,
        "everyone_pinned": True,
        "effective_position": 1,  # personal wins
    }


@pytest.mark.asyncio
async def test_resolved_state_falls_back_to_everyone(db_session):
    """User with no personal row sees the everyone position."""
    await create_dashboard(db_session, slug="home", name="Home")
    bob = _make_user(db_session)
    await db_session.commit()

    await set_rail_pin(
        db_session, "home",
        scope="everyone", user_id=None, is_admin=True, rail_position=7,
    )

    state = await resolved_rail_state(db_session, "home", bob.id)
    assert state == {
        "me_pinned": False,
        "everyone_pinned": True,
        "effective_position": 7,
    }


@pytest.mark.asyncio
async def test_upsert_updates_position(db_session):
    await create_dashboard(db_session, slug="home", name="Home")
    alice = _make_user(db_session)
    await db_session.commit()

    await set_rail_pin(
        db_session, "home",
        scope="me", user_id=alice.id, is_admin=False, rail_position=1,
    )
    await set_rail_pin(
        db_session, "home",
        scope="me", user_id=alice.id, is_admin=False, rail_position=9,
    )

    rows = (await db_session.execute(
        select(DashboardRailPin).where(
            DashboardRailPin.dashboard_slug == "home",
            DashboardRailPin.user_id == alice.id,
        )
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].rail_position == 9


@pytest.mark.asyncio
async def test_unset_me_leaves_everyone_intact(db_session):
    await create_dashboard(db_session, slug="home", name="Home")
    alice = _make_user(db_session)
    await db_session.commit()

    await set_rail_pin(
        db_session, "home",
        scope="everyone", user_id=None, is_admin=True,
    )
    await set_rail_pin(
        db_session, "home",
        scope="me", user_id=alice.id, is_admin=False,
    )

    removed = await unset_rail_pin(
        db_session, "home",
        scope="me", user_id=alice.id, is_admin=False,
    )
    assert removed is True

    state = await resolved_rail_state(db_session, "home", alice.id)
    assert state["me_pinned"] is False
    assert state["everyone_pinned"] is True


@pytest.mark.asyncio
async def test_unset_everyone_requires_admin(db_session):
    await create_dashboard(db_session, slug="home", name="Home")
    alice = _make_user(db_session)
    await db_session.commit()

    await set_rail_pin(
        db_session, "home",
        scope="everyone", user_id=None, is_admin=True,
    )

    with pytest.raises(ForbiddenError) as exc:
        await unset_rail_pin(
            db_session, "home",
            scope="everyone", user_id=alice.id, is_admin=False,
        )
    assert exc.value.http_status == 403


@pytest.mark.asyncio
async def test_bulk_resolves_multiple_slugs(db_session):
    await create_dashboard(db_session, slug="a", name="A")
    await create_dashboard(db_session, slug="b", name="B")
    alice = _make_user(db_session)
    await db_session.commit()

    await set_rail_pin(
        db_session, "a",
        scope="everyone", user_id=None, is_admin=True, rail_position=2,
    )
    await set_rail_pin(
        db_session, "b",
        scope="me", user_id=alice.id, is_admin=False, rail_position=4,
    )

    batch = await resolved_rail_state_bulk(db_session, ["a", "b", "c"], alice.id)
    assert batch["a"]["everyone_pinned"] is True
    assert batch["a"]["me_pinned"] is False
    assert batch["a"]["effective_position"] == 2
    assert batch["b"]["me_pinned"] is True
    assert batch["b"]["effective_position"] == 4
    assert batch["c"] == {
        "me_pinned": False,
        "everyone_pinned": False,
        "effective_position": None,
    }


@pytest.mark.asyncio
async def test_cascade_on_dashboard_delete(db_session):
    """Deleting a dashboard cascades rail pins (FK ondelete=CASCADE)."""
    from app.services.dashboards import delete_dashboard

    await create_dashboard(db_session, slug="home", name="Home")
    alice = _make_user(db_session)
    await db_session.commit()

    await set_rail_pin(
        db_session, "home",
        scope="me", user_id=alice.id, is_admin=False,
    )
    await delete_dashboard(db_session, "home")

    rows = (await db_session.execute(
        select(DashboardRailPin).where(
            DashboardRailPin.dashboard_slug == "home",
        )
    )).scalars().all()
    assert rows == []
