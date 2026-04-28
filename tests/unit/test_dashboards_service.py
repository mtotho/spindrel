"""Unit tests for app/services/dashboards.py."""
from __future__ import annotations

import uuid

import pytest
from app.domain.errors import DomainError

from app.db.models import Channel
from app.services.dashboard_pins import create_pin, list_pins
from app.services.dashboards import (
    CHANNEL_SLUG_PREFIX,
    channel_slug,
    create_dashboard,
    delete_dashboard,
    ensure_channel_dashboard,
    get_dashboard,
    is_channel_slug,
    list_dashboards,
    redirect_target_slug,
    touch_last_viewed,
    update_dashboard,
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


@pytest.mark.asyncio
async def test_default_is_preseeded(db_session):
    row = await get_dashboard(db_session, "default")
    assert row.slug == "default"
    assert row.name == "Default"


@pytest.mark.asyncio
async def test_create_and_list(db_session):
    await create_dashboard(db_session, slug="home", name="Home", icon="Home")
    rows = await list_dashboards(db_session)
    slugs = [r.slug for r in rows]
    assert "home" in slugs and "default" in slugs


@pytest.mark.asyncio
async def test_create_rejects_reserved_slug(db_session):
    for reserved in ("default", "dev", "new"):
        with pytest.raises(DomainError) as exc:
            await create_dashboard(db_session, slug=reserved, name="X")
        assert exc.value.http_status == 400


@pytest.mark.asyncio
async def test_create_rejects_bad_slug_format(db_session):
    for bad in ("Caps", "with space", "-leading", "", "a" * 49):
        with pytest.raises(DomainError) as exc:
            await create_dashboard(db_session, slug=bad, name="X")
        assert exc.value.http_status == 400


@pytest.mark.asyncio
async def test_create_rejects_duplicate_slug(db_session):
    await create_dashboard(db_session, slug="home", name="Home")
    with pytest.raises(DomainError) as exc:
        await create_dashboard(db_session, slug="home", name="Home Again")
    assert exc.value.http_status == 409


@pytest.mark.asyncio
async def test_update_changes_metadata(db_session):
    await create_dashboard(db_session, slug="home", name="Home")
    updated = await update_dashboard(
        db_session, "home",
        {"name": "Home Office", "icon": "Briefcase"},
    )
    assert updated.name == "Home Office"
    assert updated.icon == "Briefcase"


@pytest.mark.asyncio
async def test_delete_removes_dashboard(db_session):
    await create_dashboard(db_session, slug="home", name="Home")
    await delete_dashboard(db_session, "home")
    with pytest.raises(DomainError) as exc:
        await get_dashboard(db_session, "home")
    assert exc.value.http_status == 404


@pytest.mark.asyncio
async def test_delete_default_is_forbidden(db_session):
    with pytest.raises(DomainError) as exc:
        await delete_dashboard(db_session, "default")
    assert exc.value.http_status == 400


@pytest.mark.asyncio
async def test_delete_cascades_pins(db_session):
    """Deleting a dashboard drops its pins (explicit parity with FK cascade)."""
    await create_dashboard(db_session, slug="home", name="Home")
    await create_pin(
        db_session, source_kind="adhoc", tool_name="t", envelope=_env(),
        dashboard_key="home",
    )
    await delete_dashboard(db_session, "home")
    with pytest.raises(DomainError):
        await get_dashboard(db_session, "home")
    pins = await list_pins(db_session, dashboard_key="home")
    assert pins == []


@pytest.mark.asyncio
async def test_touch_last_viewed_drives_redirect_target(db_session):
    await create_dashboard(db_session, slug="home", name="Home")
    assert await redirect_target_slug(db_session) == "default"
    await touch_last_viewed(db_session, "home")
    assert await redirect_target_slug(db_session) == "home"


@pytest.mark.asyncio
async def test_create_pin_rejects_unknown_dashboard(db_session):
    with pytest.raises(DomainError) as exc:
        await create_pin(
            db_session, source_kind="adhoc", tool_name="t", envelope=_env(),
            dashboard_key="nope",
        )
    assert exc.value.http_status == 404


# ---------------------------------------------------------------------------
# Channel-scoped dashboards (reserved slug ``channel:<uuid>``)
# ---------------------------------------------------------------------------


def _make_channel(db_session, *, name: str = "ch") -> Channel:
    ch = Channel(id=uuid.uuid4(), name=name, bot_id="bot-x")
    db_session.add(ch)
    return ch


def test_channel_slug_helpers():
    cid = uuid.uuid4()
    assert channel_slug(cid) == f"{CHANNEL_SLUG_PREFIX}{cid}"
    assert is_channel_slug(channel_slug(cid)) is True
    assert is_channel_slug("default") is False
    assert is_channel_slug("") is False


@pytest.mark.asyncio
async def test_create_rejects_channel_prefix(db_session):
    """User-facing create never lands on the reserved prefix — slug validator
    rejects the colon first, but we want the clearer message anyway."""
    with pytest.raises(DomainError) as exc:
        await create_dashboard(db_session, slug="channel:not-a-uuid", name="X")
    assert exc.value.http_status == 400


@pytest.mark.asyncio
async def test_ensure_channel_dashboard_is_idempotent(db_session):
    ch = _make_channel(db_session, name="quality-assurance")
    await db_session.commit()

    first = await ensure_channel_dashboard(db_session, ch.id)
    assert first.slug == channel_slug(ch.id)
    assert first.name == "quality-assurance"

    second = await ensure_channel_dashboard(db_session, ch.id)
    assert second.slug == first.slug
    # Second call is a no-op on existing rows.
    rows = await list_dashboards(db_session, scope="channel")
    assert len([r for r in rows if r.slug == first.slug]) == 1


@pytest.mark.asyncio
async def test_ensure_channel_dashboard_requires_channel(db_session):
    ghost = uuid.uuid4()
    with pytest.raises(DomainError) as exc:
        await ensure_channel_dashboard(db_session, ghost)
    assert exc.value.http_status == 404


@pytest.mark.asyncio
async def test_list_dashboards_scope_filter(db_session):
    ch = _make_channel(db_session)
    await db_session.commit()
    await ensure_channel_dashboard(db_session, ch.id)
    await create_dashboard(db_session, slug="home", name="Home")

    user_rows = await list_dashboards(db_session, scope="user")
    user_slugs = {r.slug for r in user_rows}
    assert "default" in user_slugs
    assert "home" in user_slugs
    assert all(not r.slug.startswith(CHANNEL_SLUG_PREFIX) for r in user_rows)

    channel_rows = await list_dashboards(db_session, scope="channel")
    channel_slugs = {r.slug for r in channel_rows}
    assert channel_slug(ch.id) in channel_slugs
    assert all(r.slug.startswith(CHANNEL_SLUG_PREFIX) for r in channel_rows)

    all_rows = await list_dashboards(db_session, scope="all")
    assert len(all_rows) >= len(user_rows) + len(channel_rows)


@pytest.mark.asyncio
async def test_redirect_target_skips_channel_dashboards(db_session):
    ch = _make_channel(db_session)
    await db_session.commit()
    dash = await ensure_channel_dashboard(db_session, ch.id)
    await touch_last_viewed(db_session, dash.slug)
    # Generic redirect should still fall back to default, not to the channel.
    assert await redirect_target_slug(db_session) == "default"


@pytest.mark.asyncio
async def test_channel_dashboard_pin_requires_source_channel_id(db_session):
    """Pinning onto a channel dashboard needs the owning channel to seed FK."""
    ch = _make_channel(db_session)
    await db_session.commit()
    slug = channel_slug(ch.id)

    # Missing source_channel_id → 400.
    with pytest.raises(DomainError) as exc:
        await create_pin(
            db_session, source_kind="adhoc", tool_name="t", envelope=_env(),
            dashboard_key=slug,
        )
    assert exc.value.http_status == 400

    # With it, lazy-create kicks in on the first pin and we land cleanly.
    pin = await create_pin(
        db_session, source_kind="channel", tool_name="t", envelope=_env(),
        source_channel_id=ch.id, dashboard_key=slug,
    )
    assert pin.dashboard_key == slug
    pins = await list_pins(db_session, dashboard_key=slug)
    assert [p.id for p in pins] == [pin.id]


@pytest.mark.asyncio
async def test_channel_dashboard_pin_stacks_in_rail_zone(db_session):
    """Chat-pinned widgets stack vertically at ``x=0`` so the OmniPanel's
    rail-zone filter (``x < railZoneCols``) surfaces them on first pin —
    no dashboard-editor detour required. Width matches the standard tile."""
    ch = _make_channel(db_session)
    await db_session.commit()
    slug = channel_slug(ch.id)

    a = await create_pin(
        db_session, source_kind="channel", tool_name="a", envelope=_env(),
        source_channel_id=ch.id, dashboard_key=slug,
    )
    b = await create_pin(
        db_session, source_kind="channel", tool_name="b", envelope=_env(),
        source_channel_id=ch.id, dashboard_key=slug,
    )

    # Channel + user dashboards share the same 2-col auto-pack formula —
    # new pins land in the grid canvas by default and get moved to Rail /
    # Dock / Header via the zone chip in the editor.
    assert a.grid_layout == {"x": 0, "y": 0, "w": 6, "h": 10}
    assert b.grid_layout == {"x": 6, "y": 0, "w": 6, "h": 10}


@pytest.mark.asyncio
async def test_user_dashboard_pin_uses_alternating_columns(db_session):
    """User dashboards and channel dashboards both 2-col-pack new pins."""
    await create_dashboard(db_session, slug="home", name="Home")
    a = await create_pin(
        db_session, source_kind="adhoc", tool_name="a", envelope=_env(),
        dashboard_key="home",
    )
    b = await create_pin(
        db_session, source_kind="adhoc", tool_name="b", envelope=_env(),
        dashboard_key="home",
    )
    # Position 0 → (x=0, y=0); position 1 → (x=6, y=0). Alternating.
    assert a.grid_layout == {"x": 0, "y": 0, "w": 6, "h": 10}
    assert b.grid_layout == {"x": 6, "y": 0, "w": 6, "h": 10}


@pytest.mark.asyncio
async def test_fine_dashboard_pin_uses_manifest_default_tile(db_session):
    await create_dashboard(
        db_session,
        slug="fine-home",
        name="Fine Home",
        grid_config={"layout_type": "grid", "preset": "fine"},
    )

    a = await create_pin(
        db_session, source_kind="adhoc", tool_name="a", envelope=_env(),
        dashboard_key="fine-home",
    )
    b = await create_pin(
        db_session, source_kind="adhoc", tool_name="b", envelope=_env(),
        dashboard_key="fine-home",
    )

    assert a.grid_layout == {"x": 0, "y": 0, "w": 12, "h": 20}
    assert b.grid_layout == {"x": 12, "y": 0, "w": 12, "h": 20}


@pytest.mark.asyncio
async def test_channel_dashboard_delete_removes_pins(db_session):
    ch = _make_channel(db_session)
    await db_session.commit()
    slug = channel_slug(ch.id)
    await ensure_channel_dashboard(db_session, ch.id)
    await create_pin(
        db_session, source_kind="channel", tool_name="t", envelope=_env(),
        source_channel_id=ch.id, dashboard_key=slug,
    )
    await delete_dashboard(db_session, slug)

    pins = await list_pins(db_session, dashboard_key=slug)
    assert pins == []
    with pytest.raises(DomainError):
        await get_dashboard(db_session, slug)


# --- Grid config: per-dashboard layout preset + atomic pin rescale ---

@pytest.mark.asyncio
async def test_grid_config_defaults_to_null(db_session):
    row = await create_dashboard(db_session, slug="g1", name="G1")
    assert row.grid_config is None


@pytest.mark.asyncio
async def test_update_preset_rescales_pin_coords_standard_to_fine(db_session):
    """Flipping standard→fine (×2 ratio) doubles every pin's x/y/w/h."""
    await create_dashboard(db_session, slug="rescale", name="Rescale")
    pin = await create_pin(
        db_session, source_kind="adhoc", tool_name="t", envelope=_env(),
        dashboard_key="rescale",
    )
    pin.grid_layout = {"x": 3, "y": 2, "w": 6, "h": 6}
    await db_session.commit()

    await update_dashboard(
        db_session, "rescale",
        {"grid_config": {"layout_type": "grid", "preset": "fine"}},
    )
    await db_session.refresh(pin)
    assert pin.grid_layout == {"x": 6, "y": 4, "w": 12, "h": 12}


@pytest.mark.asyncio
async def test_update_preset_rescales_pin_coords_fine_to_standard(db_session):
    """Flipping fine→standard (÷2) halves coords, minimum 1."""
    await create_dashboard(
        db_session, slug="halfit", name="Halfit",
        grid_config={"layout_type": "grid", "preset": "fine"},
    )
    pin = await create_pin(
        db_session, source_kind="adhoc", tool_name="t", envelope=_env(),
        dashboard_key="halfit",
    )
    pin.grid_layout = {"x": 8, "y": 6, "w": 10, "h": 10}
    await db_session.commit()

    await update_dashboard(db_session, "halfit", {"grid_config": None})
    await db_session.refresh(pin)
    assert pin.grid_layout == {"x": 4, "y": 3, "w": 5, "h": 5}


@pytest.mark.asyncio
async def test_update_preset_same_value_no_rescale(db_session):
    """Re-submitting the current preset leaves pins untouched."""
    await create_dashboard(
        db_session, slug="idem", name="Idem",
        grid_config={"layout_type": "grid", "preset": "fine"},
    )
    pin = await create_pin(
        db_session, source_kind="adhoc", tool_name="t", envelope=_env(),
        dashboard_key="idem",
    )
    original = {"x": 4, "y": 4, "w": 8, "h": 8}
    pin.grid_layout = dict(original)
    await db_session.commit()

    await update_dashboard(
        db_session, "idem",
        {"grid_config": {"layout_type": "grid", "preset": "fine"}},
    )
    await db_session.refresh(pin)
    assert pin.grid_layout == original


@pytest.mark.asyncio
async def test_update_preset_unknown_value_treated_as_standard(db_session):
    """An unknown `preset` string is treated as `standard` on read — no
    rescale happens if the dashboard was already on standard. Permissive
    behavior keeps frontend rollouts of new preset IDs non-breaking."""
    await create_dashboard(db_session, slug="rolling", name="Rolling")
    pin = await create_pin(
        db_session, source_kind="adhoc", tool_name="t", envelope=_env(),
        dashboard_key="rolling",
    )
    pin.grid_layout = {"x": 1, "y": 1, "w": 6, "h": 6}
    await db_session.commit()

    await update_dashboard(
        db_session, "rolling",
        {"grid_config": {"layout_type": "grid", "preset": "future-preset"}},
    )
    await db_session.refresh(pin)
    assert pin.grid_layout == {"x": 1, "y": 1, "w": 6, "h": 6}
