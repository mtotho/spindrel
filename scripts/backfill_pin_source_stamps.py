#!/usr/bin/env python3
"""Phase 2 backfill: populate ``widget_dashboard_pins.source_stamp``.

Phase 1 of the pin-contract deepening (see
``app/services/pin_contract/__init__.py``) added a ``source_stamp`` column
populated only on new writes. Phase 3 will flip ``list_pins`` to serve
snapshots directly from columns when the stamp matches; that flip is only
safe once every existing row is stamped.

This script does two things:

* default mode — walks ``widget_dashboard_pins`` in batches and writes
  ``source_stamp`` on every row where it is currently NULL. Idempotent;
  re-runs touch zero rows once steady-state is reached.
* ``--verify`` mode — for every row, computes the new-path
  ``compute_pin_metadata`` view and the legacy ``build_pin_contract_metadata``
  view side-by-side, diffs ``widget_origin`` / ``provenance_confidence`` /
  the three snapshot fields, and reports mismatches. No writes. This is the
  Phase 3 readiness gate: zero mismatches in prod = safe to flip.

Usage:

    python scripts/backfill_pin_source_stamps.py
    python scripts/backfill_pin_source_stamps.py --verify
    python scripts/backfill_pin_source_stamps.py --dashboard-key default
    python scripts/backfill_pin_source_stamps.py --batch-size 100
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# Repo root on path so ``app`` and ``integrations`` import cleanly when
# running this file directly (matches scripts/list_integration_processes.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.db.engine import async_session  # noqa: E402
from app.db.models import WidgetDashboardPin  # noqa: E402
from app.services.pin_contract import (  # noqa: E402
    ContractSnapshot,
    compute_pin_metadata,
    compute_pin_source_stamp,
)
from app.services.widget_contracts import (  # noqa: E402
    build_pin_contract_metadata,
)

logger = logging.getLogger("backfill_pin_source_stamps")


# ── Backfill ────────────────────────────────────────────────────────


async def backfill(
    *,
    batch_size: int,
    dashboard_key: str | None,
    dry_run: bool,
) -> dict[str, Any]:
    stats: Counter[str] = Counter()
    last_id = None
    while True:
        async with async_session() as db:
            stmt = select(WidgetDashboardPin).where(
                WidgetDashboardPin.source_stamp.is_(None)
            )
            if dashboard_key is not None:
                stmt = stmt.where(WidgetDashboardPin.dashboard_key == dashboard_key)
            if last_id is not None:
                stmt = stmt.where(WidgetDashboardPin.id > last_id)
            stmt = stmt.order_by(WidgetDashboardPin.id.asc()).limit(batch_size)
            rows = (await db.execute(stmt)).scalars().all()
            if not rows:
                break
            for row in rows:
                stamp = compute_pin_source_stamp(
                    tool_name=row.tool_name,
                    envelope=row.envelope or {},
                    source_bot_id=row.source_bot_id,
                    caller_origin=row.widget_origin,
                )
                origin_kind = _origin_kind(row.widget_origin)
                stats["scanned"] += 1
                if stamp is None:
                    stats[f"stamp_none.{origin_kind}"] += 1
                else:
                    stats[f"stamped.{origin_kind}"] += 1
                if not dry_run and stamp is not None:
                    row.source_stamp = stamp
                last_id = row.id
            if not dry_run:
                await db.commit()
        if len(rows) < batch_size:
            break
    return dict(stats)


# ── Verify ──────────────────────────────────────────────────────────


_VERIFY_FIELDS = (
    "widget_origin",
    "provenance_confidence",
    "widget_contract",
    "config_schema",
    "widget_presentation",
)


async def verify(
    *,
    batch_size: int,
    dashboard_key: str | None,
    limit: int | None,
) -> dict[str, Any]:
    stats: Counter[str] = Counter()
    mismatches: list[dict[str, Any]] = []
    last_id = None
    seen = 0
    while True:
        async with async_session() as db:
            stmt = select(WidgetDashboardPin)
            if dashboard_key is not None:
                stmt = stmt.where(WidgetDashboardPin.dashboard_key == dashboard_key)
            if last_id is not None:
                stmt = stmt.where(WidgetDashboardPin.id > last_id)
            stmt = stmt.order_by(WidgetDashboardPin.id.asc()).limit(batch_size)
            rows = (await db.execute(stmt)).scalars().all()
            if not rows:
                break
            for row in rows:
                seen += 1
                stats["scanned"] += 1
                drift = _diff_views(row)
                if drift:
                    stats["mismatch"] += 1
                    mismatches.append({"pin_id": str(row.id), "fields": drift})
                else:
                    stats["match"] += 1
                last_id = row.id
                if limit is not None and seen >= limit:
                    return {"stats": dict(stats), "mismatches": mismatches}
        if len(rows) < batch_size:
            break
    return {"stats": dict(stats), "mismatches": mismatches}


def _diff_views(pin: WidgetDashboardPin) -> list[str]:
    """Return field names where new-path view ≠ legacy view."""
    new_view, _stamp = compute_pin_metadata(
        tool_name=pin.tool_name,
        envelope=pin.envelope or {},
        source_bot_id=pin.source_bot_id,
        caller_origin=pin.widget_origin if pin.widget_origin else None,
        snapshot=ContractSnapshot(
            widget_contract=pin.widget_contract_snapshot,
            config_schema=pin.config_schema_snapshot,
            widget_presentation=pin.widget_presentation_snapshot,
        ),
    )
    legacy = build_pin_contract_metadata(
        tool_name=pin.tool_name,
        envelope=pin.envelope or {},
        source_bot_id=pin.source_bot_id,
        widget_origin=pin.widget_origin,
        provenance_confidence=pin.provenance_confidence,
        widget_contract_snapshot=pin.widget_contract_snapshot,
        config_schema_snapshot=pin.config_schema_snapshot,
        widget_presentation_snapshot=pin.widget_presentation_snapshot,
    )
    pairs = {
        "widget_origin": (new_view.widget_origin or None, legacy.get("widget_origin")),
        "provenance_confidence": (
            new_view.provenance_confidence,
            legacy.get("provenance_confidence"),
        ),
        "widget_contract": (
            new_view.widget_contract,
            legacy.get("widget_contract")
            if legacy.get("widget_contract") is not None
            else legacy.get("widget_contract_snapshot"),
        ),
        "config_schema": (
            new_view.config_schema,
            legacy.get("config_schema")
            if legacy.get("config_schema") is not None
            else legacy.get("config_schema_snapshot"),
        ),
        "widget_presentation": (
            new_view.widget_presentation,
            legacy.get("widget_presentation")
            if legacy.get("widget_presentation") is not None
            else legacy.get("widget_presentation_snapshot"),
        ),
    }
    return [name for name, (a, b) in pairs.items() if a != b]


# ── Helpers ─────────────────────────────────────────────────────────


def _origin_kind(origin: Any) -> str:
    if not isinstance(origin, dict) or not origin:
        return "unknown"
    definition = origin.get("definition_kind", "?")
    instantiation = origin.get("instantiation_kind", "?")
    return f"{definition}+{instantiation}"


# ── CLI ─────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verify", action="store_true",
                        help="dry-run parity check (no writes)")
    parser.add_argument("--dry-run", action="store_true",
                        help="walk and report without writing stamps")
    parser.add_argument("--batch-size", type=int, default=500,
                        help="rows per DB batch (default: 500)")
    parser.add_argument("--dashboard-key", type=str, default=None,
                        help="filter to a single dashboard_key")
    parser.add_argument("--limit", type=int, default=None,
                        help="cap rows scanned (verify mode only)")
    parser.add_argument("--log-level", default="INFO",
                        help="python logging level (default: INFO)")
    return parser.parse_args(argv)


async def _main_async(args: argparse.Namespace) -> int:
    if args.verify:
        result = await verify(
            batch_size=args.batch_size,
            dashboard_key=args.dashboard_key,
            limit=args.limit,
        )
        stats = result["stats"]
        mismatches = result["mismatches"]
        logger.info("verify stats: %s", stats)
        if mismatches:
            logger.warning("verify found %d mismatches", len(mismatches))
            for m in mismatches[:25]:
                logger.warning("  pin=%s fields=%s", m["pin_id"], m["fields"])
            if len(mismatches) > 25:
                logger.warning("  … %d more", len(mismatches) - 25)
            return 1
        logger.info("verify clean — Phase 3 ready")
        return 0

    stats = await backfill(
        batch_size=args.batch_size,
        dashboard_key=args.dashboard_key,
        dry_run=args.dry_run,
    )
    logger.info("backfill stats: %s", stats)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
