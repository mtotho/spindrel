"""Manifest/setup compatibility helpers for integrations.

This module is intentionally side-effect-light: it converts declarative
integration manifests into the legacy SETUP-shaped dictionaries and exposes
small helpers for process metadata. Importing it should not register routers,
tools, renderers, or hooks.
"""
from __future__ import annotations

import importlib
import logging
import os

logger = logging.getLogger(__name__)


def get_manifest_field(integration_id: str, field: str):
    """Read a field from the manifest cache. Returns None if missing."""
    try:
        from app.services.integration_manifests import get_manifest

        manifest = get_manifest(integration_id)
        return manifest.get(field) if manifest else None
    except ImportError:
        return None


def get_setup(candidate, integration_id: str, is_external: bool, source: str) -> dict | None:
    """Get the SETUP-compatible dict for an integration.

    Checks the DB-backed manifest cache first, then falls back to parsing
    integration.yaml directly from disk for unit tests where the cache is not
    populated.
    """
    try:
        from app.services.integration_manifests import get_manifest

        manifest = get_manifest(integration_id)
        if manifest:
            return manifest_to_setup(manifest)
    except ImportError:
        pass

    yaml_path = candidate / "integration.yaml"
    if yaml_path.exists():
        try:
            from app.services.integration_manifests import parse_integration_yaml

            data = parse_integration_yaml(yaml_path)
            return manifest_to_setup(data)
        except Exception:
            logger.debug("Failed to parse integration.yaml for %r", integration_id, exc_info=True)

    return None


def backfill_event_filter_options(setup: dict) -> None:
    """Ensure binding.config_fields includes event_filter options from events."""
    events = setup.get("events")
    binding = setup.get("binding")
    if not events or not binding:
        return

    options = [
        {"value": e["type"], "label": e.get("label", e["type"])}
        for e in events
        if isinstance(e, dict) and "type" in e
    ]
    if not options:
        return

    config_fields = binding.get("config_fields")
    if config_fields is None:
        config_fields = []
        binding["config_fields"] = config_fields

    for field in config_fields:
        if field.get("key") != "event_filter":
            continue
        if not field.get("options"):
            field["options"] = options
        return

    config_fields.append({
        "key": "event_filter",
        "type": "multiselect",
        "label": "Event Filter",
        "description": "Which events to process (empty = all)",
        "options": options,
    })


def manifest_to_setup(manifest: dict) -> dict:
    """Convert an integration.yaml manifest into legacy SETUP-compatible shape."""
    setup: dict = {
        "icon": manifest.get("icon", "Plug"),
        "name": manifest.get("name"),
        "version": manifest.get("version"),
        "description": manifest.get("description"),
    }

    settings = manifest.get("settings")
    if settings:
        setup["env_vars"] = [
            {
                "key": s["key"],
                "required": s.get("required", False),
                "secret": s.get("secret", False),
                "description": s.get("label", s["key"]),
                "default": s.get("default"),
                "type": s.get("type", "string"),
            }
            for s in settings
        ]

    deps = manifest.get("dependencies", {})
    if isinstance(deps, dict):
        if "python" in deps:
            setup["python_dependencies"] = deps["python"]
        if "npm" in deps:
            setup["npm_dependencies"] = deps["npm"]
        if "system" in deps:
            setup["system_dependencies"] = deps["system"]

    from app.services.integration_manifests import PASSTHROUGH_KEYS

    for key in PASSTHROUGH_KEYS:
        if key in manifest:
            setup[key] = manifest[key]

    backfill_event_filter_options(setup)
    return setup


def get_process_config(candidate, integration_id: str, is_external: bool, source: str) -> dict | None:
    """Get process config from process.py or the manifest process section."""
    process_file = candidate / "process.py"
    if process_file.exists():
        try:
            from integrations.discovery import import_integration_module

            mod = import_integration_module(integration_id, "process", process_file, is_external, source)
            cmd = getattr(mod, "CMD", None)
            if cmd:
                return {
                    "cmd": list(cmd),
                    "required_env": getattr(mod, "REQUIRED_ENV", []),
                    "description": getattr(mod, "DESCRIPTION", integration_id),
                    "watch_paths": getattr(mod, "WATCH_PATHS", None),
                }
        except Exception:
            logger.exception("Failed to load process.py for integration %r", integration_id)

    try:
        from app.services.integration_manifests import get_manifest

        manifest = get_manifest(integration_id)
        if manifest:
            proc = manifest.get("process")
            if proc and proc.get("cmd"):
                return {
                    "cmd": list(proc["cmd"]),
                    "required_env": proc.get("required_env", []),
                    "description": proc.get("description", integration_id),
                    "watch_paths": proc.get("watch_paths"),
                }
    except ImportError:
        pass

    yaml_path = candidate / "integration.yaml"
    if yaml_path.exists():
        try:
            from app.services.integration_manifests import parse_integration_yaml

            data = parse_integration_yaml(yaml_path)
            proc = data.get("process")
            if proc and proc.get("cmd"):
                return {
                    "cmd": list(proc["cmd"]),
                    "required_env": proc.get("required_env", []),
                    "description": proc.get("description", integration_id),
                    "watch_paths": proc.get("watch_paths"),
                }
        except Exception:
            logger.debug("Failed to parse integration.yaml for %r", integration_id, exc_info=True)

    return None


def resolve_cmd(cmd: list[str], watch_paths: list[str] | None) -> list[str]:
    """Resolve python path and optionally wrap with watchfiles for auto-reload."""
    import shutil
    import sys

    resolved = list(cmd)
    if resolved and resolved[0] == "python":
        resolved[0] = sys.executable

    if not watch_paths:
        return resolved
    if not shutil.which("watchfiles"):
        return resolved
    return ["watchfiles", "--filter", "python", " ".join(resolved)] + watch_paths


# Compatibility aliases for existing private imports while callers migrate.
_get_manifest_field = get_manifest_field
_get_setup = get_setup
_backfill_event_filter_options = backfill_event_filter_options
_manifest_to_setup = manifest_to_setup
_get_process_config = get_process_config
_resolve_cmd = resolve_cmd
