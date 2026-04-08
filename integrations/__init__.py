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

# Tracks integration IDs loaded during discover_integrations() and load_new_integrations().
_loaded_ids: set[str] = set()


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
    Later directories override earlier ones (external > package > integration).
    """
    seen: dict[str, int] = {}
    results: list[tuple[Path, str, bool, str]] = []
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
            if candidate.name.startswith(("_", ".")):
                continue
            name = candidate.name
            if name in seen:
                # Later source overrides earlier one
                results[seen[name]] = (candidate, name, is_external, source)
            else:
                seen[name] = len(results)
                results.append((candidate, name, is_external, source))
    return results


def _load_single_integration(
    candidate: Path, integration_id: str, is_external: bool, source: str,
) -> APIRouter | None:
    """Load dispatcher, hooks, and router for a single integration.

    Returns the APIRouter if one exists, else None.
    """
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
        return None

    try:
        module = _import_module(integration_id, "router", router_file, is_external, source)
    except Exception:
        logger.exception("Failed to load integration %r — skipping", integration_id)
        return None

    router = getattr(module, "router", None)
    if router is None or not isinstance(router, APIRouter):
        logger.warning("Integration %r has no APIRouter named 'router' — skipping", integration_id)
        return None

    return router


def discover_integrations() -> list[tuple[str, APIRouter]]:
    """Discover and load all integrations. Returns [(integration_id, router)]."""
    global _loaded_ids
    results: list[tuple[str, APIRouter]] = []

    for candidate, integration_id, is_external, source in _iter_integration_candidates():
        router = _load_single_integration(candidate, integration_id, is_external, source)
        _loaded_ids.add(integration_id)
        if router is not None:
            results.append((integration_id, router))

    return results


def load_new_integrations(app) -> list[tuple[str, Path]]:
    """Discover integrations added since last discover/reload, register their routers.

    Returns [(integration_id, candidate_dir)] for each newly loaded integration.
    """
    global _loaded_ids
    newly_loaded: list[tuple[str, Path]] = []

    for candidate, integration_id, is_external, source in _iter_integration_candidates():
        if integration_id in _loaded_ids:
            continue

        logger.info("Hot-loading new integration: %s (from %s)", integration_id, candidate)
        router = _load_single_integration(candidate, integration_id, is_external, source)
        _loaded_ids.add(integration_id)

        if router is not None:
            app.include_router(router, prefix=f"/integrations/{integration_id}")

        newly_loaded.append((integration_id, candidate))

    return newly_loaded


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
        process_file = candidate / "process.py"
        has_process = process_file.exists()
        process_description = None
        process_launchable = False
        if has_process:
            try:
                mod = _import_module(integration_id, "process", process_file, is_external, source)
                process_description = getattr(mod, "DESCRIPTION", None)
                process_launchable = bool(getattr(mod, "CMD", None))
            except Exception:
                pass
        entry: dict = {
            "id": integration_id,
            "name": integration_id.replace("_", " ").replace("-", " ").title(),
            "source": source,
            "icon": "Plug",
            "has_router": (candidate / "router.py").exists(),
            "has_dispatcher": (candidate / "dispatcher.py").exists(),
            "has_hooks": (candidate / "hooks.py").exists(),
            "has_tools": any((candidate / "tools").glob("*.py")) if (candidate / "tools").is_dir() else False,
            "has_skills": any((candidate / "skills").glob("**/*.md")) if (candidate / "skills").is_dir() else False,
            "has_carapaces": any((candidate / "carapaces").glob("**/*.yaml")) if (candidate / "carapaces").is_dir() else False,
            "has_process": has_process,
            "process_launchable": process_launchable,
            "process_description": process_description,
            "process_status": None,
            "env_vars": [],
            "webhook": None,
            "api_permissions": None,
            "status": "not_configured",
            "readme": None,
        }

        # Enumerate tool/skill/carapace names for detail display
        # Prefer live registry (shows actual loaded tool names); fall back to files on disk
        try:
            from app.tools.registry import _tools as _reg_tools
            entry["tool_names"] = sorted(
                name for name, meta in _reg_tools.items()
                if meta.get("source_integration") == integration_id
            )
        except Exception:
            entry["tool_names"] = []
        tools_dir = candidate / "tools"
        if tools_dir.is_dir():
            entry["tool_files"] = sorted(
                f.stem for f in tools_dir.glob("*.py") if not f.name.startswith("_")
            )
        else:
            entry["tool_files"] = []
        skills_dir = candidate / "skills"
        if skills_dir.is_dir():
            entry["skill_files"] = sorted(
                f.stem for f in skills_dir.glob("**/*.md")
            )
        else:
            entry["skill_files"] = []
        carapaces_dir = candidate / "carapaces"
        if carapaces_dir.is_dir():
            # Flat: carapaces/foo.yaml → stem is "foo"
            # Nested: carapaces/foo/carapace.yaml → use parent dir name
            carapace_names: set[str] = set()
            for f in carapaces_dir.glob("**/*.yaml"):
                if f.name == "carapace.yaml":
                    carapace_names.add(f.parent.name)
                else:
                    carapace_names.add(f.stem)
            entry["carapace_files"] = sorted(carapace_names)
        else:
            entry["carapace_files"] = []

        # Check if globally disabled
        try:
            from app.services.integration_settings import is_disabled
            entry["disabled"] = is_disabled(integration_id)
        except Exception:
            entry["disabled"] = False

        # Include live process status if process manager is available
        if has_process and process_launchable:
            try:
                from app.services.integration_processes import process_manager
                entry["process_status"] = process_manager.status(integration_id)
            except ImportError:
                pass

        # Load setup.py if present
        setup_file = candidate / "setup.py"
        if setup_file.exists():
            try:
                module = _import_module(integration_id, "setup", setup_file, is_external, source)
                setup = getattr(module, "SETUP", {})
                entry["icon"] = setup.get("icon", "Plug")

                # Env vars with is_set check (DB cache > env var > default)
                for var in setup.get("env_vars", []):
                    try:
                        from app.services.integration_settings import get_value
                        is_set = bool(get_value(integration_id, var["key"])) or bool(var.get("default"))
                    except ImportError:
                        is_set = bool(os.environ.get(var["key"])) or bool(var.get("default"))
                    entry["env_vars"].append({
                        "key": var["key"],
                        "required": var.get("required", False),
                        "description": var.get("description", ""),
                        "default": var.get("default"),
                        "is_set": is_set,
                    })

                # Python dependencies check
                py_deps = setup.get("python_dependencies", [])
                if py_deps:
                    deps_status = []
                    all_installed = True
                    for dep in py_deps:
                        import_name = dep.get("import_name", dep.get("package", "").replace("-", "_"))
                        try:
                            importlib.import_module(import_name)
                            deps_status.append({"package": dep["package"], "installed": True})
                        except ImportError:
                            deps_status.append({"package": dep["package"], "installed": False})
                            all_installed = False
                    entry["python_dependencies"] = deps_status
                    entry["deps_installed"] = all_installed

                # npm / binary dependencies check
                npm_deps = setup.get("npm_dependencies", [])
                if npm_deps:
                    import shutil
                    _npm_bin = os.path.expanduser("~/.local/bin")
                    npm_status = []
                    all_npm_installed = True
                    for dep in npm_deps:
                        binary = dep.get("binary_name", dep["package"])
                        installed = (
                            shutil.which(binary) is not None
                            or os.path.isfile(os.path.join(_npm_bin, binary))
                        )
                        npm_status.append({"package": dep["package"], "binary_name": binary, "installed": installed})
                        if not installed:
                            all_npm_installed = False
                    entry["npm_dependencies"] = npm_status
                    entry["npm_deps_installed"] = all_npm_installed

                # OAuth config (pass through to UI)
                oauth = setup.get("oauth")
                if oauth:
                    entry["oauth"] = oauth

                # API permissions
                ap = setup.get("api_permissions")
                if ap:
                    entry["api_permissions"] = ap

                # Debug actions
                da = setup.get("debug_actions")
                if da and isinstance(da, list):
                    entry["debug_actions"] = da

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

        # Determine status from required env vars + python/npm dependencies
        required_vars = [v for v in entry["env_vars"] if v["required"]]
        deps_ok = entry.get("deps_installed", True) and entry.get("npm_deps_installed", True)
        if not required_vars:
            # No required vars declared — "ready" if has any capability file AND deps installed
            if entry["has_router"] or entry["has_dispatcher"] or entry["has_hooks"] or entry["has_tools"] or entry["has_carapaces"]:
                entry["status"] = "ready" if deps_ok else "partial"
        else:
            set_count = sum(1 for v in required_vars if v["is_set"])
            if set_count == len(required_vars) and deps_ok:
                entry["status"] = "ready"
            elif set_count > 0 or not deps_ok:
                entry["status"] = "partial"
            # else remains "not_configured"

        results.append(entry)

    return results


def discover_dashboard_modules() -> list[dict]:
    """Discover dashboard modules from integration setup.py manifests.

    Returns list of dicts:
        {integration_id, module_id, label, icon, description, api_base}
    """
    results: list[dict] = []

    for candidate, integration_id, is_external, source in _iter_integration_candidates():
        setup_file = candidate / "setup.py"
        if not setup_file.exists():
            continue
        try:
            module = _import_module(integration_id, "setup", setup_file, is_external, source)
            setup = getattr(module, "SETUP", {})
            for mod in setup.get("dashboard_modules", []):
                results.append({
                    "integration_id": integration_id,
                    "module_id": mod["id"],
                    "label": mod.get("label", mod["id"]),
                    "icon": mod.get("icon", "Zap"),
                    "description": mod.get("description", ""),
                    "api_base": f"/integrations/{integration_id}/mc/{mod['id']}",
                })
        except Exception:
            logger.exception("Failed to load dashboard modules for integration %r", integration_id)

    return results


_sidebar_sections_cache: list[dict] | None = None


def discover_sidebar_sections(*, refresh: bool = False) -> list[dict]:
    """Discover sidebar sections from integration setup.py manifests.

    Integrations declare a ``sidebar_section`` in their ``SETUP`` dict to add
    a navigation section to the main sidebar.  Format::

        "sidebar_section": {
            "id": "mission-control",       # unique section ID
            "title": "MISSION CONTROL",    # sidebar header text
            "icon": "LayoutDashboard",     # lucide icon for collapsed rail
            "items": [
                {"label": "Dashboard", "href": "/mission-control", "icon": "LayoutDashboard"},
                {"label": "Kanban",    "href": "/mission-control/kanban", "icon": "Columns"},
            ],
            "readiness_endpoint": "/api/v1/mission-control/readiness",  # optional
            "readiness_field": "dashboard",                              # optional
        }

    Returns list of dicts with the above fields plus ``integration_id``.
    Results are cached after the first call; pass ``refresh=True`` to rebuild.
    """
    global _sidebar_sections_cache
    if _sidebar_sections_cache is not None and not refresh:
        return _sidebar_sections_cache

    results: list[dict] = []

    for candidate, integration_id, is_external, source in _iter_integration_candidates():
        setup_file = candidate / "setup.py"
        if not setup_file.exists():
            continue
        try:
            module = _import_module(integration_id, "setup", setup_file, is_external, source)
            setup = getattr(module, "SETUP", {})
            section = setup.get("sidebar_section")
            if section and isinstance(section, dict) and "id" in section and section.get("items"):
                results.append({
                    "integration_id": integration_id,
                    "id": section["id"],
                    "title": section.get("title", section["id"].upper()),
                    "icon": section.get("icon", "Plug"),
                    "items": [
                        item for item in section["items"]
                        if isinstance(item, dict) and "label" in item and "href" in item
                    ],
                    "readiness_endpoint": section.get("readiness_endpoint"),
                    "readiness_field": section.get("readiness_field"),
                })
        except Exception:
            logger.exception("Failed to load sidebar section for integration %r", integration_id)

    _sidebar_sections_cache = results
    return results


_chat_huds: dict[str, list[dict]] | None = None


def discover_chat_huds() -> dict[str, list[dict]]:
    """Discover chat HUD widget declarations from integration setup.py SETUP dicts.

    Returns {integration_id: [hud_widget_configs]} for integrations that
    declare a ``"chat_hud"`` key in their SETUP dict.  Each widget must have
    at least ``id`` and ``style`` fields.
    """
    global _chat_huds
    results: dict[str, list[dict]] = {}
    valid_styles = {"status_strip", "side_panel", "input_bar", "floating_action"}

    for candidate, integration_id, is_external, source in _iter_integration_candidates():
        setup_file = candidate / "setup.py"
        if not setup_file.exists():
            continue
        try:
            module = _import_module(integration_id, "setup", setup_file, is_external, source)
            setup = getattr(module, "SETUP", {})
            huds = setup.get("chat_hud")
            if not huds or not isinstance(huds, list):
                continue
            validated: list[dict] = []
            for widget in huds:
                if not isinstance(widget, dict):
                    continue
                if "id" not in widget or "style" not in widget:
                    logger.warning(
                        "Integration %r chat_hud widget missing id/style — skipping",
                        integration_id,
                    )
                    continue
                if widget["style"] not in valid_styles:
                    logger.warning(
                        "Integration %r chat_hud widget has invalid style %r — skipping",
                        integration_id, widget["style"],
                    )
                    continue
                validated.append(widget)
            if validated:
                results[integration_id] = validated
        except Exception:
            logger.exception("Failed to load chat_hud config for integration %r", integration_id)

    _chat_huds = results
    return results


def get_chat_huds() -> dict[str, list[dict]]:
    """Return cached chat HUD declarations, discovering if needed."""
    global _chat_huds
    if _chat_huds is None:
        return discover_chat_huds()
    return _chat_huds


_chat_hud_presets: dict[str, dict[str, dict]] | None = None


def discover_chat_hud_presets() -> dict[str, dict[str, dict]]:
    """Discover chat HUD layout presets from integration setup.py SETUP dicts.

    Returns ``{integration_id: {preset_name: {"label": str, "widgets": [str]}}}``
    for integrations that declare ``chat_hud_presets`` in SETUP.  Widget IDs in
    each preset are validated against the integration's ``chat_hud`` widgets.
    """
    global _chat_hud_presets
    huds = get_chat_huds()
    results: dict[str, dict[str, dict]] = {}

    for candidate, integration_id, is_external, source in _iter_integration_candidates():
        setup_file = candidate / "setup.py"
        if not setup_file.exists():
            continue
        try:
            module = _import_module(integration_id, "setup", setup_file, is_external, source)
            setup = getattr(module, "SETUP", {})
            presets = setup.get("chat_hud_presets")
            if not presets or not isinstance(presets, dict):
                continue
            # Validate widget IDs against declared chat_hud widgets
            valid_widget_ids = {w["id"] for w in huds.get(integration_id, [])}
            validated: dict[str, dict] = {}
            for name, preset in presets.items():
                if not isinstance(preset, dict) or "label" not in preset:
                    logger.warning(
                        "Integration %r chat_hud_presets[%r] missing label — skipping",
                        integration_id, name,
                    )
                    continue
                widgets = preset.get("widgets", [])
                bad = [w for w in widgets if w not in valid_widget_ids]
                if bad:
                    logger.warning(
                        "Integration %r chat_hud_presets[%r] references unknown widget IDs %s — skipping them",
                        integration_id, name, bad,
                    )
                    widgets = [w for w in widgets if w in valid_widget_ids]
                entry = {"label": preset["label"], "widgets": widgets}
                if "description" in preset:
                    entry["description"] = preset["description"]
                validated[name] = entry
            if validated:
                results[integration_id] = validated
        except Exception:
            logger.exception("Failed to load chat_hud_presets for integration %r", integration_id)

    _chat_hud_presets = results
    return results


def get_chat_hud_presets() -> dict[str, dict[str, dict]]:
    """Return cached chat HUD presets, discovering if needed."""
    global _chat_hud_presets
    if _chat_hud_presets is None:
        return discover_chat_hud_presets()
    return _chat_hud_presets


_activation_manifests: dict[str, dict] | None = None


def discover_activation_manifests() -> dict[str, dict]:
    """Discover activation manifests from integration setup.py SETUP dicts.

    Returns {integration_id: activation_manifest} for integrations that
    declare an ``"activation"`` key in their SETUP dict.

    Supports ``"includes": ["other_integration"]`` — the including manifest
    inherits the included integration's carapaces (merged, deduped).
    """
    global _activation_manifests
    results: dict[str, dict] = {}

    for candidate, integration_id, is_external, source in _iter_integration_candidates():
        setup_file = candidate / "setup.py"
        if not setup_file.exists():
            continue
        try:
            module = _import_module(integration_id, "setup", setup_file, is_external, source)
            setup = getattr(module, "SETUP", {})
            activation = setup.get("activation")
            if activation and isinstance(activation, dict):
                # Embed version from top-level SETUP into the manifest
                version = setup.get("version")
                if version and "version" not in activation:
                    activation = {**activation, "version": version}
                results[integration_id] = activation
        except Exception:
            logger.exception("Failed to load activation manifest for integration %r", integration_id)

    # Resolve "includes" — merge carapaces and config_fields from included
    # integrations.  requires_workspace is NOT inherited — each integration
    # declares its own requirement.
    for itype, manifest in results.items():
        includes = manifest.get("includes")
        if not includes or not isinstance(includes, list):
            continue
        merged_carapaces = list(manifest.get("carapaces", []))
        merged_config_fields = list(manifest.get("config_fields", []))
        existing_keys = {f["key"] for f in merged_config_fields}
        for included_id in includes:
            included = results.get(included_id)
            if not included:
                continue
            for cap_id in included.get("carapaces", []):
                if cap_id not in merged_carapaces:
                    merged_carapaces.append(cap_id)
            for field in included.get("config_fields", []):
                if field["key"] not in existing_keys:
                    merged_config_fields.append({
                        **field,
                        "source_integration": included_id,
                    })
                    existing_keys.add(field["key"])
        manifest["carapaces"] = merged_carapaces
        if merged_config_fields:
            manifest["config_fields"] = merged_config_fields

    _activation_manifests = results
    return results


def get_activation_manifests() -> dict[str, dict]:
    """Return cached activation manifests, discovering if needed."""
    global _activation_manifests
    if _activation_manifests is None:
        return discover_activation_manifests()
    return _activation_manifests


def discover_web_uis() -> list[dict]:
    """Discover integrations that ship a web UI (static build).

    Scans SETUP dicts for a ``web_ui`` key containing::

        "web_ui": {
            "static_dir": "dashboard/dist",  # relative to integration dir
            "dev_port": 5173,                # optional: Vite dev server port
        }

    Returns list of dicts:
        {integration_id, static_dir_path (absolute Path), dev_port (int|None)}
    Only includes entries where the static_dir actually exists on disk.
    """
    results: list[dict] = []

    for candidate, integration_id, is_external, source in _iter_integration_candidates():
        setup_file = candidate / "setup.py"
        if not setup_file.exists():
            continue
        try:
            module = _import_module(integration_id, "setup", setup_file, is_external, source)
            setup = getattr(module, "SETUP", {})
            web_ui = setup.get("web_ui")
            if not web_ui or not isinstance(web_ui, dict):
                continue
            static_dir = web_ui.get("static_dir")
            if not static_dir:
                continue
            static_path = (candidate / static_dir).resolve()
            if not static_path.is_dir():
                logger.warning(
                    "Integration %r declares web_ui but static dir does not exist: %s "
                    "(run 'npm run build' inside the dashboard directory)",
                    integration_id, static_path,
                )
                continue
            results.append({
                "integration_id": integration_id,
                "static_dir_path": static_path,
                "dev_port": web_ui.get("dev_port"),
            })
            logger.info("Discovered web UI for integration %r: %s", integration_id, static_path)
        except Exception:
            logger.exception("Failed to load web_ui config for integration %r", integration_id)

    return results


def discover_binding_metadata() -> dict[str, dict]:
    """Return binding metadata for all integrations that have it.

    Returns {integration_id: {client_id_prefix, client_id_placeholder, ...}}
    """
    results: dict[str, dict] = {}

    for candidate, integration_id, is_external, source in _iter_integration_candidates():
        setup_file = candidate / "setup.py"
        if not setup_file.exists():
            continue
        try:
            module = _import_module(integration_id, "setup", setup_file, is_external, source)
            setup = getattr(module, "SETUP", {})
            binding = setup.get("binding")
            if binding:
                results[integration_id] = binding
        except Exception:
            logger.exception("Failed to load binding metadata for integration %r", integration_id)

    return results


def _resolve_cmd(cmd: list[str], watch_paths: list[str] | None) -> list[str]:
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


def discover_docker_compose_stacks() -> list[dict]:
    """Discover integration Docker Compose stacks from setup.py manifests.

    Returns list of dicts:
        {integration_id, project_name, compose_definition, config_files,
         enabled_setting, connect_networks, description}
    for integrations that declare a ``docker_compose`` key in SETUP.
    """
    results: list[dict] = []

    for candidate, integration_id, is_external, source in _iter_integration_candidates():
        setup_file = candidate / "setup.py"
        if not setup_file.exists():
            continue
        try:
            module = _import_module(integration_id, "setup", setup_file, is_external, source)
            setup = getattr(module, "SETUP", {})
            dc = setup.get("docker_compose")
            if not dc or not isinstance(dc, dict):
                continue

            compose_file = dc.get("file")
            if not compose_file:
                continue

            compose_path = candidate / compose_file
            if not compose_path.exists():
                logger.warning(
                    "Integration %r declares docker_compose but file not found: %s",
                    integration_id, compose_path,
                )
                continue

            compose_definition = compose_path.read_text()

            # Read config files
            config_files: dict[str, str] = {}
            for rel_path in dc.get("config_files", []):
                cfg_path = candidate / rel_path
                if cfg_path.exists():
                    config_files[rel_path] = cfg_path.read_text()
                else:
                    logger.warning(
                        "Integration %r docker_compose config_file not found: %s",
                        integration_id, cfg_path,
                    )

            # Resolve the default for enabled_setting from env_vars
            enabled_setting = dc.get("enabled_setting")
            enabled_default = "false"
            if enabled_setting:
                for var in setup.get("env_vars", []):
                    if var.get("key") == enabled_setting:
                        enabled_default = var.get("default", "false")
                        break

            results.append({
                "integration_id": integration_id,
                "project_name": dc.get("project_name", f"spindrel-{integration_id}"),
                "compose_definition": compose_definition,
                "config_files": config_files,
                "enabled_setting": enabled_setting,
                "enabled_default": enabled_default,
                "connect_networks": dc.get("connect_networks", []),
                "description": dc.get("description", ""),
            })
        except Exception:
            logger.exception("Failed to load docker_compose config for integration %r", integration_id)

    return results


def discover_processes() -> list[dict]:
    """Discover integration background processes.

    Returns list of dicts: {id, cmd, required_env, description}
    Only includes processes whose REQUIRED_ENV vars are all set.
    Wraps with watchfiles auto-reload when available.
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
            watch_paths = getattr(module, "WATCH_PATHS", None)
            cmd = _resolve_cmd(cmd, watch_paths)
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
