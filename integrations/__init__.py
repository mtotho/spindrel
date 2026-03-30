"""Integration auto-discovery.

Scans integrations/*/router.py for a `router` FastAPI APIRouter attribute.
Scans integrations/*/dispatcher.py and auto-imports to trigger register() calls.
Returns [(integration_id, router), ...] for each discovered integration with a router.

Each integration can also provide:
  - dispatcher.py  — calls app.agent.dispatchers.register() at import time
  - hooks.py       — calls app.agent.hooks.register_integration() / register_hook()
  - process.py     — declares CMD/REQUIRED_ENV for dev-server auto-start

Supports external integration directories via INTEGRATION_DIRS config.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import os
import sys
from pathlib import Path

from fastapi import APIRouter

logger = logging.getLogger(__name__)

_INTEGRATIONS_DIR = Path(__file__).parent
_PACKAGES_DIR = _INTEGRATIONS_DIR.parent / "packages"


def _all_integration_dirs() -> list[Path]:
    """Return all integration directories: in-repo integrations/, packages/, + INTEGRATION_DIRS."""
    dirs = [_INTEGRATIONS_DIR, _PACKAGES_DIR]

    try:
        from app.config import settings
        extra = settings.INTEGRATION_DIRS
    except Exception:
        extra = os.environ.get("INTEGRATION_DIRS", "")

    if extra:
        for p in extra.split(":"):
            p = p.strip()
            if p:
                path = Path(p).expanduser().resolve()
                if path.is_dir():
                    dirs.append(path)
                else:
                    logger.warning("INTEGRATION_DIRS path does not exist: %s", path)
    return dirs


def _import_module(integration_id: str, module_name: str, file_path: Path, is_external: bool, source: str = "integration"):
    """Import a module from an integration/package directory.

    For in-repo integrations, uses the standard dotted import.
    For in-repo packages, uses the packages.* dotted import.
    For external directories, uses importlib file-based loading.
    """
    if not is_external:
        prefix = "packages" if source == "package" else "integrations"
        return importlib.import_module(f"{prefix}.{integration_id}.{module_name}")

    mod_name = f"_ext_integration_{integration_id}_{module_name}"
    spec = importlib.util.spec_from_file_location(mod_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not create module spec for {file_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _iter_integration_candidates() -> list[tuple[Path, str, bool, str]]:
    """Yield (candidate_dir, integration_id, is_external, source) for all directories.

    source is 'integration', 'package', or 'external'.
    """
    results = []
    for base_dir in _all_integration_dirs():
        if base_dir == _INTEGRATIONS_DIR:
            source = "integration"
        elif base_dir == _PACKAGES_DIR:
            source = "package"
        else:
            source = "external"
        is_external = source not in ("integration", "package")
        if not base_dir.is_dir():
            continue
        for candidate in sorted(base_dir.iterdir()):
            if not candidate.is_dir():
                continue
            if candidate.name.startswith("_"):
                continue
            results.append((candidate, candidate.name, is_external, source))
    return results


def discover_integrations() -> list[tuple[str, APIRouter]]:
    """Discover and load all integrations. Returns [(integration_id, router)]."""
    results: list[tuple[str, APIRouter]] = []

    for candidate, integration_id, is_external, source in _iter_integration_candidates():
        # Auto-import dispatcher.py to trigger register() (independent of router.py)
        dispatcher_file = candidate / "dispatcher.py"
        if dispatcher_file.exists():
            try:
                _import_module(integration_id, "dispatcher", dispatcher_file, is_external, source)
                logger.debug("Loaded dispatcher for integration: %s", integration_id)
            except Exception:
                logger.exception("Failed to load dispatcher for integration %r", integration_id)

        # Auto-import hooks.py to trigger register_integration() / register_hook()
        hooks_file = candidate / "hooks.py"
        if hooks_file.exists():
            try:
                _import_module(integration_id, "hooks", hooks_file, is_external, source)
                logger.debug("Loaded hooks for integration: %s", integration_id)
            except Exception:
                logger.exception("Failed to load hooks for integration %r", integration_id)

        # Register router if present
        router_file = candidate / "router.py"
        if not router_file.exists():
            continue

        try:
            module = _import_module(integration_id, "router", router_file, is_external, source)
        except Exception:
            logger.exception("Failed to load integration %r — skipping", integration_id)
            continue

        router = getattr(module, "router", None)
        if router is None or not isinstance(router, APIRouter):
            logger.warning("Integration %r has no APIRouter named 'router' — skipping", integration_id)
            continue

        results.append((integration_id, router))

    return results


def discover_identity_fields() -> list[dict]:
    """Discover integration identity fields for user profile linking.

    Returns list of dicts: {id, name, fields: [{key, label, description}]}
    Only includes integrations that have a config.py with IDENTITY_FIELDS.
    """
    results: list[dict] = []

    for candidate, integration_id, is_external, source in _iter_integration_candidates():
        config_file = candidate / "config.py"
        if not config_file.exists():
            continue

        try:
            module = _import_module(integration_id, "config", config_file, is_external, source)
            fields = getattr(module, "IDENTITY_FIELDS", None)
            if fields:
                results.append({
                    "id": integration_id,
                    "name": integration_id.capitalize(),
                    "fields": fields,
                })
        except Exception:
            logger.exception("Failed to load identity fields for integration %r", integration_id)

    return results


def discover_setup_status(base_url: str = "") -> list[dict]:
    """Return setup status for all integrations.

    Returns list of dicts with id, name, capabilities, env var status,
    webhook info, overall status, and README contents.
    """
    results: list[dict] = []

    for candidate, integration_id, is_external, source in _iter_integration_candidates():
        entry: dict = {
            "id": integration_id,
            "name": integration_id.replace("_", " ").replace("-", " ").title(),
            "source": source,
            "has_router": (candidate / "router.py").exists(),
            "has_dispatcher": (candidate / "dispatcher.py").exists(),
            "has_hooks": (candidate / "hooks.py").exists(),
            "has_tools": (candidate / "tools").is_dir(),
            "has_skills": (candidate / "skills").is_dir(),
            "env_vars": [],
            "webhook": None,
            "status": "not_configured",
            "readme": None,
        }

        # Load setup.py if present
        setup_file = candidate / "setup.py"
        if setup_file.exists():
            try:
                module = _import_module(integration_id, "setup", setup_file, is_external, source)
                setup = getattr(module, "SETUP", {})

                # Env vars with is_set check (DB cache > env var)
                for var in setup.get("env_vars", []):
                    try:
                        from app.services.integration_settings import get_value
                        is_set = bool(get_value(integration_id, var["key"]))
                    except ImportError:
                        is_set = bool(os.environ.get(var["key"]))
                    entry["env_vars"].append({
                        "key": var["key"],
                        "required": var.get("required", False),
                        "description": var.get("description", ""),
                        "is_set": is_set,
                    })

                # Webhook
                wh = setup.get("webhook")
                if wh:
                    full_url = f"{base_url.rstrip('/')}{wh['path']}" if base_url else wh["path"]
                    entry["webhook"] = {
                        "path": wh["path"],
                        "url": full_url,
                        "description": wh.get("description", ""),
                    }
            except Exception:
                logger.exception("Failed to load setup.py for integration %r", integration_id)

        # Read README.md if present
        readme_file = candidate / "README.md"
        if readme_file.exists():
            try:
                _readme_text = readme_file.read_text()
                entry["readme"] = _readme_text[:5000]
            except Exception:
                pass

        # Determine status from required env vars
        required_vars = [v for v in entry["env_vars"] if v["required"]]
        if not required_vars:
            # No required vars declared — "ready" if has any capability file
            if entry["has_router"] or entry["has_dispatcher"] or entry["has_hooks"] or entry["has_tools"]:
                entry["status"] = "ready"
        else:
            set_count = sum(1 for v in required_vars if v["is_set"])
            if set_count == len(required_vars):
                entry["status"] = "ready"
            elif set_count > 0:
                entry["status"] = "partial"
            # else remains "not_configured"

        results.append(entry)

    return results


def discover_processes() -> list[dict]:
    """Discover integration background processes.

    Returns list of dicts: {id, cmd, required_env, description}
    Only includes processes whose REQUIRED_ENV vars are all set.
    """
    results: list[dict] = []

    for candidate, integration_id, is_external, source in _iter_integration_candidates():
        process_file = candidate / "process.py"
        if not process_file.exists():
            continue

        try:
            module = _import_module(integration_id, "process", process_file, is_external, source)
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
