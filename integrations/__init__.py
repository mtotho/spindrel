"""Integration auto-discovery.

Scans integrations/*/router.py for a `router` FastAPI APIRouter attribute.
Scans integrations/*/dispatcher.py and auto-imports to trigger register() calls.
Returns [(integration_id, router), ...] for each discovered integration with a router.

Each integration can also provide:
  - dispatcher.py  — calls app.agent.dispatchers.register() at import time
  - process.py     — declares CMD/REQUIRED_ENV for dev-server auto-start
"""
from __future__ import annotations

import importlib
import logging
import os
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

        integration_id = candidate.name

        # Auto-import dispatcher.py to trigger register() (independent of router.py)
        dispatcher_file = candidate / "dispatcher.py"
        if dispatcher_file.exists():
            try:
                importlib.import_module(f"integrations.{integration_id}.dispatcher")
                logger.debug("Loaded dispatcher for integration: %s", integration_id)
            except Exception:
                logger.exception("Failed to load dispatcher for integration %r", integration_id)

        # Register router if present
        router_file = candidate / "router.py"
        if not router_file.exists():
            continue

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


def discover_processes() -> list[dict]:
    """Discover integration background processes.

    Returns list of dicts: {id, cmd, required_env, description}
    Only includes processes whose REQUIRED_ENV vars are all set.
    """
    results: list[dict] = []

    for candidate in sorted(_INTEGRATIONS_DIR.iterdir()):
        if not candidate.is_dir() or candidate.name.startswith("_"):
            continue

        process_file = candidate / "process.py"
        if not process_file.exists():
            continue

        integration_id = candidate.name
        try:
            module = importlib.import_module(f"integrations.{integration_id}.process")
            cmd = getattr(module, "CMD", None)
            required_env = getattr(module, "REQUIRED_ENV", [])
            description = getattr(module, "DESCRIPTION", integration_id)
            if not cmd:
                continue
            if all(os.environ.get(v) for v in required_env):
                results.append({
                    "id": integration_id,
                    "cmd": cmd,
                    "required_env": required_env,
                    "description": description,
                })
            else:
                missing = [v for v in required_env if not os.environ.get(v)]
                logger.debug(
                    "Skipping process for integration %r: missing env vars %s",
                    integration_id, missing,
                )
        except Exception:
            logger.exception("Failed to load process config for integration %r", integration_id)

    return results
