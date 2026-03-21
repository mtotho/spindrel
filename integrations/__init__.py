"""Integration auto-discovery.

Scans integrations/*/router.py for a `router` FastAPI APIRouter attribute.
Returns [(integration_id, router), ...] for each discovered integration.
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path

from fastapi import APIRouter

logger = logging.getLogger(__name__)

_INTEGRATIONS_DIR = Path(__file__).parent


def discover_integrations() -> list[tuple[str, APIRouter]]:
    """Discover and load all integrations. Returns [(integration_id, router)]."""
    results: list[tuple[str, APIRouter]] = []

    for candidate in sorted(_INTEGRATIONS_DIR.iterdir()):
        if not candidate.is_dir():
            continue
        if candidate.name.startswith("_"):
            continue
        router_file = candidate / "router.py"
        if not router_file.exists():
            continue

        integration_id = candidate.name
        module_path = f"integrations.{integration_id}.router"
        try:
            module = importlib.import_module(module_path)
        except Exception:
            logger.exception("Failed to load integration %r — skipping", integration_id)
            continue

        router = getattr(module, "router", None)
        if router is None or not isinstance(router, APIRouter):
            logger.warning("Integration %r has no APIRouter named 'router' — skipping", integration_id)
            continue

        results.append((integration_id, router))

    return results
