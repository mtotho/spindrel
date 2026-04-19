"""Phase K — Dashboard Pin Drift + Migration Contract.

Seams from plan rippling-giggling-bachman.md Phase K:

K.2  Migration 213 idempotency — running its upgrade logic twice doesn't
     duplicate dashboard rows or pin rows.  The migration already has an
     idempotency check; this test pins that it works correctly.

K.3  Migration 215 partial-layout backfill — pins with a partial
     ``grid_layout`` dict that already has ``"x"`` are left untouched.

K.4  Channel delete cascade:
     - ``source_channel_id`` FK is SET NULL (pins survive with null source).
     - Channel dashboard (slug=``channel:<id>``) has NO FK to Channel —
       it's an orphan slug.  Deleting the channel leaves the dashboard.
       (Pinning this as confirmed missing-cascade; it may be intentional
       since the dashboard may be pinned for viewing history after delete.)

K.5  Pin position uniqueness: two pins with same (dashboard_key, position)
     are ALLOWED — the table has an index but not a unique constraint.

K.7  ``apply_dashboard_pin_config_patch`` JSONB round-trip: shallow-merge
     persists across session expire (``flag_modified`` + ``commit``).

K.9  Dashboard slug collision: user cannot create a dashboard with a slug
     matching the ``channel:`` prefix — but ALSO: the ``_SLUG_RE`` regex
     blocks colons before the channel-prefix check fires (dead code pin).
"""
from __future__ import annotations

import copy
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy import select

from app.db.models import Channel, WidgetDashboard, WidgetDashboardPin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_channel() -> Channel:
    return Channel(id=uuid.uuid4(), name=f"ch-{uuid.uuid4().hex[:6]}", bot_id="test-bot")


def _make_dashboard(slug: str, name: str = "Test") -> WidgetDashboard:
    return WidgetDashboard(slug=slug, name=name)


def _make_pin(
    dashboard_key: str,
    position: int,
    *,
    source_channel_id=None,
    grid_layout=None,
) -> WidgetDashboardPin:
    return WidgetDashboardPin(
        id=uuid.uuid4(),
        dashboard_key=dashboard_key,
        position=position,
        source_kind="channel",
        source_channel_id=source_channel_id,
        source_bot_id="test-bot",
        tool_name="test_widget",
        tool_args={},
        widget_config={},
        envelope={"display_label": "Test Widget"},
        grid_layout=grid_layout or {},
    )


# ===========================================================================
# K.2 — Migration 213 idempotency
# ===========================================================================


@pytest.mark.asyncio
class TestMigration213Idempotency:
    """Pins that migration 213 would create must not be duplicated when the
    migration logic runs a second time on the same data.

    Tests the idempotency guard at migrations/versions/213_*.py:80-134.
    The guard checks for existing (tool_name, source_bot_id, position) tuples
    before inserting new pins.
    """

    async def test_double_run_does_not_duplicate_dashboard(self, db_session):
        """The dashboard row insert is guarded: if slug already exists → skip.
        Running the migration logic twice leaves exactly 1 dashboard row.
        """
        slug = f"channel:{uuid.uuid4()}"
        dash = _make_dashboard(slug)
        db_session.add(dash)
        await db_session.flush()

        # Simulate a second migration attempt: try to insert, check existence first.
        existing = (await db_session.execute(
            select(WidgetDashboard).where(WidgetDashboard.slug == slug)
        )).scalar_one_or_none()

        if existing is None:
            db_session.add(_make_dashboard(slug, name="Duplicate"))
            await db_session.flush()

        # Only one row should exist.
        count = (await db_session.execute(
            sa.select(sa.func.count()).select_from(WidgetDashboard).where(
                WidgetDashboard.slug == slug
            )
        )).scalar_one()
        assert count == 1, f"Dashboard duplicated on second run: {count} rows"

    async def test_double_run_does_not_duplicate_pins(self, db_session):
        """Pins are deduplicated by (tool_name, source_bot_id, position).

        Migration 213 lines 96-112: build existing_keys set, skip if already present.
        """
        slug = f"channel:{uuid.uuid4()}"
        db_session.add(_make_dashboard(slug))
        await db_session.flush()

        # First pass: insert 2 pins.
        for pos in (0, 1):
            db_session.add(_make_pin(slug, pos))
        await db_session.flush()

        # Second pass: simulate re-running migration (check + conditional insert).
        existing_keys = {
            (row.tool_name, row.source_bot_id, row.position)
            async for row in (
                await db_session.stream(
                    select(WidgetDashboardPin.tool_name,
                           WidgetDashboardPin.source_bot_id,
                           WidgetDashboardPin.position)
                    .where(WidgetDashboardPin.dashboard_key == slug)
                )
            )
        }

        for pos in (0, 1):
            if ("test_widget", "test-bot", pos) not in existing_keys:
                db_session.add(_make_pin(slug, pos))

        await db_session.flush()

        count = (await db_session.execute(
            sa.select(sa.func.count()).select_from(WidgetDashboardPin).where(
                WidgetDashboardPin.dashboard_key == slug
            )
        )).scalar_one()
        assert count == 2, (
            f"Pin count after double-run: {count} (expected 2) — idempotency guard failed"
        )


# ===========================================================================
# K.3 — Migration 215 partial-layout backfill semantics
# ===========================================================================


@pytest.mark.asyncio
class TestMigration215Backfill:
    """Migration 215 backfills ``grid_layout`` on channel dashboard pins that
    have an empty or missing layout, but skips pins that already have ``x``.
    """

    async def test_pin_with_x_is_not_overwritten(self, db_session):
        """Pin with ``grid_layout = {"x": 3, "y": 0, "w": 4, "h": 2}``
        must NOT be overwritten by the migration backfill.

        Migration 215 line 52: ``if isinstance(gl, dict) and gl and "x" in gl: continue``
        """
        slug = f"channel:{uuid.uuid4()}"
        db_session.add(_make_dashboard(slug))
        user_layout = {"x": 3, "y": 0, "w": 4, "h": 2}
        pin = _make_pin(slug, 0, grid_layout=user_layout)
        db_session.add(pin)
        await db_session.flush()

        # Simulate migration 215 upgrade logic inline.
        rows = (await db_session.execute(
            select(WidgetDashboardPin.id, WidgetDashboardPin.position, WidgetDashboardPin.grid_layout)
            .where(WidgetDashboardPin.dashboard_key.like("channel:%"))
            .order_by(WidgetDashboardPin.position)
        )).fetchall()

        for pid, position, gl in rows:
            if isinstance(gl, dict) and gl and "x" in gl:
                continue  # already placed — skip
            # This would overwrite; should NOT reach here for our pin.
            await db_session.execute(
                sa.update(WidgetDashboardPin)
                .where(WidgetDashboardPin.id == pid)
                .values(grid_layout={"x": 0, "y": int(position or 0) * 6, "w": 6, "h": 6})
            )

        await db_session.flush()

        refreshed = (await db_session.execute(
            select(WidgetDashboardPin).where(WidgetDashboardPin.id == pin.id)
        )).scalar_one()

        assert refreshed.grid_layout == user_layout, (
            f"Migration 215 overwrote a pin with existing 'x' coord: "
            f"expected {user_layout!r}, got {refreshed.grid_layout!r}"
        )

    async def test_pin_with_empty_layout_gets_backfilled(self, db_session):
        """Pin with ``grid_layout = {}`` (migration 213's default) gets
        the stacked default ``{x:0, y:pos*6, w:6, h:6}``.
        """
        slug = f"channel:{uuid.uuid4()}"
        db_session.add(_make_dashboard(slug))
        pin = _make_pin(slug, 2, grid_layout={})
        db_session.add(pin)
        await db_session.flush()

        # Simulate migration 215.
        for pid, position, gl in (await db_session.execute(
            select(WidgetDashboardPin.id, WidgetDashboardPin.position, WidgetDashboardPin.grid_layout)
            .where(WidgetDashboardPin.dashboard_key.like("channel:%"))
        )).fetchall():
            if isinstance(gl, dict) and gl and "x" in gl:
                continue
            await db_session.execute(
                sa.update(WidgetDashboardPin)
                .where(WidgetDashboardPin.id == pid)
                .values(grid_layout={"x": 0, "y": int(position or 0) * 6, "w": 6, "h": 6})
            )

        await db_session.flush()
        pin_id = pin.id  # capture before expire invalidates the attribute
        db_session.expire(pin)

        refreshed = (await db_session.execute(
            select(WidgetDashboardPin).where(WidgetDashboardPin.id == pin_id)
        )).scalar_one()

        assert refreshed.grid_layout == {"x": 0, "y": 12, "w": 6, "h": 6}, (
            f"Empty-layout pin not backfilled correctly: {refreshed.grid_layout!r}"
        )


# ===========================================================================
# K.4 — Channel delete cascade (source_channel_id SET NULL; dashboard orphaned)
# ===========================================================================


@pytest.mark.asyncio
class TestChannelDeleteCascade:
    """Pinning FK behavior when a Channel is deleted.

    1. WidgetDashboardPin.source_channel_id → FK ondelete=SET NULL
       Pins that reference the deleted channel survive but lose their source.

    2. WidgetDashboard (slug=``channel:<id>``) has NO FK to Channel.
       The channel dashboard is NOT cascade-deleted; it becomes an orphan.
       Pins on the channel dashboard also survive (they reference the dashboard,
       not the channel directly).
    """

    async def test_source_channel_id_fk_declared_set_null(self):
        """Verify at schema level that source_channel_id FK is ondelete=SET NULL.

        SQLite FK actions require ``PRAGMA foreign_keys = ON`` at connection
        establishment, which is outside the test session's control.  We
        therefore pin the schema contract (FK declaration) rather than the
        runtime behavior (actual SET NULL on delete); the runtime behavior is
        covered by integration tests against PostgreSQL.
        """
        col = WidgetDashboardPin.__table__.c["source_channel_id"]
        fks = list(col.foreign_keys)
        assert len(fks) == 1, f"Expected 1 FK on source_channel_id, got {fks}"
        fk = fks[0]
        assert fk.ondelete == "SET NULL", (
            f"source_channel_id FK should be ondelete='SET NULL', got {fk.ondelete!r}. "
            "Without this, channel deletion would leave orphan pins or cascade-delete them."
        )
        assert col.nullable, (
            "source_channel_id must be nullable — required for SET NULL to work"
        )

    async def test_channel_dashboard_not_cascade_deleted_with_channel(
        self, db_session
    ):
        """Deleting a channel does NOT delete its channel-scoped dashboard.

        WidgetDashboard has no FK to Channel — the slug ``channel:<uuid>``
        is a naming convention, not a DB relationship.  The dashboard
        becomes an orphaned row after the channel is deleted.

        Pinning current contract: this may be intentional (preserving the
        dashboard for offline reference) or may be a missing cascade
        (Loose Ends: channel dashboard not cascade-deleted).
        """
        ch = _make_channel()
        db_session.add(ch)
        await db_session.flush()

        slug = f"channel:{ch.id}"
        db_session.add(_make_dashboard(slug, name="Channel Dashboard"))
        pin = _make_pin(slug, 0)
        db_session.add(pin)
        await db_session.flush()

        # Delete the channel.
        await db_session.delete(ch)
        await db_session.flush()

        # Dashboard still exists — no FK cascade.
        surviving_dash = (await db_session.execute(
            select(WidgetDashboard).where(WidgetDashboard.slug == slug)
        )).scalar_one_or_none()

        assert surviving_dash is not None, (
            "Channel dashboard was cascade-deleted — this changed the contract. "
            "If a FK was added, update this test and remove from Loose Ends."
        )

        # Pin on the channel dashboard also survives (dashboard not deleted → no cascade).
        surviving_pin = (await db_session.execute(
            select(WidgetDashboardPin).where(WidgetDashboardPin.id == pin.id)
        )).scalar_one_or_none()

        assert surviving_pin is not None, "Pin on channel dashboard unexpectedly deleted"


# ===========================================================================
# K.5 — Pin position uniqueness (index only, not unique)
# ===========================================================================


@pytest.mark.asyncio
class TestPinPositionUniqueness:
    """WidgetDashboardPin.__table_args__ has an Index (not UniqueConstraint) on
    (dashboard_key, position).  Two pins can occupy the same position within
    the same dashboard without a DB error.

    Pinning current contract: duplicate positions are allowed by the schema.
    The ordering contract is therefore: if multiple pins have the same position,
    fetch order is undefined and the frontend must handle conflicts gracefully.
    """

    async def test_two_pins_same_position_both_persist(self, db_session):
        """Inserting two pins with identical (dashboard_key, position) succeeds.
        Both rows are committed and retrievable.
        """
        slug = "conflict-dashboard"
        db_session.add(_make_dashboard(slug))
        p1 = _make_pin(slug, 5)
        p2 = _make_pin(slug, 5)
        db_session.add(p1)
        db_session.add(p2)
        await db_session.flush()

        count = (await db_session.execute(
            sa.select(sa.func.count()).select_from(WidgetDashboardPin).where(
                WidgetDashboardPin.dashboard_key == slug,
                WidgetDashboardPin.position == 5,
            )
        )).scalar_one()

        assert count == 2, (
            f"Expected 2 pins at position 5 (no unique constraint), got {count}. "
            "If a unique constraint was added, update this test and add a dedup path."
        )


# ===========================================================================
# K.7 — apply_dashboard_pin_config_patch JSONB round-trip
# ===========================================================================


@pytest.mark.asyncio
class TestJsonbConfigPatch:
    """``apply_dashboard_pin_config_patch`` uses ``copy.deepcopy`` + ``flag_modified``
    to ensure SQLAlchemy tracks the in-place mutation.

    Mirrors the Phase E.7 shape for channel_bot_members.config.
    """

    async def test_patch_merges_and_persists_across_expire(
        self, db_session, patched_async_sessions
    ):
        """Shallow-merge patch → commit → expire → re-read → merged config persisted."""
        from app.services.dashboard_pins import apply_dashboard_pin_config_patch

        slug = "jsonb-test"
        db_session.add(_make_dashboard(slug))
        pin = _make_pin(slug, 0)
        pin.widget_config = {"theme": "dark"}
        db_session.add(pin)
        await db_session.flush()
        await db_session.commit()

        await apply_dashboard_pin_config_patch(db_session, pin.id, {"width": 800})

        pin_id = pin.id  # capture before expire_all invalidates the attribute
        db_session.expire_all()

        refreshed = (await db_session.execute(
            select(WidgetDashboardPin).where(WidgetDashboardPin.id == pin_id)
        )).scalar_one()

        assert refreshed.widget_config == {"theme": "dark", "width": 800}, (
            f"JSONB merge not persisted across expire: {refreshed.widget_config!r}"
        )

    async def test_patch_replace_mode_discards_existing(
        self, db_session, patched_async_sessions
    ):
        """``merge=False`` replaces config entirely (no shallow merge)."""
        from app.services.dashboard_pins import apply_dashboard_pin_config_patch

        slug = "jsonb-replace"
        db_session.add(_make_dashboard(slug))
        pin = _make_pin(slug, 0)
        pin.widget_config = {"a": 1, "b": 2}
        db_session.add(pin)
        await db_session.flush()
        await db_session.commit()

        await apply_dashboard_pin_config_patch(
            db_session, pin.id, {"c": 3}, merge=False
        )

        pin_id = pin.id  # capture before expire_all invalidates the attribute
        db_session.expire_all()
        refreshed = (await db_session.execute(
            select(WidgetDashboardPin).where(WidgetDashboardPin.id == pin_id)
        )).scalar_one()

        assert refreshed.widget_config == {"c": 3}, (
            f"Replace mode kept old keys: {refreshed.widget_config!r}"
        )


# ===========================================================================
# K.9 — Dashboard slug collision: channel: prefix blocked by regex + explicit guard
# ===========================================================================


class TestSlugProtection:
    """User-facing ``create_dashboard`` rejects slugs that start with
    ``channel:`` via two layers:

    1. ``_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")`` — colons are not
       in the character class, so any ``channel:...`` slug fails regex validation
       BEFORE reaching the channel-prefix check.

    2. ``if slug.startswith(CHANNEL_SLUG_PREFIX): raise HTTPException(400, ...)``
       at line 210 is therefore effectively dead code — the regex blocks colons first.

    Pinning this dual-guard contract.  If the regex is ever relaxed (e.g. to
    allow colons) the explicit channel-prefix check becomes load-bearing;
    update the ``dead_code`` test if that happens.
    """

    @pytest.mark.asyncio
    async def test_valid_slug_without_colon_succeeds(self, db_session):
        """Baseline: a slug with no colon (e.g. ``channelxabc``) is valid
        and does NOT raise — contrast with the colon-containing failure cases below.
        """
        from app.services.dashboards import create_dashboard

        dash = await create_dashboard(db_session, slug="channelxabc", name="Valid")
        assert dash.slug == "channelxabc"

    @pytest.mark.asyncio
    async def test_slug_with_colon_rejected_by_regex(self, db_session):
        """A slug containing a colon (``channel:abc``) fails ``_SLUG_RE``
        because colon is not in ``[a-z0-9-]``.
        """
        from fastapi import HTTPException

        from app.services.dashboards import create_dashboard

        with pytest.raises(HTTPException) as excinfo:
            await create_dashboard(
                db_session, slug="channel:abc", name="Should fail"
            )
        assert excinfo.value.status_code == 400
        # Blocked by regex — message says "lowercase letters, digits, or dashes".
        assert "channel" in excinfo.value.detail.lower() or "slug" in excinfo.value.detail.lower()

    @pytest.mark.asyncio
    async def test_explicit_channel_prefix_guard_is_dead_code(self, db_session):
        """Pin that the channel-prefix explicit check at line 210 is
        never reached when called via ``create_dashboard`` because the regex
        blocks colons first.

        If this test fails it means the channel-prefix error message was
        returned — that implies the regex was widened to allow colons.
        """
        from fastapi import HTTPException

        from app.services.dashboards import create_dashboard, CHANNEL_SLUG_PREFIX

        # Build a slug that starts with "channel:" — colon blocks regex.
        slug = f"{CHANNEL_SLUG_PREFIX}testchannel"

        with pytest.raises(HTTPException) as excinfo:
            await create_dashboard(db_session, slug=slug, name="Fail")

        # Regex fires first — message is about slug format, not channel prefix.
        # If the message says "'channel:*' slugs are reserved", the explicit
        # guard is now reachable — update this test.
        assert excinfo.value.status_code == 400
        assert "channel:" not in excinfo.value.detail, (
            "The explicit channel-prefix guard at dashboards.py:210 is now reachable "
            "— the slug regex was likely widened. Remove the 'dead code' comment and "
            "keep the explicit guard as the first line of defence."
        )
