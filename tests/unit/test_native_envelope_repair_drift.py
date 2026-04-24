"""Phase N.2 drift-seam sweep: native widget envelope repair on dashboard reload.

The authoritative render envelope for native pins lives in ``widget_instances``;
the pin row caches a copy for fast reads. ``list_pins`` runs
``_sync_native_pin_envelopes`` every call to rebuild the cached envelope from
the instance's current state/config. These tests pin the seams that would
otherwise corrupt a dashboard silently:

- idempotency: two back-to-back reloads must not re-commit unchanged envelopes
- actual repair: an instance state mutation must propagate into the pin's
  cached envelope on the next reload
- orphan pointer: a pin whose widget_instance was deleted must not crash
  ``list_pins`` — the whole dashboard must still render
- cross-kind isolation: non-native pins (no widget_instance_id) are untouched
  by the native sync sweep
- schema-upgrade mid-flight: a pin whose widget_ref is no longer in the
  registry (native spec removed or renamed) must not crash the dashboard;
  the sweep skips it and leaves the cached envelope alone.
"""
from __future__ import annotations

import uuid

import pytest

from app.db.models import WidgetInstance
from app.services.dashboard_pins import create_pin, list_pins
from app.services.native_app_widgets import (
    NATIVE_APP_CONTENT_TYPE,
    build_native_widget_preview_envelope,
)
from tests.factories import build_channel


# ---------------------------------------------------------------------------
# Idempotency — back-to-back reloads must not churn envelopes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_pins_native_sync_is_idempotent_across_reloads(db_session):
    """Two sequential ``list_pins`` calls produce the same envelope and do not
    mark it dirty on the second pass.

    Drift pin: a regression that re-serializes even when state is unchanged
    would cause every dashboard read to commit ``updated_at``, thrashing
    downstream caches and producing spurious activity in audit logs.
    """
    pin = await create_pin(
        db_session,
        source_kind="adhoc",
        tool_name="core/todo_native",
        envelope=build_native_widget_preview_envelope("core/todo_native"),
    )

    first_rows = await list_pins(db_session)
    first = next(r for r in first_rows if r.id == pin.id)
    first_envelope = dict(first.envelope)
    first_updated_at = first.updated_at

    second_rows = await list_pins(db_session)
    second = next(r for r in second_rows if r.id == pin.id)

    assert second.envelope == first_envelope
    assert second.updated_at == first_updated_at


# ---------------------------------------------------------------------------
# Actual repair — state mutation propagates into envelope on next reload
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_pins_rebuilds_envelope_after_instance_state_change(
    db_session,
):
    """The pin's cached envelope must reflect the instance's updated state on
    the next ``list_pins`` call — this is the whole point of the sync.

    Drift pin: if ``_sync_native_pin_envelopes`` ever short-circuits on
    ``row.widget_kind != 'native_app'`` at the wrong layer, or stops calling
    ``build_envelope_for_native_instance``, state mutations become invisible
    to the dashboard until a full restart.
    """
    channel = build_channel()
    db_session.add(channel)
    await db_session.commit()
    channel_id = channel.id
    pin = await create_pin(
        db_session,
        dashboard_key=f"channel:{channel_id}",
        source_kind="channel",
        source_channel_id=channel_id,
        tool_name="core/pinned_files_native",
        envelope=build_native_widget_preview_envelope("core/pinned_files_native"),
        zone="dock",
    )
    original_state = dict(pin.envelope["body"]["state"])
    assert original_state.get("pinned_files") == []

    instance = await db_session.get(WidgetInstance, pin.widget_instance_id)
    assert instance is not None
    instance.state = {
        **original_state,
        "pinned_files": [
            {"path": "notes.md", "pinned_at": "2026-04-23T10:00:00+00:00",
             "pinned_by": "user"},
        ],
        "active_path": "notes.md",
        "updated_at": "2026-04-23T10:00:00+00:00",
    }
    await db_session.commit()

    rows = await list_pins(db_session, dashboard_key=f"channel:{channel_id}")
    row = next(r for r in rows if r.id == pin.id)
    assert row.envelope["body"]["state"]["active_path"] == "notes.md"
    rebuilt_files = row.envelope["body"]["state"]["pinned_files"]
    assert len(rebuilt_files) == 1
    assert rebuilt_files[0]["path"] == "notes.md"


# ---------------------------------------------------------------------------
# Orphan pointer — widget_instance deleted, pin must not crash the dashboard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_pins_tolerates_orphaned_widget_instance_pointer(db_session):
    """Deleting the backing ``WidgetInstance`` leaves a pin with a stale
    ``widget_instance_id`` FK. The native sync sweep must skip such rows —
    ``list_pins`` must still return the other pins successfully.

    Drift pin: if a future refactor drops the ``instance is None`` guard in
    ``_sync_native_pin_envelopes``, a single orphaned pin 500s every dashboard
    read across the whole deployment.
    """
    # Native pin whose instance we will delete.
    native_pin = await create_pin(
        db_session,
        source_kind="adhoc",
        tool_name="core/todo_native",
        envelope=build_native_widget_preview_envelope("core/todo_native"),
    )
    # Healthy sibling pin, so we can assert the sweep does not crash wholesale.
    sibling = await create_pin(
        db_session,
        source_kind="adhoc",
        tool_name="core/notes_native",
        envelope=build_native_widget_preview_envelope("core/notes_native"),
    )

    instance = await db_session.get(WidgetInstance, native_pin.widget_instance_id)
    assert instance is not None
    await db_session.delete(instance)
    await db_session.commit()

    # Must not raise. The orphan pin is returned with its cached envelope
    # intact; the sibling renders normally.
    rows = await list_pins(db_session)
    ids = {r.id for r in rows}
    assert native_pin.id in ids
    assert sibling.id in ids

    orphan = next(r for r in rows if r.id == native_pin.id)
    # Envelope was not repaired (no source) — it stays as originally cached.
    assert orphan.envelope.get("content_type") == NATIVE_APP_CONTENT_TYPE


# ---------------------------------------------------------------------------
# Cross-kind isolation — non-native pins are untouched by the sync
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_pins_does_not_touch_non_native_pins_during_sync(db_session):
    """Pins without a ``widget_instance_id`` (ad-hoc tool-result pins, HTML
    widgets) must pass through the sweep unchanged.

    Drift pin: if the sweep ever widens its eligibility (e.g. trying to
    rebuild envelopes for HTML widgets from a phantom instance), it will
    corrupt pinned HTML widgets on every dashboard read.
    """
    generic = await create_pin(
        db_session,
        source_kind="adhoc",
        tool_name="some_tool",
        envelope={
            "content_type": "application/vnd.spindrel.components+json",
            "body": "{}",
            "plain_body": "ok",
            "display": "inline",
            "truncated": False,
            "record_id": None,
            "byte_size": 2,
            "display_label": "Generic",
        },
    )
    original_envelope = dict(generic.envelope)
    assert generic.widget_instance_id is None

    rows = await list_pins(db_session)
    row = next(r for r in rows if r.id == generic.id)

    assert row.widget_instance_id is None
    assert row.envelope == original_envelope


# ---------------------------------------------------------------------------
# Schema upgrade mid-flight — widget_ref removed from registry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_pins_skips_pins_with_missing_widget_spec(
    db_session, monkeypatch,
):
    """A pin whose ``widget_ref`` is no longer in ``_REGISTRY`` (spec removed
    or renamed between deploy versions) must not crash the sweep. The pin
    stays in the return set with its cached envelope intact, identical to
    the orphaned-instance branch; healthy sibling pins render normally.

    Regression guard for the N.2 fix at
    ``app/services/dashboard_pins.py::_sync_native_pin_envelopes`` —
    ``HTTPException`` from ``build_envelope_for_native_instance`` is caught
    and the row is skipped.
    """
    stale_pin = await create_pin(
        db_session,
        source_kind="adhoc",
        tool_name="core/todo_native",
        envelope=build_native_widget_preview_envelope("core/todo_native"),
    )
    sibling = await create_pin(
        db_session,
        source_kind="adhoc",
        tool_name="core/notes_native",
        envelope=build_native_widget_preview_envelope("core/notes_native"),
    )
    assert stale_pin.widget_instance_id is not None
    cached_stale_envelope = dict(stale_pin.envelope)

    # Simulate a deploy-time registry removal: only ``core/notes_native``
    # survives the restart.
    from app.services.native_app_widgets import _REGISTRY as live_registry
    surviving = {"core/notes_native": live_registry["core/notes_native"]}
    monkeypatch.setattr(
        "app.services.native_app_widgets._REGISTRY", surviving,
    )

    rows = await list_pins(db_session)
    ids = {r.id for r in rows}
    assert stale_pin.id in ids
    assert sibling.id in ids

    stale = next(r for r in rows if r.id == stale_pin.id)
    # Cached envelope is preserved — the sweep didn't touch it.
    assert stale.envelope == cached_stale_envelope
    assert stale.envelope.get("content_type") == NATIVE_APP_CONTENT_TYPE
