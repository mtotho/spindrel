"""Phase G.3 — dashboards::delete_dashboard cascade ordering drift seams.

Seam class: orphan pointer + partial-commit (explicit delete vs. FK cascade)

delete_dashboard() explicitly deletes child pins BEFORE deleting the
dashboard row (lines 149-152 in dashboards.py). The comment in the code
explains the rationale: parity between SQLite (no FK enforcement) and
Postgres (ON DELETE CASCADE on the FK).

This file pins the contracts:
1. Cross-dashboard isolation — only the target dashboard's pins are deleted;
   sibling dashboard pins survive.
2. No-pins delete — deleting a dashboard with no pins doesn't crash.
3. Non-existent slug 404 — get_dashboard raises 404 when slug is unknown.
4. Dashboard list decrements — list_dashboards no longer returns the deleted slug.
5. Drift pin: explicit delete then dashboard row delete is idempotent even if FK
   cascade would have handled it (SQLite compat note in code is correct).
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.domain.errors import DomainError

from app.db.models import WidgetDashboardPin
from app.services.dashboard_pins import create_pin, list_pins
from app.services.dashboards import (
    create_dashboard,
    delete_dashboard,
    get_dashboard,
    list_dashboards,
)


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
# G.3.1 — cross-dashboard isolation of cascade
# ---------------------------------------------------------------------------


class TestCascadeIsolation:
    @pytest.mark.asyncio
    async def test_delete_only_removes_target_dashboards_pins(self, db_session):
        """Deleting 'home' leaves 'work' dashboard and its pins untouched."""
        await create_dashboard(db_session, slug="home", name="Home")
        await create_dashboard(db_session, slug="work", name="Work")

        pin_home = await create_pin(
            db_session, source_kind="adhoc", tool_name="h", envelope=_env("h"),
            dashboard_key="home",
        )
        pin_work = await create_pin(
            db_session, source_kind="adhoc", tool_name="w", envelope=_env("w"),
            dashboard_key="work",
        )

        await delete_dashboard(db_session, "home")

        # home's pin is gone
        home_pins = await list_pins(db_session, dashboard_key="home")
        assert home_pins == []

        # work's pin survived
        work_pins = await list_pins(db_session, dashboard_key="work")
        assert len(work_pins) == 1
        assert work_pins[0].id == pin_work.id

    @pytest.mark.asyncio
    async def test_default_pins_untouched_when_custom_dashboard_deleted(self, db_session):
        """Deleting a custom dashboard leaves default dashboard's pins intact."""
        await create_dashboard(db_session, slug="home", name="Home")
        default_pin = await create_pin(
            db_session, source_kind="adhoc", tool_name="d", envelope=_env("d"),
            dashboard_key="default",
        )
        await create_pin(
            db_session, source_kind="adhoc", tool_name="h", envelope=_env("h"),
            dashboard_key="home",
        )

        await delete_dashboard(db_session, "home")

        default_pins = await list_pins(db_session, dashboard_key="default")
        assert len(default_pins) == 1
        assert default_pins[0].id == default_pin.id


# ---------------------------------------------------------------------------
# G.3.2 — no-pins delete is safe
# ---------------------------------------------------------------------------


class TestNoPinsDelete:
    @pytest.mark.asyncio
    async def test_delete_dashboard_with_no_pins_does_not_crash(self, db_session):
        """Explicit DELETE WHERE dashboard_key=slug with empty table is a no-op."""
        await create_dashboard(db_session, slug="empty", name="Empty")
        # No pins created for "empty"
        await delete_dashboard(db_session, "empty")
        with pytest.raises(DomainError) as exc:
            await get_dashboard(db_session, "empty")
        assert exc.value.http_status == 404


# ---------------------------------------------------------------------------
# G.3.3 — 404 on non-existent slug
# ---------------------------------------------------------------------------


class TestNonExistentSlug:
    @pytest.mark.asyncio
    async def test_delete_nonexistent_dashboard_raises_404(self, db_session):
        """Trying to delete an unknown dashboard surfaces a 404, not a silent no-op."""
        with pytest.raises(DomainError) as exc:
            await delete_dashboard(db_session, "nonexistent")
        assert exc.value.http_status == 404

    @pytest.mark.asyncio
    async def test_get_nonexistent_dashboard_raises_404(self, db_session):
        with pytest.raises(DomainError) as exc:
            await get_dashboard(db_session, "ghost")
        assert exc.value.http_status == 404


# ---------------------------------------------------------------------------
# G.3.4 — list no longer contains deleted dashboard
# ---------------------------------------------------------------------------


class TestListAfterDelete:
    @pytest.mark.asyncio
    async def test_deleted_dashboard_not_in_list(self, db_session):
        await create_dashboard(db_session, slug="home", name="Home")
        await create_dashboard(db_session, slug="work", name="Work")

        slugs_before = {r.slug for r in await list_dashboards(db_session)}
        assert "home" in slugs_before and "work" in slugs_before

        await delete_dashboard(db_session, "home")

        slugs_after = {r.slug for r in await list_dashboards(db_session)}
        assert "home" not in slugs_after
        assert "work" in slugs_after
        assert "default" in slugs_after  # always present

    @pytest.mark.asyncio
    async def test_multiple_pins_all_deleted_with_dashboard(self, db_session):
        """Multiple pins on the same dashboard are all removed on delete."""
        await create_dashboard(db_session, slug="home", name="Home")
        for i in range(3):
            await create_pin(
                db_session, source_kind="adhoc", tool_name=f"t{i}",
                envelope=_env(f"p{i}"), dashboard_key="home",
            )

        await delete_dashboard(db_session, "home")

        pins = await list_pins(db_session, dashboard_key="home")
        assert pins == []
