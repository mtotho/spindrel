"""Phase G.2 — dashboard_pins::apply_layout_bulk drift seams.

Seam class: multi-actor JSONB mutation + cross-dashboard isolation

The existing test_dashboard_pins_service.py covers:
- Unknown pin IDs cause a full rollback (atomic)
- Valid items are persisted with correct coordinates

Missing (drift seams):
1. Cross-dashboard isolation — a pin from dashboard "home" must be rejected
   when the request targets dashboard_key="default".  Callers could silently
   move pins across dashboards by targeting the wrong dashboard_key.
2. JSONB flag_modified cross-session read — ``flag_modified`` fires and the
   update is actually visible from a fresh session (not just in-session cache).
3. Empty items list — early-return at {"ok": True, "updated": 0} without
   touching the DB.
4. Negative coordinate rejection — negative w/h/x/y values are rejected.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select

from app.domain.errors import DomainError

from app.db.models import WidgetDashboardPin
from app.services.dashboard_pins import (
    apply_layout_bulk,
    create_pin,
    list_pins,
)
from app.services.dashboards import create_dashboard


def _env(label: str = "x") -> dict:
    return {
        "content_type": "application/vnd.spindrel.components+json",
        "body": "{}",
        "plain_body": "ok",
        "display": "inline",
        "truncated": False,
        "record_id": None,
        "byte_size": 2,
        "display_label": label,
    }


# ---------------------------------------------------------------------------
# G.2.1 — cross-dashboard isolation
# ---------------------------------------------------------------------------


class TestCrossDashboardIsolation:
    @pytest.mark.asyncio
    async def test_pin_from_other_dashboard_rejected(self, db_session):
        """Pin belonging to 'home' is invisible to apply_layout_bulk on 'default'."""
        await create_dashboard(db_session, slug="home", name="Home")
        pin = await create_pin(
            db_session, source_kind="adhoc", tool_name="t", envelope=_env(),
            dashboard_key="home",
        )
        items = [{"id": str(pin.id), "x": 0, "y": 0, "w": 4, "h": 3}]

        with pytest.raises(DomainError) as exc:
            await apply_layout_bulk(db_session, items, dashboard_key="default")
        assert exc.value.http_status == 400
        assert str(pin.id) in exc.value.detail

    @pytest.mark.asyncio
    async def test_pin_from_correct_dashboard_accepted(self, db_session):
        """Same pin is accepted when dashboard_key matches."""
        await create_dashboard(db_session, slug="home", name="Home")
        pin = await create_pin(
            db_session, source_kind="adhoc", tool_name="t", envelope=_env(),
            dashboard_key="home",
        )
        items = [{"id": str(pin.id), "x": 1, "y": 2, "w": 6, "h": 4}]
        result = await apply_layout_bulk(db_session, items, dashboard_key="home")
        assert result == {"ok": True, "updated": 1}

    @pytest.mark.asyncio
    async def test_mixed_batch_all_or_nothing(self, db_session):
        """A batch with one foreign-dashboard pin rolls back the whole request."""
        await create_dashboard(db_session, slug="home", name="Home")
        good_pin = await create_pin(
            db_session, source_kind="adhoc", tool_name="g", envelope=_env(),
            dashboard_key="default",
        )
        foreign_pin = await create_pin(
            db_session, source_kind="adhoc", tool_name="f", envelope=_env(),
            dashboard_key="home",
        )
        items = [
            {"id": str(good_pin.id), "x": 0, "y": 0, "w": 4, "h": 3},
            {"id": str(foreign_pin.id), "x": 4, "y": 0, "w": 4, "h": 3},
        ]
        with pytest.raises(DomainError) as exc:
            await apply_layout_bulk(db_session, items, dashboard_key="default")
        assert exc.value.http_status == 400
        # good_pin must not have been committed
        rows = await list_pins(db_session)
        for row in rows:
            if row.id == good_pin.id:
                assert row.grid_layout != {"x": 0, "y": 0, "w": 4, "h": 3}


# ---------------------------------------------------------------------------
# G.2.2 — JSONB flag_modified cross-session persistence
# ---------------------------------------------------------------------------


class TestJsonbFlagModifiedPersistence:
    @pytest.mark.asyncio
    async def test_layout_visible_from_fresh_session(self, db_session, engine):
        """grid_layout written by apply_layout_bulk is visible from a fresh session.

        Verifies that flag_modified fired correctly and the JSONB column was
        committed — not just cached in the in-session identity map.
        """
        pin = await create_pin(
            db_session, source_kind="adhoc", tool_name="t", envelope=_env(),
        )
        items = [{"id": str(pin.id), "x": 2, "y": 3, "w": 5, "h": 4}]
        await apply_layout_bulk(db_session, items, dashboard_key="default")

        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as fresh_db:
            row = (await fresh_db.execute(
                select(WidgetDashboardPin).where(WidgetDashboardPin.id == pin.id)
            )).scalar_one()
            assert row.grid_layout == {"x": 2, "y": 3, "w": 5, "h": 4}


# ---------------------------------------------------------------------------
# G.2.3 — empty items early return
# ---------------------------------------------------------------------------


class TestEmptyItems:
    @pytest.mark.asyncio
    async def test_empty_list_returns_zero_updated(self, db_session):
        """apply_layout_bulk([]) returns the zero-updated dict immediately."""
        result = await apply_layout_bulk(db_session, [], dashboard_key="default")
        assert result == {"ok": True, "updated": 0}

    @pytest.mark.asyncio
    async def test_non_list_items_rejected(self, db_session):
        """Non-list items argument raises 400."""
        with pytest.raises(DomainError) as exc:
            await apply_layout_bulk(db_session, {"id": "x"})  # type: ignore[arg-type]
        assert exc.value.http_status == 400


# ---------------------------------------------------------------------------
# G.2.4 — coordinate validation
# ---------------------------------------------------------------------------


class TestCoordinateValidation:
    @pytest.mark.asyncio
    async def test_negative_x_rejected(self, db_session):
        pin = await create_pin(
            db_session, source_kind="adhoc", tool_name="t", envelope=_env(),
        )
        items = [{"id": str(pin.id), "x": -1, "y": 0, "w": 4, "h": 3}]
        with pytest.raises(DomainError) as exc:
            await apply_layout_bulk(db_session, items)
        assert exc.value.http_status == 400

    @pytest.mark.asyncio
    async def test_missing_coordinate_key_rejected(self, db_session):
        pin = await create_pin(
            db_session, source_kind="adhoc", tool_name="t", envelope=_env(),
        )
        items = [{"id": str(pin.id), "x": 0, "y": 0, "w": 4}]  # missing h
        with pytest.raises(DomainError) as exc:
            await apply_layout_bulk(db_session, items)
        assert exc.value.http_status == 400
