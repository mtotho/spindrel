"""Compatibility facade for integration host discovery.

The implementation is split by ownership:

- :mod:`integrations.discovery` owns source discovery and side-effectful module
  loading for routers, renderers, hooks, and targets.
- :mod:`integrations.manifest_setup` owns manifest-to-SETUP compatibility and
  process metadata.
- :mod:`app.services.integration_catalog` owns side-effect-free catalog and
  admin read-model projections.

Keep this package root shallow. Public names remain here so existing imports
continue to work while production callers move to the owning modules.
"""
from __future__ import annotations

from app.services.integration_catalog import (
    discover_activation_manifests,
    discover_binding_metadata,
    discover_dashboard_modules,
    discover_docker_compose_stacks,
    discover_integration_events,
    discover_processes,
    discover_setup_status,
    discover_sidebar_sections,
    discover_web_uis,
    get_activation_manifests,
)
from integrations.discovery import (
    _INTEGRATIONS_DIR,
    _PACKAGES_DIR,
    _all_integration_dirs,
    _auto_register_target,
    _import_module,
    _iter_integration_candidates,
    _load_single_integration,
    _loaded_ids,
    all_integration_dirs,
    discover_identity_fields,
    discover_integrations,
    import_integration_module,
    iter_integration_candidates,
    load_new_integrations,
    load_single_integration,
)
from integrations.manifest_setup import (
    _backfill_event_filter_options,
    _get_manifest_field,
    _get_process_config,
    _get_setup,
    _manifest_to_setup,
    _resolve_cmd,
    backfill_event_filter_options,
    get_manifest_field,
    get_process_config,
    get_setup,
    manifest_to_setup,
    resolve_cmd,
)


def _get_setup_vars(integration_id: str) -> list[dict]:
    """Compatibility wrapper for older integration-settings tests/imports."""
    from app.services.integration_admin import get_setup_vars

    return get_setup_vars(integration_id)


__all__ = [
    "_INTEGRATIONS_DIR",
    "_PACKAGES_DIR",
    "_all_integration_dirs",
    "_auto_register_target",
    "_backfill_event_filter_options",
    "_get_manifest_field",
    "_get_process_config",
    "_get_setup",
    "_get_setup_vars",
    "_import_module",
    "_iter_integration_candidates",
    "_load_single_integration",
    "_loaded_ids",
    "_manifest_to_setup",
    "_resolve_cmd",
    "all_integration_dirs",
    "backfill_event_filter_options",
    "discover_activation_manifests",
    "discover_binding_metadata",
    "discover_dashboard_modules",
    "discover_docker_compose_stacks",
    "discover_identity_fields",
    "discover_integration_events",
    "discover_integrations",
    "discover_processes",
    "discover_setup_status",
    "discover_sidebar_sections",
    "discover_web_uis",
    "get_activation_manifests",
    "get_manifest_field",
    "get_process_config",
    "get_setup",
    "import_integration_module",
    "iter_integration_candidates",
    "load_new_integrations",
    "load_single_integration",
    "manifest_to_setup",
    "resolve_cmd",
]
