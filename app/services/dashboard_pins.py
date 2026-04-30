"""CRUD helpers for the ``widget_dashboard_pins`` table.

Keeps the router thin and lets the widget-actions layer reuse the shared
config-patch helper without importing the router module (mirrors
``app/routers/api_v1_channels.py::apply_widget_config_patch``).
"""
from __future__ import annotations

import copy
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from app.domain.errors import DomainError, NotFoundError, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import ApiKey, Bot, WidgetDashboard, WidgetDashboardPin, WidgetInstance, WorkspaceSpatialNode
from app.services.dashboard_grid import (
    DEFAULT_PRESET,
    default_grid_layout as _manifest_default_grid_layout,
    header_cols as _manifest_header_cols,
    resolve_preset_name as _resolve_manifest_preset_name,
)
from app.services.native_app_widgets import (
    NATIVE_APP_CONTENT_TYPE,
    build_envelope_for_native_instance,
    extract_native_widget_ref_from_envelope,
    get_or_create_native_widget_instance,
)
from app.services.pin_contract import (
    ContractSnapshot,
    PinMetadataView,
    compute_pin_metadata,
    reconcile_pin_metadata,
    render_pin_metadata,
)
from app.services.widget_layout import (
    VALID_ZONES,
    clamp_layout_size_to_hints,
    resolve_zone_from_layout_hints,
)

logger = logging.getLogger(__name__)


DEFAULT_DASHBOARD_KEY = "default"

# Envelope content_type that renders inside the bot-authenticated iframe.
# Pins of this type need a resolvable bot with an active API key; any other
# content_type renders without needing ``/widget-auth/mint``.
_HTML_INTERACTIVE_CT = "application/vnd.spindrel.html+interactive"


_VALID_LAYOUT_KEYS = {"x", "y", "w", "h"}
_HEADER_DEFAULT_LAYOUT = {"x": 0, "y": 0, "w": 6, "h": 2}
_HEADER_CHIP_LAYOUT = {"x": 0, "y": 0, "w": 4, "h": 1}


def _seed_widget_config(tool_name: str, envelope: dict, widget_config: dict | None) -> dict:
    """Backfill per-pin config from the rendered envelope when a widget's
    refresh contract needs an explicit binding key.

    Home Assistant's ``ha_get_state`` widget now polls via ``config.entity_id``
    instead of scraping identity back out of ``display_label`` on every refresh.
    Existing preview/pin flows do not yet send widget_config explicitly, so
    seed the binding once at pin-create time from the emitted envelope.
    """
    merged = dict(widget_config or {})
    bare_tool_name = tool_name.split("-", 1)[1] if "-" in tool_name else tool_name
    if bare_tool_name == "ha_get_state" and not merged.get("entity_id"):
        display_label = (envelope.get("display_label") or "").strip()
        if display_label:
            merged["entity_id"] = display_label
    return merged


def _default_grid_layout(
    position: int,
    *,
    channel: bool = False,
    preset_name: str = DEFAULT_PRESET,
) -> dict[str, int]:
    """Compute a day-0 layout slot for a pin at the given position.

    User + channel dashboards both land new pins in the main grid canvas by
    default (2-col flow, mirrors migration 211's backfill formula). The
    ``channel`` flag is kept for call-site intent and test compatibility but
    no longer selects a Rail-specific 1-col slot — "Add widget" should drop
    into the page the user is looking at, which is the Grid canvas. Moves
    to Rail / Dock / Header happen via the zone chip.
    """
    return _manifest_default_grid_layout(position, preset_name=preset_name)


def _resolve_dashboard_preset_name(grid_config: dict | None) -> str:
    return _resolve_manifest_preset_name(grid_config)


def _header_cols_for_preset(preset_name: str) -> int:
    return _manifest_header_cols(preset_name)


def _default_layout_for_zone(
    position: int,
    zone: str,
    *,
    channel: bool = False,
    preset_name: str = DEFAULT_PRESET,
) -> dict[str, int]:
    if zone == "header":
        return dict(_HEADER_DEFAULT_LAYOUT)
    if zone in ("rail", "dock"):
        return {"x": 0, "y": position * 10, "w": 1, "h": 10}
    return _default_grid_layout(position, channel=channel, preset_name=preset_name)


def _seed_layout_from_hints(
    position: int,
    *,
    resolved_zone: str,
    layout_hints: object,
    channel: bool = False,
    preset_name: str = DEFAULT_PRESET,
    apply_size_hints: bool = True,
) -> dict[str, int]:
    preferred_zone = (
        layout_hints.get("preferred_zone").strip()
        if isinstance(layout_hints, dict)
        and isinstance(layout_hints.get("preferred_zone"), str)
        and layout_hints.get("preferred_zone").strip()
        else None
    )
    if preferred_zone == "chip" and resolved_zone == "header":
        base = dict(_HEADER_CHIP_LAYOUT)
    else:
        base = _default_layout_for_zone(
            position,
            resolved_zone,
            channel=channel,
            preset_name=preset_name,
        )
    clamped = (
        clamp_layout_size_to_hints(base, layout_hints=layout_hints)
        if apply_size_hints
        else base
    )
    return _normalize_coords_for_zone(clamped, resolved_zone, preset_name=preset_name)


def _pin_is_fully_stamped(pin: WidgetDashboardPin) -> bool:
    """Gate for the snapshot-only read path.

    A row is "fully stamped" when every column the read path needs is
    populated AND ``source_stamp`` is set (proof a Phase 1+ writer or the
    Phase 2 backfill produced this row). ``config_schema_snapshot`` is
    intentionally NOT in the gate — many widgets legitimately have no
    config schema, and a NULL there must not force a cold-path reconcile.
    """
    return (
        pin.source_stamp is not None
        and pin.widget_origin is not None
        and pin.provenance_confidence is not None
        and pin.widget_contract_snapshot is not None
        and pin.widget_presentation_snapshot is not None
    )


def serialize_pin(pin: WidgetDashboardPin) -> dict[str, Any]:
    """Serialize a pin row to a JSON-safe dict for API responses.

    Hot path: ``render_pin_metadata`` reads only the snapshot columns when
    the pin is fully stamped. Stragglers fall back to ``compute_pin_metadata``
    which walks the resolver chain — they should be rare after Phase 2
    backfill, but the fallback keeps hand-edited / restored-from-backup
    rows serving correctly.
    """
    if _pin_is_fully_stamped(pin):
        view = render_pin_metadata(pin)
    else:
        snapshot = ContractSnapshot(
            widget_contract=pin.widget_contract_snapshot,
            config_schema=pin.config_schema_snapshot,
            widget_presentation=pin.widget_presentation_snapshot,
        )
        caller_origin = (
            pin.widget_origin
            if pin.provenance_confidence == "authoritative"
            and isinstance(pin.widget_origin, dict)
            and pin.widget_origin
            else None
        )
        view, _ = compute_pin_metadata(
            tool_name=pin.tool_name,
            envelope=pin.envelope or {},
            source_bot_id=pin.source_bot_id,
            caller_origin=caller_origin,
            snapshot=snapshot,
        )
    data = {
        "id": str(pin.id),
        "dashboard_key": pin.dashboard_key,
        "position": pin.position,
        "source_kind": pin.source_kind,
        "source_channel_id": str(pin.source_channel_id) if pin.source_channel_id else None,
        "widget_instance_id": str(pin.widget_instance_id) if pin.widget_instance_id else None,
        "source_bot_id": pin.source_bot_id,
        "tool_name": pin.tool_name,
        "tool_args": pin.tool_args or {},
        "widget_config": pin.widget_config or {},
        "widget_origin": view.widget_origin,
        "provenance_confidence": view.provenance_confidence,
        "envelope": pin.envelope or {},
        "display_label": pin.display_label,
        "grid_layout": pin.grid_layout or {},
        "is_main_panel": bool(pin.is_main_panel),
        "zone": pin.zone or "grid",
        "pinned_at": pin.pinned_at.isoformat() if pin.pinned_at else None,
        "updated_at": pin.updated_at.isoformat() if pin.updated_at else None,
        "config_schema": view.config_schema,
        "widget_contract": view.widget_contract,
        "widget_presentation": view.widget_presentation,
    }
    widget_presentation = view.widget_presentation
    if isinstance(widget_presentation, dict):
        data["panel_title"] = widget_presentation.get("panel_title")
        data["show_panel_title"] = widget_presentation.get("show_panel_title")
        data["layout_hints"] = widget_presentation.get("layout_hints")
    return data


def _refresh_pin_contract_metadata(pin: WidgetDashboardPin) -> bool:
    """Thin wrapper around ``reconcile_pin_metadata`` for back-compat.

    Phase 3 flipped the implementation to the new resolver chain. The
    function name is preserved so the existing drift-guard test suite
    (``tests/unit/test_refresh_pin_contract_metadata.py``) and any
    Phase 1-era callers keep working unchanged. ``reconcile_pin_metadata``
    additionally writes ``source_stamp``, which is the desired side-effect
    on every refresh.
    """
    return reconcile_pin_metadata(pin)


async def _sync_native_pin_envelopes(
    db: AsyncSession,
    rows: list[WidgetDashboardPin],
) -> bool:
    """Rebuild native pin envelopes from their authoritative widget instance state.

    The pin row caches a render envelope for fast reads, but for native widgets
    the durable state lives in ``widget_instances``. If the cached envelope ever
    drifts, a fresh dashboard load should repair it rather than re-serving stale
    state after refresh.
    """
    instance_ids = [
        row.widget_instance_id
        for row in rows
        if row.widget_instance_id is not None
    ]
    if not instance_ids:
        return False

    instances = (
        await db.execute(
            select(WidgetInstance).where(WidgetInstance.id.in_(instance_ids))
        )
    ).scalars().all()
    by_id = {instance.id: instance for instance in instances}

    dirty = False
    for row in rows:
        if row.widget_instance_id is None:
            continue
        instance = by_id.get(row.widget_instance_id)
        if instance is None or instance.widget_kind != "native_app":
            continue
        display_label = row.display_label or (row.envelope or {}).get("display_label")
        try:
            envelope = build_envelope_for_native_instance(
                instance,
                display_label=display_label,
                source_bot_id=row.source_bot_id,
            )
        except DomainError:
            # Spec removed/renamed between deploy versions. Leave the cached
            # envelope alone so the rest of the dashboard still renders —
            # identical failure mode to the ``instance is None`` branch above.
            logger.warning(
                "native envelope repair skipped: widget_ref=%s on pin=%s no longer "
                "registered; serving cached envelope",
                instance.widget_ref, row.id,
            )
            continue
        if row.envelope != envelope:
            row.envelope = envelope
            row.display_label = envelope.get("display_label") or row.display_label
            flag_modified(row, "envelope")
            dirty = True

    return dirty


async def list_pins(
    db: AsyncSession, *, dashboard_key: str = DEFAULT_DASHBOARD_KEY,
) -> list[WidgetDashboardPin]:
    dashboard = (
        await db.execute(
            select(WidgetDashboard.grid_config).where(WidgetDashboard.slug == dashboard_key)
        )
    ).first()
    preset_name = _resolve_dashboard_preset_name(dashboard[0] if dashboard else None)
    rows = (await db.execute(
        select(WidgetDashboardPin)
        .where(WidgetDashboardPin.dashboard_key == dashboard_key)
        .order_by(WidgetDashboardPin.position.asc(), WidgetDashboardPin.pinned_at.asc())
    )).scalars().all()
    # Self-heal any pins whose grid_layout violates zone invariants. Stale coords
    # from earlier preset changes or pre-zone-column code can leave header pins
    # with w=24 or y=2 that explode the horizontal chip strip at render time;
    # normalizing here is a one-shot correction on the next read.
    dirty = False
    for row in rows:
        gl = row.grid_layout
        if isinstance(gl, dict) and gl:
            if (row.zone or "grid") == "header" and gl == {"x": 0, "y": 0, "w": 1, "h": 1}:
                normalized = dict(_HEADER_CHIP_LAYOUT)
            else:
                normalized = _normalize_coords_for_zone(gl, row.zone or "grid", preset_name=preset_name)
            if normalized != gl:
                row.grid_layout = normalized
                flag_modified(row, "grid_layout")
                dirty = True
        # Reconcile only un-stamped / under-populated rows. Fully-stamped
        # rows serve straight from snapshot columns via ``render_pin_metadata``
        # in ``serialize_pin`` — no registry / filesystem reads on the hot
        # path. The fallback keeps hand-edited or backup-restored rows alive.
        if not _pin_is_fully_stamped(row):
            if reconcile_pin_metadata(row):
                dirty = True
    if await _sync_native_pin_envelopes(db, rows):
        dirty = True
    if dirty:
        await db.commit()
    return list(rows)


async def _next_position(
    db: AsyncSession, *, dashboard_key: str,
) -> int:
    max_pos = (await db.execute(
        select(func.max(WidgetDashboardPin.position))
        .where(WidgetDashboardPin.dashboard_key == dashboard_key)
    )).scalar()
    return (max_pos + 1) if max_pos is not None else 0


@dataclass(frozen=True)
class _PinDashboardContext:
    dashboard_key: str
    is_channel: bool
    preset_name: str
    position: int


@dataclass(frozen=True)
class _ResolvedNativePinPayload:
    envelope: dict
    widget_instance_id: uuid.UUID | None


@dataclass(frozen=True)
class _PinMetadataLayout:
    view: PinMetadataView
    source_stamp: str | None
    resolved_zone: str
    grid_layout: dict


def _validate_pin_create_input(
    *,
    source_kind: str,
    tool_name: str,
    envelope: dict,
) -> None:
    if source_kind not in ("channel", "adhoc"):
        raise ValidationError(f"Invalid source_kind: {source_kind}")
    if not tool_name:
        raise ValidationError("tool_name is required")
    if not isinstance(envelope, dict) or not envelope:
        raise ValidationError("envelope must be a non-empty object")


def _validate_explicit_pin_zone(zone: str | None) -> None:
    if zone is not None and zone not in VALID_ZONES:
        raise ValidationError(f"Invalid zone: {zone}")


async def _resolve_pin_bot_identity(
    db: AsyncSession,
    *,
    envelope: dict,
    source_bot_id: str | None,
) -> str | None:
    # Pin identity rule: the envelope's source_bot_id is stamped from
    # current_bot_id at emission time — that's the authoritative bot. Any
    # source_bot_id arg passed separately is a UI signal that can lag
    # behind (stale store, missing field, fallback literal). Prefer the
    # envelope; warn on mismatch so future UI drift is visible in logs.
    envelope_bot_id = envelope.get("source_bot_id")
    if envelope_bot_id and source_bot_id and envelope_bot_id != source_bot_id:
        logger.warning(
            "create_pin source_bot_id mismatch: envelope=%s body=%s — using envelope",
            envelope_bot_id, source_bot_id,
        )
    resolved_bot_id: str | None = envelope_bot_id or source_bot_id

    # Validate the bot. NULL is allowed (pin without iframe auth needs). A
    # non-null value must resolve to a real bot; interactive-HTML pins also
    # require an active API key (otherwise /widget-auth/mint 400s on every
    # refresh forever — silent-persist of a permanently broken pin).
    if resolved_bot_id is not None:
        bot = await db.get(Bot, resolved_bot_id)
        if bot is None:
            raise ValidationError(f"Unknown source_bot_id: {resolved_bot_id!r}")
        if envelope.get("content_type") == _HTML_INTERACTIVE_CT:
            bot_label = bot.display_name or bot.name or bot.id
            if bot.api_key_id is None:
                raise ValidationError(
                    f"Bot '{bot_label}' has no API permissions — interactive "
                    "widgets need an API key to mint iframe tokens. Grant "
                    f"scopes under Admin → Bots → {bot_label} → Permissions.",
                )
            api_key = await db.get(ApiKey, bot.api_key_id)
            if api_key is None or not api_key.is_active:
                raise ValidationError(
                    f"Bot '{bot_label}' has an inactive API key — interactive "
                    "widgets need one to mint iframe tokens. Re-enable under "
                    f"Admin → Bots → {bot_label} → Permissions.",
                )
    return resolved_bot_id


async def _resolve_pin_dashboard_context(
    db: AsyncSession,
    *,
    dashboard_key: str,
    source_channel_id: uuid.UUID | None,
) -> _PinDashboardContext:
    # Validate dashboard exists so we get a clean 404 (not an FK violation).
    # Imported lazily to avoid a module-level cycle with app.services.dashboards
    # which depends on us for DEFAULT_DASHBOARD_KEY.
    #
    # Channel dashboards (``channel:<uuid>``) are lazy-created on first pin —
    # users never "create" a channel dashboard; dropping the first widget on
    # one auto-allocates the WidgetDashboard row.
    from app.services.dashboards import (
        ensure_channel_dashboard,
        get_dashboard,
        is_channel_slug,
    )
    is_channel = is_channel_slug(dashboard_key)
    if is_channel:
        if source_channel_id is None:
            raise ValidationError(
                "source_channel_id is required when pinning to a channel dashboard",
            )
        await ensure_channel_dashboard(db, source_channel_id)
    dashboard = await get_dashboard(db, dashboard_key)
    return _PinDashboardContext(
        dashboard_key=dashboard_key,
        is_channel=is_channel,
        preset_name=_resolve_dashboard_preset_name(
            getattr(dashboard, "grid_config", None),
        ),
        position=await _next_position(db, dashboard_key=dashboard_key),
    )


async def _resolve_native_pin_payload(
    db: AsyncSession,
    *,
    envelope: dict,
    widget_config: dict,
    display_label: str | None,
    source_bot_id: str | None,
    dashboard_key: str,
    source_channel_id: uuid.UUID | None,
    override_widget_instance: "WidgetInstance | None",
) -> _ResolvedNativePinPayload:
    if envelope.get("content_type") != NATIVE_APP_CONTENT_TYPE:
        return _ResolvedNativePinPayload(envelope=envelope, widget_instance_id=None)

    widget_ref = extract_native_widget_ref_from_envelope(envelope)
    if not widget_ref:
        raise ValidationError("native widget envelope is missing widget_ref")
    if override_widget_instance is not None:
        # Caller already created a WidgetInstance (e.g. Standing Orders,
        # which need multiple instances per channel with unique scope_ref).
        # Skip the singleton get-or-create path and use the supplied one.
        instance = override_widget_instance
    else:
        instance = await get_or_create_native_widget_instance(
            db,
            widget_ref=widget_ref,
            dashboard_key=dashboard_key,
            source_channel_id=source_channel_id,
            config=widget_config or {},
        )
    return _ResolvedNativePinPayload(
        widget_instance_id=instance.id,
        envelope=build_envelope_for_native_instance(
            instance,
            display_label=display_label or envelope.get("display_label"),
            source_bot_id=source_bot_id,
        ),
    )


def _resolve_pin_metadata_layout(
    *,
    tool_name: str,
    envelope: dict,
    source_bot_id: str | None,
    widget_origin: dict | None,
    zone: str | None,
    grid_layout: dict | None,
    dashboard: _PinDashboardContext,
) -> _PinMetadataLayout:
    _validate_explicit_pin_zone(zone)

    # Phase 3: single compute call produces origin/confidence/snapshots AND
    # the source_stamp in one pass. We need the resolved view BEFORE
    # constructing the row so layout_hints can drive initial zone seeding.
    view, source_stamp = compute_pin_metadata(
        tool_name=tool_name,
        envelope=envelope,
        source_bot_id=source_bot_id,
        caller_origin=widget_origin,
    )
    widget_presentation = view.widget_presentation
    layout_hints = (
        widget_presentation.get("layout_hints")
        if isinstance(widget_presentation, dict)
        else None
    )
    hinted_zone = resolve_zone_from_layout_hints(layout_hints)
    resolved_zone = zone or hinted_zone or "grid"
    if resolved_zone not in VALID_ZONES:
        raise ValidationError(f"Invalid zone: {resolved_zone}")

    resolved_grid_layout = (
        _normalize_coords_for_zone(
            grid_layout,
            resolved_zone,
            preset_name=dashboard.preset_name,
        )
        if isinstance(grid_layout, dict)
        else _seed_layout_from_hints(
            dashboard.position,
            resolved_zone=resolved_zone,
            layout_hints=layout_hints,
            channel=dashboard.is_channel,
            preset_name=dashboard.preset_name,
            apply_size_hints=zone is None or zone == hinted_zone,
        )
    )
    return _PinMetadataLayout(
        view=view,
        source_stamp=source_stamp,
        resolved_zone=resolved_zone,
        grid_layout=resolved_grid_layout,
    )


def _build_pin_row(
    *,
    dashboard: _PinDashboardContext,
    source_kind: str,
    source_channel_id: uuid.UUID | None,
    native_payload: _ResolvedNativePinPayload,
    source_bot_id: str | None,
    tool_name: str,
    tool_args: dict | None,
    widget_config: dict,
    display_label: str | None,
    metadata_layout: _PinMetadataLayout,
) -> WidgetDashboardPin:
    view = metadata_layout.view
    envelope = native_payload.envelope
    return WidgetDashboardPin(
        dashboard_key=dashboard.dashboard_key,
        position=dashboard.position,
        source_kind=source_kind,
        source_channel_id=source_channel_id,
        widget_instance_id=native_payload.widget_instance_id,
        source_bot_id=source_bot_id,
        tool_name=tool_name,
        tool_args=tool_args or {},
        widget_config=widget_config or {},
        widget_origin=view.widget_origin or None,
        provenance_confidence=view.provenance_confidence,
        widget_contract_snapshot=copy.deepcopy(view.widget_contract)
        if view.widget_contract is not None
        else None,
        config_schema_snapshot=copy.deepcopy(view.config_schema)
        if view.config_schema is not None
        else None,
        widget_presentation_snapshot=copy.deepcopy(view.widget_presentation)
        if view.widget_presentation is not None
        else None,
        source_stamp=metadata_layout.source_stamp,
        envelope=envelope,
        display_label=display_label or envelope.get("display_label"),
        grid_layout=metadata_layout.grid_layout,
        zone=metadata_layout.resolved_zone,
    )


async def _register_pin_post_commit_hooks(
    db: AsyncSession,
    pin: WidgetDashboardPin,
) -> None:
    # Register any @on_cron handlers declared in the bundle's widget.yaml.
    # Best-effort: a bundle with no manifest or no cron entries is a no-op.
    try:
        from app.services.widget_cron import register_pin_crons
        await register_pin_crons(db, pin)
    except Exception:
        logger.exception("register_pin_crons failed for pin %s", pin.id)

    # Register any @on_event handlers. Also best-effort; a failure here
    # must not take down the pin write.
    try:
        from app.services.widget_events import register_pin_events
        await register_pin_events(db, pin)
    except Exception:
        logger.exception("register_pin_events failed for pin %s", pin.id)


async def _ensure_channel_pin_spatial_projection(
    db: AsyncSession,
    pin: WidgetDashboardPin,
) -> None:
    """Channel dashboard -> Spatial Canvas projection.

    Channel-associated widgets should read as one user-facing object across
    the channel dashboard and workspace map. Internally they remain two pin
    rows because the Spatial Canvas stores widget nodes through the reserved
    ``workspace:spatial`` dashboard.
    """
    from app.services.dashboards import is_channel_slug

    if not is_channel_slug(pin.dashboard_key) or pin.source_channel_id is None:
        return
    origin = pin.widget_origin or {}
    if isinstance(origin, dict) and origin.get("source_spatial_pin_id"):
        return
    from app.services.workspace_spatial import pin_dashboard_pin_to_canvas

    await pin_dashboard_pin_to_canvas(db, source_dashboard_pin_id=pin.id)


async def _delete_linked_channel_spatial_rows(
    db: AsyncSession,
    pin: WidgetDashboardPin,
) -> None:
    """Delete paired rows for channel-dashboard/spatial projections.

    This is intentionally internal and direct so delete flows can opt out
    during recursive paired cleanup without bouncing through public service
    functions forever.
    """
    from app.services.dashboards import WORKSPACE_SPATIAL_DASHBOARD_KEY, is_channel_slug

    if is_channel_slug(pin.dashboard_key):
        rows = (
            await db.execute(
                select(WidgetDashboardPin, WorkspaceSpatialNode)
                .join(
                    WorkspaceSpatialNode,
                    WorkspaceSpatialNode.widget_pin_id == WidgetDashboardPin.id,
                )
                .where(WidgetDashboardPin.dashboard_key == WORKSPACE_SPATIAL_DASHBOARD_KEY)
            )
        ).all()
        for spatial_pin, node in rows:
            origin = spatial_pin.widget_origin or {}
            if isinstance(origin, dict) and origin.get("source_dashboard_pin_id") == str(pin.id):
                await db.delete(node)
                await db.delete(spatial_pin)
        return

    if pin.dashboard_key != WORKSPACE_SPATIAL_DASHBOARD_KEY:
        return

    origin = pin.widget_origin or {}
    source_dashboard_pin_id = origin.get("source_dashboard_pin_id") if isinstance(origin, dict) else None
    source_spatial_pin_id = str(pin.id)

    channel_rows = (
        await db.execute(
            select(WidgetDashboardPin).where(
                WidgetDashboardPin.dashboard_key.like("channel:%"),
            )
        )
    ).scalars().all()
    for channel_pin in channel_rows:
        channel_origin = channel_pin.widget_origin or {}
        if not isinstance(channel_origin, dict):
            continue
        if source_dashboard_pin_id and str(channel_pin.id) == source_dashboard_pin_id:
            await db.delete(channel_pin)
            continue
        if channel_origin.get("source_spatial_pin_id") == source_spatial_pin_id:
            await db.delete(channel_pin)


async def create_pin(
    db: AsyncSession,
    *,
    source_kind: str,
    tool_name: str,
    envelope: dict,
    source_channel_id: uuid.UUID | None = None,
    source_bot_id: str | None = None,
    tool_args: dict | None = None,
    widget_config: dict | None = None,
    widget_origin: dict | None = None,
    display_label: str | None = None,
    dashboard_key: str = DEFAULT_DASHBOARD_KEY,
    zone: str | None = None,
    grid_layout: dict | None = None,
    override_widget_instance: "WidgetInstance | None" = None,
    commit: bool = True,
) -> WidgetDashboardPin:
    _validate_pin_create_input(
        source_kind=source_kind,
        tool_name=tool_name,
        envelope=envelope,
    )
    source_bot_id = await _resolve_pin_bot_identity(
        db,
        envelope=envelope,
        source_bot_id=source_bot_id,
    )
    dashboard = await _resolve_pin_dashboard_context(
        db,
        dashboard_key=dashboard_key,
        source_channel_id=source_channel_id,
    )
    widget_config = _seed_widget_config(tool_name, envelope, widget_config)
    _validate_explicit_pin_zone(zone)
    native_payload = await _resolve_native_pin_payload(
        db,
        envelope=envelope,
        widget_config=widget_config,
        display_label=display_label,
        source_bot_id=source_bot_id,
        dashboard_key=dashboard_key,
        source_channel_id=source_channel_id,
        override_widget_instance=override_widget_instance,
    )
    metadata_layout = _resolve_pin_metadata_layout(
        tool_name=tool_name,
        envelope=native_payload.envelope,
        source_bot_id=source_bot_id,
        widget_origin=widget_origin,
        zone=zone,
        grid_layout=grid_layout,
        dashboard=dashboard,
    )
    pin = _build_pin_row(
        dashboard=dashboard,
        source_kind=source_kind,
        source_channel_id=source_channel_id,
        native_payload=native_payload,
        source_bot_id=source_bot_id,
        tool_name=tool_name,
        tool_args=tool_args,
        widget_config=widget_config,
        display_label=display_label,
        metadata_layout=metadata_layout,
    )
    db.add(pin)
    await db.flush()
    if commit:
        await db.commit()
        await db.refresh(pin)
    # When commit=False the caller composes a wider transaction (e.g. pin a
    # widget AND create its workspace_spatial_nodes row atomically). Caller
    # is responsible for the final commit + refresh and for invoking the
    # post-commit cron/event registration once the row is durable.

    if not commit:
        return pin

    await _register_pin_post_commit_hooks(db, pin)
    await _ensure_channel_pin_spatial_projection(db, pin)
    return pin


async def create_suite_pins(
    db: AsyncSession,
    *,
    suite_id: str,
    dashboard_key: str,
    source_bot_id: str | None = None,
    source_channel_id: uuid.UUID | None = None,
    member_slugs: list[str] | None = None,
) -> list[WidgetDashboardPin]:
    """Bulk-pin every member of a suite onto a dashboard in one transaction.

    Each member is pinned via the existing ``create_pin`` validation pipeline,
    so the usual guards (bot identity, API-key scopes, channel-dashboard
    reservation) apply. If any member fails, nothing is committed.

    ``member_slugs`` may narrow the set (e.g. pin only `mc_kanban` + `mc_tasks`,
    skip the timeline). Defaults to the full suite member list.

    The envelope for each member is a minimal shape that matches what
    ``emit_html_widget`` produces for a path-mode widget: ``content_type``
    is the interactive-HTML tag, ``source_path`` is ``<member>/index.html``
    relative to the source_kind's widget root (``BUILTIN_WIDGET_ROOT`` for
    builtin suites, ``integrations/<id>/widgets/`` for integration suites),
    plus the bot / channel identity fields. Widget JWT minting + runtime
    scoping fall out of these fields at render time.
    """
    from app.services.widget_suite import load_suite

    suite = load_suite(suite_id)
    if suite is None:
        raise NotFoundError(f"Unknown suite: {suite_id!r}")

    requested = member_slugs or suite.members
    for m in requested:
        if m not in suite.members:
            raise ValidationError(
                f"{m!r} is not a member of suite {suite_id!r}",
            )

    # Resolve source_kind + integration_id from the suite's on-disk location.
    # Built-in suites live under ``app/tools/local/widgets/<suite_id>/``; integration
    # suites live under ``integrations/<id>/widgets/<suite_id>/``. The iframe
    # renderer dispatches to different content endpoints per source_kind, so
    # stamping the right discriminator is load-bearing.
    source_kind = "channel"
    source_integration_id: str | None = None
    if suite.source_path is not None:
        parts = suite.source_path.parts
        if "integrations" in parts:
            idx = parts.index("integrations")
            if idx + 1 < len(parts):
                source_kind = "integration"
                source_integration_id = parts[idx + 1]
        else:
            source_kind = "builtin"

    created: list[WidgetDashboardPin] = []
    try:
        for member in requested:
            envelope = {
                "content_type": _HTML_INTERACTIVE_CT,
                "body": "",
                "plain_body": member,
                "display": "inline",
                "source_path": f"{member}/index.html",
                "source_kind": source_kind,
                "source_integration_id": source_integration_id,
                "source_channel_id": str(source_channel_id) if source_channel_id else None,
                "source_bot_id": source_bot_id,
                "display_label": member,
            }
            pin = await create_pin(
                db,
                source_kind="adhoc",
                tool_name="emit_html_widget",
                envelope=envelope,
                source_channel_id=source_channel_id,
                source_bot_id=source_bot_id,
                display_label=member,
                dashboard_key=dashboard_key,
            )
            created.append(pin)
    except Exception:
        # create_pin commits per pin; roll back by deleting what we added.
        for p in created:
            try:
                await db.delete(p)
                await db.commit()
            except Exception:
                logger.exception("suite pin rollback failed for pin %s", p.id)
        raise

    return created


async def get_pin(
    db: AsyncSession, pin_id: uuid.UUID,
) -> WidgetDashboardPin:
    pin = (await db.execute(
        select(WidgetDashboardPin).where(WidgetDashboardPin.id == pin_id)
    )).scalar_one_or_none()
    if pin is None:
        raise NotFoundError("Dashboard pin not found")
    if _refresh_pin_contract_metadata(pin):
        await db.commit()
        await db.refresh(pin)
    return pin


async def check_pin_db_content(pin: WidgetDashboardPin) -> dict | None:
    """Return DB info if the pin's bundle has a SQLite DB with content.

    Returns ``None`` when the pin is an inline widget (no source_path), the DB
    file doesn't exist, or the DB is empty.  Returns a dict with ``path``
    (str, absolute) and ``has_content`` (True) otherwise.  Used by the unpin
    flow to decide whether to surface a data-loss confirmation to the user.
    """
    try:
        from app.services.widget_db import has_content, resolve_db_path
        manifest = None
        try:
            from app.services.widget_py import resolve_bundle_dir
            from app.services.widget_manifest import parse_manifest
            bundle_dir = resolve_bundle_dir(pin)
            yaml_path = bundle_dir / "widget.yaml"
            if yaml_path.is_file():
                manifest = parse_manifest(yaml_path)
        except Exception:
            manifest = None
        db_path = resolve_db_path(pin, manifest)
        if has_content(db_path):
            return {"path": str(db_path), "has_content": True}
    except (ValueError, Exception):
        pass
    return None


async def delete_pin(
    db: AsyncSession,
    pin_id: uuid.UUID,
    *,
    delete_bundle_data: bool = False,
    delete_linked_projection: bool = True,
) -> dict:
    """Delete a dashboard pin.

    When ``delete_bundle_data=True``, also unlinks the bundle's ``data.sqlite``
    file (if one exists at the resolved path).

    Returns a dict with ``deleted=True`` and, when a non-empty DB was found
    after deletion, ``data_sqlite_orphan=True`` + ``orphan_path`` so the caller
    can surface a follow-up prompt or record what was cleaned up.
    """
    pin = await get_pin(db, pin_id)
    was_panel = bool(pin.is_main_panel)
    dashboard_key = pin.dashboard_key

    # Resolve DB path before deleting the pin (we need bot/channel info from pin).
    orphan_info: dict | None = None
    pinned_files_channel_id: uuid.UUID | None = None
    if delete_bundle_data:
        orphan_info = await check_pin_db_content(pin)
    if pin.widget_instance_id is not None:
        instance = await db.get(WidgetInstance, pin.widget_instance_id)
        if instance is not None and instance.widget_ref == "core/pinned_files_native":
            from app.services.pinned_panels import clear_pinned_files_instance

            await clear_pinned_files_instance(instance)
            try:
                pinned_files_channel_id = uuid.UUID(instance.scope_ref)
            except ValueError:
                pass

    # Cancel live event subscribers BEFORE the pin row drops — otherwise a
    # subscriber might race on a missing pin in the brief window before the
    # FK cascade fires. The call also drops widget_event_subscriptions rows.
    try:
        from app.services.widget_events import unregister_pin_events
        await unregister_pin_events(db, pin_id)
    except Exception:
        logger.exception("unregister_pin_events failed for pin %s", pin_id)

    if delete_linked_projection:
        await _delete_linked_channel_spatial_rows(db, pin)

    await db.delete(pin)
    await db.flush()
    if was_panel:
        # Removing the dashboard's only panel pin reverts it to normal grid
        # mode — otherwise the renderer would show an empty main area.
        await _set_dashboard_layout_mode(db, dashboard_key, None)
    await db.commit()
    if pinned_files_channel_id is not None:
        from app.services.pinned_panels import replace_channel_paths

        replace_channel_paths(pinned_files_channel_id, [])

    result: dict = {"deleted": True}
    if delete_bundle_data and orphan_info:
        import os
        db_path_str = orphan_info["path"]
        try:
            os.unlink(db_path_str)
            result["bundle_data_deleted"] = True
            result["orphan_path"] = db_path_str
        except FileNotFoundError:
            result["bundle_data_deleted"] = False
        except Exception as exc:
            result["bundle_data_deleted"] = False
            result["bundle_data_error"] = str(exc)

    return result


async def apply_dashboard_pin_config_patch(
    db: AsyncSession,
    pin_id: uuid.UUID,
    patch: dict,
    *,
    merge: bool = True,
) -> dict:
    """Shallow-merge (or replace) a pin's ``widget_config``.

    Mirrors ``app/routers/api_v1_channels.py::apply_widget_config_patch`` so
    the widget_config dispatch path can route to either surface by scope.
    Returns the serialized pin.
    """
    pin = await get_pin(db, pin_id)
    current = copy.deepcopy(pin.widget_config or {})
    pin.widget_config = {**current, **patch} if merge else dict(patch)
    flag_modified(pin, "widget_config")
    await db.commit()
    await db.refresh(pin)
    return serialize_pin(pin)


async def update_pin_envelope(
    db: AsyncSession,
    pin_id: uuid.UUID,
    envelope: dict,
) -> WidgetDashboardPin:
    pin = await get_pin(db, pin_id)
    pin.envelope = envelope
    pin.display_label = envelope.get("display_label") or pin.display_label
    flag_modified(pin, "envelope")
    reconcile_pin_metadata(pin)
    await db.commit()
    await db.refresh(pin)

    # Envelope change may have moved source_path to a new bundle — reconcile
    # the pin's cron subscriptions against whatever widget.yaml lives there
    # now (or clear them if the new bundle has none).
    try:
        from app.services.widget_cron import register_pin_crons
        await register_pin_crons(db, pin)
    except Exception:
        logger.exception("register_pin_crons failed for pin %s on envelope update", pin.id)

    # Same for @on_event subscriptions — cancel old live tasks and respawn
    # against the new manifest.
    try:
        from app.services.widget_events import register_pin_events
        await register_pin_events(db, pin)
    except Exception:
        logger.exception("register_pin_events failed for pin %s on envelope update", pin.id)

    return pin


async def rename_pin(
    db: AsyncSession,
    pin_id: uuid.UUID,
    display_label: str | None,
) -> dict[str, Any]:
    """Update just the pin's ``display_label`` (a table column, not JSONB).

    ``display_label`` is stored on the row so the dashboard header can show a
    user-chosen name without touching ``widget_config`` (which is widget-
    semantic). Pass ``None`` / empty string to clear it.
    """
    pin = await get_pin(db, pin_id)
    cleaned = (display_label or "").strip() or None
    pin.display_label = cleaned
    await db.commit()
    await db.refresh(pin)
    return serialize_pin(pin)


async def update_pin_scope(
    db: AsyncSession,
    pin_id: uuid.UUID,
    source_bot_id: str | None,
) -> dict[str, Any]:
    """Flip a pin's auth scope between "user-scoped" and "bot-scoped".

    ``source_bot_id = None`` — user scope. The iframe authenticates as the
    viewer; each viewer sees data through their own credentials. Suite DBs
    still resolve via dashboard_key so shared state works.

    ``source_bot_id = "<bot_id>"`` — bot scope. The iframe mints a JWT from
    the named bot so every viewer sees the same data through the bot's
    ceiling. Bot must exist.

    We write both the table column AND the envelope's ``source_bot_id``
    field: the renderer reads the envelope to drive the scope chip (``@bot``
    vs ``as you``) and the widget-token-mint path keys on the column. They
    must stay in lockstep.
    """
    pin = await get_pin(db, pin_id)

    if source_bot_id is not None:
        bot_row = (await db.execute(
            select(Bot).where(Bot.id == source_bot_id)
        )).scalar_one_or_none()
        if bot_row is None:
            raise NotFoundError(f"bot not found: {source_bot_id!r}")

    pin.source_bot_id = source_bot_id
    envelope = dict(pin.envelope or {})
    if source_bot_id is None:
        envelope.pop("source_bot_id", None)
    else:
        envelope["source_bot_id"] = source_bot_id
    pin.envelope = envelope
    flag_modified(pin, "envelope")
    reconcile_pin_metadata(pin)

    await db.commit()
    await db.refresh(pin)
    return serialize_pin(pin)


def _normalize_coords_for_zone(
    coords: dict[str, int],
    zone: str,
    *,
    preset_name: str = DEFAULT_PRESET,
) -> dict[str, int]:
    """Clamp ``coords`` to the invariants of ``zone``.

    Header → two-row top rail with preset-width columns.
    Rail / Dock → ``x=0, w=1`` (h/y pass through).
    Grid → pass through (preset-wide validation happens at drag-commit).
    """
    x = coords.get("x", 0)
    y = coords.get("y", 0)
    w = coords.get("w", 1)
    h = coords.get("h", 1)
    if zone == "header":
        cols = _header_cols_for_preset(preset_name)
        w = max(1, min(cols, w))
        h = max(1, min(2, h))
        x = max(0, x)
        y = min(1, max(0, y))
        max_x = max(0, cols - w)
        x = min(x, max_x)
        return {"x": x, "y": y, "w": w, "h": h}
    if zone in ("rail", "dock"):
        return {"x": 0, "y": max(0, y), "w": 1, "h": max(1, h)}
    return {"x": max(0, x), "y": max(0, y), "w": max(1, w), "h": max(1, h)}


def _validate_layout_item(
    item: Any,
) -> tuple[uuid.UUID, dict[str, int], str | None]:
    if not isinstance(item, dict):
        raise ValidationError("layout item must be an object")
    raw_id = item.get("id")
    if not raw_id:
        raise ValidationError("layout item missing 'id'")
    try:
        pin_id = uuid.UUID(str(raw_id))
    except ValueError as exc:
        raise ValidationError(f"Invalid pin id: {raw_id}") from exc
    coords: dict[str, int] = {}
    for key in _VALID_LAYOUT_KEYS:
        value = item.get(key)
        if not isinstance(value, int) or value < 0:
            raise ValidationError(
                f"layout item '{key}' must be a non-negative integer",
            )
        coords[key] = value
    # Zone is optional — same-canvas reorders can omit it. When present it
    # replaces the row's current zone so cross-canvas drops commit atomically
    # with coord updates.
    zone: str | None = None
    if "zone" in item and item["zone"] is not None:
        zone = str(item["zone"])
        if zone not in VALID_ZONES:
            raise ValidationError(
                f"layout item 'zone' must be one of {sorted(VALID_ZONES)}",
            )
    return pin_id, coords, zone


async def _set_dashboard_layout_mode(
    db: AsyncSession, dashboard_key: str, mode: str | None,
) -> None:
    """Read-modify-write ``WidgetDashboard.grid_config.layout_mode``.

    ``mode=None`` removes the key entirely (treated as default ``"grid"``).
    Lazy import of dashboards service to avoid the module-level cycle.
    """
    from app.db.models import WidgetDashboard
    row = (await db.execute(
        select(WidgetDashboard).where(WidgetDashboard.slug == dashboard_key)
    )).scalar_one_or_none()
    if row is None:
        raise NotFoundError(f"Dashboard not found: {dashboard_key}")
    cfg = copy.deepcopy(row.grid_config or {})
    if mode is None:
        cfg.pop("layout_mode", None)
    else:
        cfg["layout_mode"] = mode
    row.grid_config = cfg or None
    flag_modified(row, "grid_config")
    await db.flush()


async def promote_pin_to_panel(
    db: AsyncSession, pin_id: uuid.UUID,
) -> dict[str, Any]:
    """Make ``pin_id`` the panel pin for its dashboard.

    Atomic: clears ``is_main_panel`` on every other pin in the same dashboard
    first, then sets it on this pin, then flips ``grid_config.layout_mode`` to
    ``"panel"``. Returns the serialized promoted pin.
    """
    pin = await get_pin(db, pin_id)
    # Clear any existing panel pin in this dashboard (the partial unique
    # index would otherwise reject the SET below on Postgres).
    others = (await db.execute(
        select(WidgetDashboardPin)
        .where(
            WidgetDashboardPin.dashboard_key == pin.dashboard_key,
            WidgetDashboardPin.is_main_panel == True,  # noqa: E712 - SQL boolean
            WidgetDashboardPin.id != pin.id,
        )
    )).scalars().all()
    for other in others:
        other.is_main_panel = False
    # Flush the clears before setting the new one so the partial unique
    # index never sees two TRUE rows in the same statement window.
    if others:
        await db.flush()
    pin.is_main_panel = True
    await _set_dashboard_layout_mode(db, pin.dashboard_key, "panel")
    await db.commit()
    await db.refresh(pin)
    return serialize_pin(pin)


async def demote_pin_from_panel(
    db: AsyncSession, pin_id: uuid.UUID,
) -> dict[str, Any]:
    """Clear ``is_main_panel`` on ``pin_id``.

    If this leaves the dashboard with no panel pin, ``grid_config.layout_mode``
    is reverted to ``"grid"`` (so the dashboard renders as a normal RGL grid
    again instead of an empty panel area).
    """
    pin = await get_pin(db, pin_id)
    pin.is_main_panel = False
    await db.flush()

    remaining = (await db.execute(
        select(func.count())
        .select_from(WidgetDashboardPin)
        .where(
            WidgetDashboardPin.dashboard_key == pin.dashboard_key,
            WidgetDashboardPin.is_main_panel == True,  # noqa: E712
        )
    )).scalar() or 0
    if remaining == 0:
        await _set_dashboard_layout_mode(db, pin.dashboard_key, None)
    await db.commit()
    await db.refresh(pin)
    return serialize_pin(pin)


async def apply_layout_bulk(
    db: AsyncSession,
    items: list[dict[str, Any]],
    *,
    dashboard_key: str = DEFAULT_DASHBOARD_KEY,
) -> dict[str, Any]:
    """Persist ``{x, y, w, h}`` for a batch of pins in one transaction.

    All ids must belong to ``dashboard_key``; otherwise the whole call fails
    with 400 so we never commit a partial layout.
    """
    if not isinstance(items, list):
        raise ValidationError("items must be a list")
    parsed = [_validate_layout_item(it) for it in items]
    if not parsed:
        return {"ok": True, "updated": 0}

    pin_ids = [pid for pid, _, _ in parsed]
    rows = (
        await db.execute(
            select(WidgetDashboardPin).where(
                WidgetDashboardPin.id.in_(pin_ids),
                WidgetDashboardPin.dashboard_key == dashboard_key,
            )
        )
    ).scalars().all()
    dashboard = (
        await db.execute(
            select(WidgetDashboard.grid_config).where(WidgetDashboard.slug == dashboard_key)
        )
    ).first()
    preset_name = _resolve_dashboard_preset_name(dashboard[0] if dashboard else None)
    by_id = {row.id: row for row in rows}
    missing = [str(pid) for pid in pin_ids if pid not in by_id]
    if missing:
        raise ValidationError(f"Unknown pin ids: {missing}")

    for pin_id, coords, zone in parsed:
        row = by_id[pin_id]
        effective_zone = zone if zone is not None else (row.zone or "grid")
        row.grid_layout = _normalize_coords_for_zone(
            coords,
            effective_zone,
            preset_name=preset_name,
        )
        flag_modified(row, "grid_layout")
        if zone is not None:
            row.zone = zone
    await db.commit()
    return {"ok": True, "updated": len(parsed)}
