"""Agent-harness runtimes.

A "harness bot" delegates its turn to an external agent runtime (Claude Code,
Codex, etc.) instead of running our RAG loop. The protocol + emitter live
here, but the **driver implementations live inside their respective
integrations** (``integrations/<name>/harness.py``) so each driver's deps,
CLI install, and lifecycle are owned by the integration — not the base image,
not the global pyproject.

The seam in ``app/services/turn_worker.py`` calls ``get_runtime(name)`` to
look up a registered driver. Integrations populate the registry by importing
their harness module on load via ``discover_and_load_harnesses()``, which is
called once on app startup (similar to ``discover_and_load_tools()``).

Disabling an integration → its harness module isn't imported → the runtime
isn't in the registry → the bot-editor dropdown doesn't show it →
``/admin/harnesses`` lists nothing for that runtime.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .base import (
    AuthStatus,
    ChannelEventEmitter,
    HarnessRuntime,
    TurnResult,
)

logger = logging.getLogger(__name__)


HARNESS_REGISTRY: dict[str, HarnessRuntime] = {}


def register_runtime(name: str, runtime: HarnessRuntime) -> None:
    """Register a harness runtime. Called by integration ``harness.py`` modules
    on load. Idempotent — re-registering the same name overwrites the prior
    entry (matters for integration reload cycles).
    """
    HARNESS_REGISTRY[name] = runtime
    logger.info("Registered harness runtime: %s", name)


def unregister_runtime(name: str) -> None:
    """Remove a runtime from the registry (e.g. when an integration is
    disabled at runtime)."""
    HARNESS_REGISTRY.pop(name, None)


def get_runtime(name: str) -> HarnessRuntime:
    """Return the registered runtime for ``name``.

    Raises ``KeyError`` if the runtime is unknown — callers (turn_worker)
    should validate ``bot.harness_runtime`` against the registry keys before
    dispatch and surface a friendly error if missing (integration disabled).
    """
    return HARNESS_REGISTRY[name]


def runtime_names() -> list[str]:
    return list(HARNESS_REGISTRY.keys())


def discover_and_load_harnesses() -> None:
    """Import ``integrations/*/harness.py`` for active integrations only.

    Each harness module self-registers via ``register_runtime`` as a side
    effect of import. Called once at app startup from ``app/main.py`` after
    ``discover_and_load_tools``. Mirrors the tool-loader pattern in
    ``app/tools/loader.py:_scan_integration_tools``.
    """
    from app.services.integration_settings import is_active

    root = Path(__file__).parent.parent.parent.parent  # repo root
    integrations_dir = root / "integrations"
    if not integrations_dir.is_dir():
        return

    for harness_file in sorted(integrations_dir.glob("*/harness.py")):
        integration_id = harness_file.parent.name
        try:
            if not is_active(integration_id):
                logger.info(
                    "Skipping harness for inactive integration: %s", integration_id,
                )
                continue
        except Exception:
            # If is_active errors out (e.g. unconfigured), skip silently —
            # integration manifest validation runs separately.
            continue
        try:
            _import_harness_module(harness_file, integration_id)
        except ImportError as exc:
            # Most likely cause: integration's requirements.txt hasn't been
            # installed yet (e.g. claude-agent-sdk missing). Log and move on
            # — admin can install deps via /admin/integrations and reload.
            logger.warning(
                "Skipping harness for %s — import failed (deps not installed?): %s",
                integration_id, exc,
            )
        except Exception:
            logger.exception(
                "Failed to load harness for integration %s", integration_id,
            )


def _import_harness_module(harness_file: Path, integration_id: str) -> None:
    """Import ``integrations/<id>/harness.py`` so its ``register_runtime``
    side effect fires."""
    import importlib.util

    module_name = f"integrations.{integration_id}.harness"
    spec = importlib.util.spec_from_file_location(module_name, harness_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot build import spec for {harness_file}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


__all__ = [
    "AuthStatus",
    "ChannelEventEmitter",
    "HarnessRuntime",
    "TurnResult",
    "HARNESS_REGISTRY",
    "register_runtime",
    "unregister_runtime",
    "get_runtime",
    "runtime_names",
    "discover_and_load_harnesses",
]
