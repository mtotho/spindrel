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
    """Import ``harness.py`` from each active resolved integration source.

    Each harness module self-registers via ``register_runtime`` as a side
    effect of import. Called once at app startup from ``app/main.py`` after
    ``discover_and_load_tools``. Mirrors the tool-loader source resolver path.
    """
    from app.services.integration_settings import is_active
    from integrations.discovery import iter_integration_sources

    for source in sorted(iter_integration_sources(), key=lambda s: s.integration_id):
        harness_file = source.path / "harness.py"
        if not harness_file.is_file():
            continue
        integration_id = source.integration_id
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
            _import_harness_module(
                harness_file,
                integration_id,
                is_external=source.is_external,
                source=source.source,
            )
        except ImportError as exc:
            # Integration's Python deps aren't installed (e.g. claude-agent-sdk
            # missing). pip-install the requirements.txt now and retry — this
            # is idempotent and survives container restarts because pip writes
            # into the image's site-packages, which is part of the running
            # container's writable layer (same lifetime as install_deps).
            logger.warning(
                "Harness for %s failed to import (%s) — auto-installing deps and retrying",
                integration_id, exc,
            )
            installed = _auto_install_integration_deps(source.path, integration_id)
            if not installed:
                logger.error(
                    "Could not install deps for %s; harness skipped. Click "
                    "'Reinstall' on /admin/integrations once the cause is fixed.",
                    integration_id,
                )
                continue
            try:
                _import_harness_module(
                    harness_file,
                    integration_id,
                    is_external=source.is_external,
                    source=source.source,
                )
            except Exception as exc2:
                logger.exception(
                    "Harness import retry for %s still failed after pip install: %s",
                    integration_id, exc2,
                )
        except Exception:
            logger.exception(
                "Failed to load harness for integration %s", integration_id,
            )


def _auto_install_integration_deps(integration_dir: Path, integration_id: str) -> bool:
    """Run ``pip install -r requirements.txt`` for the integration synchronously.

    Returns True on success. Called from startup discovery when a harness
    module's import fails — keeps harness bots working out-of-the-box on
    fresh container starts without forcing the admin to click Reinstall.
    """
    import subprocess
    import sys

    req_path = integration_dir / "requirements.txt"
    if not req_path.is_file():
        logger.error(
            "Cannot auto-install deps for %s — no requirements.txt at %s",
            integration_id, req_path,
        )
        return False
    cmd = [sys.executable, "-m", "pip", "install", "-q", "-r", str(req_path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=180, check=False)
    except subprocess.TimeoutExpired:
        logger.error("pip install timed out for %s", integration_id)
        return False
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or b"").decode(errors="replace").strip()
        logger.error("pip install failed for %s: %s", integration_id, err[:1000])
        return False
    logger.info("Auto-installed deps for %s from %s", integration_id, req_path)
    return True


def _import_harness_module(
    harness_file: Path,
    integration_id: str,
    *,
    is_external: bool = False,
    source: str = "integration",
) -> None:
    """Import an integration ``harness.py`` so its registration side effect fires."""
    from integrations.discovery import import_integration_module

    import_integration_module(
        integration_id,
        "harness",
        harness_file,
        is_external,
        source,
    )


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
