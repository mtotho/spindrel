"""Pin contract service — the four public functions.

``render_pin_metadata`` is the hot path: snapshot-only, zero IO.
``compute_pin_metadata`` is pure: walk the resolver chain to build the view
without touching the DB. ``apply_to_pin`` writes the columns.
``reconcile_pin_metadata`` glues compute + apply for callers that already
have a pin row.
"""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from sqlalchemy.orm.attributes import flag_modified

from app.db.models import WidgetDashboardPin
from app.services.pin_contract.deps import ContractDeps, get_deps
from app.services.pin_contract.resolvers import LiveFields, all_resolvers

logger = logging.getLogger(__name__)


# ── Public types ────────────────────────────────────────────────────


@dataclass(frozen=True)
class PinIdentity:
    """The minimal envelope-shaped input a resolver needs to claim + materialize."""
    tool_name: str
    envelope: Mapping[str, Any]
    source_bot_id: str | None


@dataclass(frozen=True)
class ContractSnapshot:
    """The three snapshot columns, bundled for fallback use."""
    widget_contract: dict | None = None
    config_schema: dict | None = None
    widget_presentation: dict | None = None


@dataclass(frozen=True)
class PinMetadataView:
    """Public read view assembled from snapshot columns + origin/confidence."""
    widget_origin: dict
    provenance_confidence: Literal["authoritative", "inferred"]
    widget_contract: dict | None
    config_schema: dict | None
    widget_presentation: dict | None


# ── Hot path ────────────────────────────────────────────────────────


def render_pin_metadata(pin: WidgetDashboardPin) -> PinMetadataView:
    """Snapshot-only read. Zero registry / filesystem access.

    Safe only when the pin has been backfilled. Callers that may see
    un-backfilled rows should check the columns first or use
    ``reconcile_pin_metadata`` for the slow path.
    """
    return PinMetadataView(
        widget_origin=copy.deepcopy(pin.widget_origin) if pin.widget_origin else {},
        provenance_confidence=_normalize_confidence(pin.provenance_confidence),
        widget_contract=copy.deepcopy(pin.widget_contract_snapshot)
        if pin.widget_contract_snapshot is not None
        else None,
        config_schema=copy.deepcopy(pin.config_schema_snapshot)
        if pin.config_schema_snapshot is not None
        else None,
        widget_presentation=copy.deepcopy(pin.widget_presentation_snapshot)
        if pin.widget_presentation_snapshot is not None
        else None,
    )


# ── Cold path ──────────────────────────────────────────────────────


def compute_pin_metadata(
    *,
    tool_name: str,
    envelope: dict,
    source_bot_id: str | None,
    caller_origin: dict | None = None,
    snapshot: ContractSnapshot | None = None,
    deps: ContractDeps | None = None,
) -> tuple[PinMetadataView, str | None]:
    """Pure compute. Returns (view, source_stamp). No DB / row mutation.

    Used by ``create_pin`` BEFORE constructing the pin row so the resolved
    ``widget_presentation.layout_hints`` can drive initial-zone seeding
    (``dashboard_pins.py:455-462``). Also used internally by
    ``reconcile_pin_metadata``.

    ``caller_origin`` non-None ⇒ ``provenance_confidence == "authoritative"``.
    """
    deps = deps or get_deps()
    ident = PinIdentity(
        tool_name=tool_name,
        envelope=envelope,
        source_bot_id=source_bot_id,
    )

    origin: dict
    confidence: Literal["authoritative", "inferred"]
    if isinstance(caller_origin, dict) and caller_origin:
        origin = copy.deepcopy(caller_origin)
        confidence = "authoritative"
        # We still need a resolver to materialize live fields when caller
        # supplied origin. Find the matching resolver by (definition_kind,
        # instantiation_kind); fall back to first resolver that *claims*
        # the envelope if no exact match.
        resolver = _resolver_for_origin(origin) or _claim_resolver(ident, deps)
    else:
        resolver = _claim_resolver(ident, deps)
        if resolver is None:
            origin = {}
            confidence = "inferred"
        else:
            claimed = resolver.claim(ident, deps)
            origin = claimed if claimed is not None else {}
            confidence = "inferred"

    if resolver is None or not origin:
        # No resolver claimed — pin is degenerate. Return empty view +
        # snapshot fallback.
        view = _fold_with_snapshot(
            origin=origin,
            confidence=confidence,
            live=LiveFields.empty(),
            snapshot=snapshot,
        )
        return view, None

    live = resolver.materialize(origin, ident, deps)
    view = _fold_with_snapshot(
        origin=origin,
        confidence=confidence,
        live=live,
        snapshot=snapshot,
    )
    stamp = resolver.stamp(origin, ident, deps)
    return view, stamp


def apply_to_pin(
    pin: WidgetDashboardPin,
    view: PinMetadataView,
    stamp: str | None,
) -> bool:
    """Write the view + stamp + snapshots back onto a pin row.

    Returns True iff anything changed. Caller commits.
    """
    changed = False
    new_origin = view.widget_origin or None
    if pin.widget_origin != new_origin:
        pin.widget_origin = new_origin
        flag_modified(pin, "widget_origin")
        changed = True
    if pin.provenance_confidence != view.provenance_confidence:
        pin.provenance_confidence = view.provenance_confidence
        changed = True
    if pin.widget_contract_snapshot != view.widget_contract:
        pin.widget_contract_snapshot = (
            copy.deepcopy(view.widget_contract) if view.widget_contract is not None else None
        )
        flag_modified(pin, "widget_contract_snapshot")
        changed = True
    if pin.config_schema_snapshot != view.config_schema:
        pin.config_schema_snapshot = (
            copy.deepcopy(view.config_schema) if view.config_schema is not None else None
        )
        flag_modified(pin, "config_schema_snapshot")
        changed = True
    if pin.widget_presentation_snapshot != view.widget_presentation:
        pin.widget_presentation_snapshot = (
            copy.deepcopy(view.widget_presentation)
            if view.widget_presentation is not None
            else None
        )
        flag_modified(pin, "widget_presentation_snapshot")
        changed = True
    if pin.source_stamp != stamp:
        pin.source_stamp = stamp
        changed = True
    return changed


def compute_pin_source_stamp(
    *,
    tool_name: str,
    envelope: dict,
    source_bot_id: str | None,
    caller_origin: dict | None = None,
    deps: ContractDeps | None = None,
) -> str | None:
    """Compute just the source_stamp without touching the contract path.

    Used during Phase 1 of the rollout where ``build_pin_contract_metadata``
    is still the contract source of truth: write paths populate
    ``source_stamp`` via this helper while the legacy snapshots are written
    through the existing flow. Phase 3 will collapse both paths.
    """
    deps = deps or get_deps()
    ident = PinIdentity(
        tool_name=tool_name,
        envelope=envelope,
        source_bot_id=source_bot_id,
    )
    if isinstance(caller_origin, dict) and caller_origin:
        resolver = _resolver_for_origin(caller_origin) or _claim_resolver(ident, deps)
        origin: dict = caller_origin
    else:
        resolver = _claim_resolver(ident, deps)
        if resolver is None:
            return None
        claimed = resolver.claim(ident, deps)
        if claimed is None:
            return None
        origin = claimed
    if resolver is None:
        return None
    return resolver.stamp(origin, ident, deps)


def reconcile_pin_metadata(
    pin: WidgetDashboardPin,
    *,
    caller_origin: dict | None = None,
    deps: ContractDeps | None = None,
) -> bool:
    """compute → apply against an existing pin row. Returns dirty bool.

    Used by ``update_pin*`` paths, the native self-heal hook in
    ``_sync_native_pin_envelopes``, and the background reconciler.
    """
    snapshot = ContractSnapshot(
        widget_contract=pin.widget_contract_snapshot,
        config_schema=pin.config_schema_snapshot,
        widget_presentation=pin.widget_presentation_snapshot,
    )
    effective_caller_origin = caller_origin
    if effective_caller_origin is None and isinstance(pin.widget_origin, dict) and pin.widget_origin:
        # Existing pins have a stored origin. Treat it as authoritative-when-
        # caller-supplied wasn't given so we don't downgrade authoritative
        # rows to inferred on every reconcile.
        if pin.provenance_confidence == "authoritative":
            effective_caller_origin = pin.widget_origin
    view, stamp = compute_pin_metadata(
        tool_name=pin.tool_name,
        envelope=pin.envelope or {},
        source_bot_id=pin.source_bot_id,
        caller_origin=effective_caller_origin,
        snapshot=snapshot,
        deps=deps,
    )
    return apply_to_pin(pin, view, stamp)


# ── Helpers ─────────────────────────────────────────────────────────


def _normalize_confidence(value: object) -> Literal["authoritative", "inferred"]:
    if isinstance(value, str) and value.strip() == "authoritative":
        return "authoritative"
    return "inferred"


def _claim_resolver(ident: PinIdentity, deps: ContractDeps):
    for resolver in all_resolvers():
        if resolver.claim(ident, deps) is not None:
            return resolver
    return None


def _resolver_for_origin(origin: dict):
    definition_kind = origin.get("definition_kind")
    instantiation_kind = origin.get("instantiation_kind")
    if not isinstance(definition_kind, str) or not isinstance(instantiation_kind, str):
        return None
    for resolver in all_resolvers():
        if (
            resolver.definition_kind == definition_kind
            and instantiation_kind in resolver.instantiation_kinds
        ):
            return resolver
    return None


def _fold_with_snapshot(
    *,
    origin: dict,
    confidence: Literal["authoritative", "inferred"],
    live: LiveFields,
    snapshot: ContractSnapshot | None,
) -> PinMetadataView:
    snapshot = snapshot or ContractSnapshot()
    widget_contract = (
        live.widget_contract
        if live.widget_contract is not None
        else copy.deepcopy(snapshot.widget_contract)
        if snapshot.widget_contract is not None
        else None
    )
    config_schema = (
        live.config_schema
        if live.config_schema is not None
        else copy.deepcopy(snapshot.config_schema)
        if snapshot.config_schema is not None
        else None
    )
    widget_presentation = (
        live.widget_presentation
        if live.widget_presentation is not None
        else copy.deepcopy(snapshot.widget_presentation)
        if snapshot.widget_presentation is not None
        else None
    )
    return PinMetadataView(
        widget_origin=copy.deepcopy(origin) if origin else {},
        provenance_confidence=confidence,
        widget_contract=widget_contract,
        config_schema=config_schema,
        widget_presentation=widget_presentation,
    )
