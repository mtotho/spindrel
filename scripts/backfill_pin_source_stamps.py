#!/usr/bin/env python3
"""Pin contract drift scanner and repair helper.

Phase 4 keeps this script name for operator muscle memory, but the job is no
longer a legacy stamp-only backfill or new-vs-old parity check. It now uses
``app.services.pin_contract`` as the single source of truth:

* default / ``--verify`` mode scans rows and reports drift without writes
* ``--repair`` mode applies the canonical pin contract view and source stamp

Usage:

    python scripts/backfill_pin_source_stamps.py
    python scripts/backfill_pin_source_stamps.py --verify
    python scripts/backfill_pin_source_stamps.py --repair
    python scripts/backfill_pin_source_stamps.py --dashboard-key default
    python scripts/backfill_pin_source_stamps.py --batch-size 100 --limit 500
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Repo root on path so ``app`` and ``integrations`` import cleanly when
# running this file directly (matches scripts/list_integration_processes.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.engine import async_session  # noqa: E402
from app.services.pin_contract import scan_pin_contract_drift  # noqa: E402

logger = logging.getLogger("pin_contract_drift")


async def scan(
    *,
    batch_size: int,
    dashboard_key: str | None,
    limit: int | None,
    repair: bool,
) -> dict[str, Any]:
    async with async_session() as db:
        return await scan_pin_contract_drift(
            db,
            batch_size=batch_size,
            dashboard_key=dashboard_key,
            limit=limit,
            repair=repair,
        )


async def verify(
    *,
    batch_size: int,
    dashboard_key: str | None,
    limit: int | None,
) -> dict[str, Any]:
    return await scan(
        batch_size=batch_size,
        dashboard_key=dashboard_key,
        limit=limit,
        repair=False,
    )


async def backfill(
    *,
    batch_size: int,
    dashboard_key: str | None,
    dry_run: bool,
) -> dict[str, Any]:
    """Compatibility wrapper for older tests/operators.

    ``dry_run=False`` now means full contract repair, not stamp-only backfill.
    """
    result = await scan(
        batch_size=batch_size,
        dashboard_key=dashboard_key,
        limit=None,
        repair=not dry_run,
    )
    return result["stats"]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verify", action="store_true",
                        help="scan and report drift without writing (default)")
    parser.add_argument("--repair", action="store_true",
                        help="repair rows whose cached contract columns drifted")
    parser.add_argument("--dry-run", action="store_true",
                        help="alias for scan-only mode")
    parser.add_argument("--batch-size", type=int, default=500,
                        help="rows per DB batch (default: 500)")
    parser.add_argument("--dashboard-key", type=str, default=None,
                        help="filter to a single dashboard_key")
    parser.add_argument("--limit", type=int, default=None,
                        help="cap rows scanned")
    parser.add_argument("--log-level", default="INFO",
                        help="python logging level (default: INFO)")
    return parser.parse_args(argv)


async def _main_async(args: argparse.Namespace) -> int:
    repair = bool(args.repair and not args.dry_run and not args.verify)
    result = await scan(
        batch_size=args.batch_size,
        dashboard_key=args.dashboard_key,
        limit=args.limit,
        repair=repair,
    )
    logger.info("pin contract drift stats: %s", result["stats"])
    if result["drifts"]:
        logger.info("pin contract drift samples:\n%s", json.dumps(result["drifts"], indent=2))
    return 1 if result["stats"].get("failed") else 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(levelname)s %(name)s: %(message)s",
    )
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
