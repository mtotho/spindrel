"""Pin contract drift detection and repair.

This is the cold-path maintenance side of the pin contract Module. It
compares the row's cached pin contract columns with the live resolver-chain
view, and can repair stale rows by applying the same view that write paths
use. The dashboard hot path remains ``render_pin_metadata`` only.
"""
from __future__ import annotations

import asyncio
import logging
from collections import Counter
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WidgetDashboardPin
from app.services.pin_contract.deps import ContractDeps
from app.services.pin_contract.service import (
    ContractSnapshot,
    PinMetadataView,
    apply_to_pin,
    compute_pin_metadata,
)

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 500
DEFAULT_DRIFT_SCAN_INTERVAL_SECONDS = 60 * 60
DEFAULT_DRIFT_SCAN_INITIAL_DELAY_SECONDS = 5 * 60
MAX_DRIFT_SAMPLES = 50


@dataclass(frozen=True)
class PinContractDrift:
    pin_id: str
    fields: tuple[str, ...]
    expected_source_stamp: str | None
    current_source_stamp: str | None

    @property
    def has_drift(self) -> bool:
        return bool(self.fields)


@dataclass(frozen=True)
class PinContractExpected:
    view: PinMetadataView
    source_stamp: str | None


def compute_expected_pin_contract(
    pin: WidgetDashboardPin,
    *,
    deps: ContractDeps | None = None,
) -> PinContractExpected:
    """Return the canonical contract view for a pin row without mutating it."""
    snapshot = ContractSnapshot(
        widget_contract=pin.widget_contract_snapshot,
        config_schema=pin.config_schema_snapshot,
        widget_presentation=pin.widget_presentation_snapshot,
    )
    caller_origin = None
    if (
        pin.provenance_confidence == "authoritative"
        and isinstance(pin.widget_origin, dict)
        and pin.widget_origin
    ):
        caller_origin = pin.widget_origin
    view, source_stamp = compute_pin_metadata(
        tool_name=pin.tool_name,
        envelope=pin.envelope or {},
        source_bot_id=pin.source_bot_id,
        caller_origin=caller_origin,
        snapshot=snapshot,
        deps=deps,
    )
    return PinContractExpected(view=view, source_stamp=source_stamp)


def detect_pin_contract_drift(
    pin: WidgetDashboardPin,
    *,
    expected: PinContractExpected | None = None,
    deps: ContractDeps | None = None,
) -> PinContractDrift:
    """Compare cached row columns to the canonical pin contract view."""
    expected = expected or compute_expected_pin_contract(pin, deps=deps)
    view = expected.view
    pairs = {
        "widget_origin": (pin.widget_origin, view.widget_origin or None),
        "provenance_confidence": (
            pin.provenance_confidence,
            view.provenance_confidence,
        ),
        "widget_contract_snapshot": (
            pin.widget_contract_snapshot,
            view.widget_contract,
        ),
        "config_schema_snapshot": (
            pin.config_schema_snapshot,
            view.config_schema,
        ),
        "widget_presentation_snapshot": (
            pin.widget_presentation_snapshot,
            view.widget_presentation,
        ),
        "source_stamp": (pin.source_stamp, expected.source_stamp),
    }
    fields = tuple(name for name, (current, desired) in pairs.items() if current != desired)
    return PinContractDrift(
        pin_id=str(pin.id),
        fields=fields,
        expected_source_stamp=expected.source_stamp,
        current_source_stamp=pin.source_stamp,
    )


async def scan_pin_contract_drift(
    db: AsyncSession,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dashboard_key: str | None = None,
    limit: int | None = None,
    repair: bool = False,
    deps: ContractDeps | None = None,
) -> dict[str, Any]:
    """Scan widget dashboard pins for contract drift.

    Returns aggregate stats plus a bounded list of drift samples. In repair
    mode, stale rows are updated through ``apply_to_pin`` and committed per
    batch.
    """
    stats: Counter[str] = Counter()
    drifts: list[dict[str, Any]] = []
    last_id = None
    seen = 0

    while True:
        stmt = select(WidgetDashboardPin)
        if dashboard_key is not None:
            stmt = stmt.where(WidgetDashboardPin.dashboard_key == dashboard_key)
        if last_id is not None:
            stmt = stmt.where(WidgetDashboardPin.id > last_id)
        stmt = stmt.order_by(WidgetDashboardPin.id.asc()).limit(batch_size)
        rows = (await db.execute(stmt)).scalars().all()
        if not rows:
            break

        dirty = False
        for row in rows:
            stats["scanned"] += 1
            seen += 1
            last_id = row.id
            try:
                expected = compute_expected_pin_contract(row, deps=deps)
                drift = detect_pin_contract_drift(row, expected=expected)
            except Exception:
                stats["failed"] += 1
                logger.exception("pin_contract drift scan failed for pin=%s", row.id)
                if limit is not None and seen >= limit:
                    break
                continue

            if drift.has_drift:
                stats["drifted"] += 1
                for field in drift.fields:
                    stats[f"drift.{field}"] += 1
                if len(drifts) < MAX_DRIFT_SAMPLES:
                    drifts.append(
                        {
                            "pin_id": drift.pin_id,
                            "fields": list(drift.fields),
                            "current_source_stamp": drift.current_source_stamp,
                            "expected_source_stamp": drift.expected_source_stamp,
                        }
                    )
                if repair and apply_to_pin(row, expected.view, expected.source_stamp):
                    stats["repaired"] += 1
                    dirty = True
            else:
                stats["clean"] += 1

            if limit is not None and seen >= limit:
                break

        if repair and dirty:
            await db.commit()
        if limit is not None and seen >= limit:
            break
        if len(rows) < batch_size:
            break

    return {"stats": dict(stats), "drifts": drifts}


async def pin_contract_drift_worker(
    *,
    initial_delay_seconds: int = DEFAULT_DRIFT_SCAN_INITIAL_DELAY_SECONDS,
    interval_seconds: int = DEFAULT_DRIFT_SCAN_INTERVAL_SECONDS,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> None:
    """Periodic best-effort repair loop for stale pin contract snapshots."""
    from app.db.engine import async_session

    await asyncio.sleep(initial_delay_seconds)
    while True:
        try:
            async with async_session() as db:
                result = await scan_pin_contract_drift(
                    db,
                    batch_size=batch_size,
                    repair=True,
                )
            stats = result.get("stats", {})
            if stats.get("drifted") or stats.get("failed"):
                logger.info("pin_contract drift scan complete: %s", stats)
        except Exception:
            logger.warning("pin_contract drift worker failed", exc_info=True)
        await asyncio.sleep(interval_seconds)
