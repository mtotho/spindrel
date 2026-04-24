"""Integration auto-discovery.

Scans integrations/*/router.py for a `router` FastAPI APIRouter attribute.
Auto-imports each integration's optional support modules to trigger
self-registration with the relevant agent-side registry.
Returns [(integration_id, router), ...] for each discovered integration with a router.

Each integration can provide:
  - target.py     — defines the typed DispatchTarget subclass and calls
                    ``app.domain.target_registry.register(MyTarget)``.
                    Auto-imported BEFORE renderer.py so the renderer
                    module can import its target class.
  - renderer.py   — defines the ChannelRenderer subclass and calls
                    ``app.integrations.renderer_registry.register(MyRenderer())``.
  - hooks.py      — calls ``app.agent.hooks.register_integration() /
                    register_hook()``.
  - process.py    — declares CMD/REQUIRED_ENV for dev-server auto-start.

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


def _get_manifest_field(integration_id: str, field: str):
    """Read a field from the manifest cache. Returns None if missing."""
    try:
        from app.services.integration_manifests import get_manifest
        manifest = get_manifest(integration_id)
        return manifest.get(field) if manifest else None
    except ImportError:
        return None


def _all_integration_dirs() -> list[Path]:
    """Return all integration directories: in-repo integrations/, packages/, + external."""
    dirs = [_INTEGRATIONS_DIR, _PACKAGES_DIR]

    try:
        from app.services.paths import effective_integration_dirs
        for p in effective_integration_dirs():
            dirs.append(Path(p))
    except Exception:
        # Fallback for early imports before app is fully initialized
        extra = os.environ.get("INTEGRATION_DIRS", "")
        if extra:
            for p in extra.split(":"):
                p = p.strip()
                if p:
                    path = Path(p).expanduser().resolve()
                    if path.is_dir():
                        dirs.append(path)
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


def _get_setup(
    candidate: Path, integration_id: str, is_external: bool, source: str,
) -> dict | None:
    """Get the SETUP-compatible dict for an integration.

    Checks the DB-backed manifest cache first, then falls back to parsing
    integration.yaml directly from disk (for unit tests where the cache
    isn't populated).
    """
    # Try manifest cache (populated from integration.yaml at startup)
    try:
        from app.services.integration_manifests import get_manifest
        manifest = get_manifest(integration_id)
        if manifest:
            return _manifest_to_setup(manifest)
    except ImportError:
        pass

    # Fall back to parsing integration.yaml directly from disk
    yaml_path = candidate / "integration.yaml"
    if yaml_path.exists():
        try:
            from app.services.integration_manifests import parse_integration_yaml
            data = parse_integration_yaml(yaml_path)
            return _manifest_to_setup(data)
        except Exception:
            logger.debug("Failed to parse integration.yaml for %r", integration_id, exc_info=True)

    return None


def _backfill_event_filter_options(setup: dict) -> None:
    """Ensure ``binding.config_fields`` includes an ``event_filter`` multiselect
    whenever the integration declares ``events``.

    - If ``event_filter`` exists without options → populate from events.
    - If no ``event_filter`` field exists → auto-inject one.
    """
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
        return  # already has event_filter field

    # No event_filter field — auto-inject one
    config_fields.append({
        "key": "event_filter",
        "type": "multiselect",
        "label": "Event Filter",
        "description": "Which events to process (empty = all)",
        "options": options,
    })


def _manifest_to_setup(manifest: dict) -> dict:
    """Convert a manifest dict (from integration.yaml) to SETUP-compatible format.

    This allows all existing discover_* functions to work with either source.
    """
    setup: dict = {}
    setup["icon"] = manifest.get("icon", "Plug")
    setup["name"] = manifest.get("name")
    setup["version"] = manifest.get("version")
    setup["description"] = manifest.get("description")

    # settings → env_vars
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

    # dependencies → python_dependencies / npm_dependencies / system_dependencies
    deps = manifest.get("dependencies", {})
    if isinstance(deps, dict):
        if "python" in deps:
            setup["python_dependencies"] = deps["python"]
        if "npm" in deps:
            setup["npm_dependencies"] = deps["npm"]
        if "system" in deps:
            setup["system_dependencies"] = deps["system"]

    # Pass through all other known fields
    from app.services.integration_manifests import PASSTHROUGH_KEYS
    for key in PASSTHROUGH_KEYS:
        if key in manifest:
            setup[key] = manifest[key]

    # Auto-derive binding.config_fields[event_filter].options from top-level events
    _backfill_event_filter_options(setup)

    return setup


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


def _auto_register_target(integration_id: str, target_spec: dict) -> bool:
    """Generate and register a DispatchTarget dataclass from a YAML ``target`` section.

    ``target_spec`` has the shape::

        {"type": "slack", "fields": {"channel_id": "string", "token": "string",
         "thread_ts": "string?", "reply_in_thread": "bool = false"}}

    Type syntax:
      - ``string``  → ``str`` (required)
      - ``string?`` → ``str | None`` (optional, default ``None``)
      - ``int``, ``int?`` — likewise for ``int``
      - ``bool``, ``bool?`` — likewise for ``bool``
      - ``bool = false`` → ``bool`` with default ``False``
      - ``string = foo`` → ``str`` with default ``"foo"``

    Returns True on success, False on failure (logged, never raised).
    """
    import dataclasses

    from app.domain.dispatch_target import _BaseTarget
    from app.domain import target_registry

    type_name = target_spec.get("type")
    fields_spec = target_spec.get("fields", {})

    if not type_name:
        logger.error("YAML target for %r missing required 'type' field", integration_id)
        return False

    # Already registered (e.g. by a target.py that was loaded first)
    if target_registry.get(type_name) is not None:
        return True

    _TYPE_MAP = {"string": str, "str": str, "int": int, "bool": bool}

    dc_fields: list[tuple] = []  # (name, type, field) triples for make_dataclass
    for field_name, type_decl in fields_spec.items():
        type_decl = str(type_decl).strip()

        # Parse "type = default" syntax
        default = dataclasses.MISSING
        if "=" in type_decl:
            type_part, default_str = type_decl.split("=", 1)
            type_decl = type_part.strip()
            default_str = default_str.strip()
            # Coerce default to Python value
            if type_decl.rstrip("?") in ("bool",):
                default = default_str.lower() in ("true", "1", "yes")
            elif type_decl.rstrip("?") in ("int",):
                default = int(default_str)
            else:
                default = default_str

        # Parse optional "?" suffix
        optional = type_decl.endswith("?")
        base_type_str = type_decl.rstrip("?")

        py_type = _TYPE_MAP.get(base_type_str)
        if py_type is None:
            logger.error(
                "YAML target for %r: unknown type %r for field %r",
                integration_id, base_type_str, field_name,
            )
            return False

        if optional:
            py_type = py_type | None  # type: ignore[operator]
            if default is dataclasses.MISSING:
                default = None

        if default is not dataclasses.MISSING:
            dc_fields.append((field_name, py_type, dataclasses.field(default=default)))
        else:
            dc_fields.append((field_name, py_type))

    try:
        cls_name = f"{''.join(w.capitalize() for w in integration_id.split('_'))}Target"
        cls = dataclasses.make_dataclass(
            cls_name,
            dc_fields,
            bases=(_BaseTarget,),
            frozen=True,
        )
        # ClassVars can't be passed through make_dataclass fields — set directly
        cls.type = type_name  # type: ignore[attr-defined]
        cls.integration_id = integration_id  # type: ignore[attr-defined]

        target_registry.register(cls)
        logger.debug("Auto-registered YAML target %r (type=%r) for integration %r", cls_name, type_name, integration_id)
        return True
    except Exception:
        logger.exception("Failed to auto-register YAML target for integration %r", integration_id)
        return False


def _load_single_integration(
    candidate: Path, integration_id: str, is_external: bool, source: str,
) -> APIRouter | None:
    """Load target, renderer, hooks, and router for a single integration.

    Returns the APIRouter if one exists, else None.
    """
    # Register target FIRST so the typed DispatchTarget subclass is
    # available before anything downstream (renderer, router)
    # tries to construct one via `parse_dispatch_target`.
    # Prefers target.py (custom logic); falls back to YAML ``target`` section.
    target_file = candidate / "target.py"
    if target_file.exists():
        try:
            _import_module(integration_id, "target", target_file, is_external, source)
            logger.debug("Loaded target for integration: %s", integration_id)
        except Exception:
            logger.exception("Failed to load target for integration %r", integration_id)
    else:
        # Try YAML-declared target from manifest
        try:
            from app.services.integration_manifests import get_manifest
            manifest = get_manifest(integration_id)
            if manifest and manifest.get("target"):
                _auto_register_target(integration_id, manifest["target"])
        except ImportError:
            pass

    # Auto-import renderer.py to trigger renderer_registry.register() (Phase F+).
    # Each integration's renderer self-registers via a `_register()` helper at
    # module import time. The discovery boundary keeps `app/main.py` ignorant
    # of which integrations exist — never `import integrations.X.renderer`
    # explicitly from `app/`.
    renderer_file = candidate / "renderer.py"
    if renderer_file.exists():
        try:
            _import_module(integration_id, "renderer", renderer_file, is_external, source)
            logger.debug("Loaded renderer for integration: %s", integration_id)
        except Exception:
            logger.exception("Failed to load renderer for integration %r", integration_id)

    # Auto-import hooks.py to trigger register_integration() / register_hook()
    hooks_file = candidate / "hooks.py"
    if hooks_file.exists():
        try:
            _import_module(integration_id, "hooks", hooks_file, is_external, source)
            logger.debug("Loaded hooks for integration: %s", integration_id)
        except Exception:
            logger.exception("Failed to load hooks for integration %r", integration_id)

    # Auto-detect which modules this integration provides
    detected_provides: set[str] = set()
    if target_file.exists() or (
        # YAML-declared target counts too
        not target_file.exists()
        and _get_manifest_field(integration_id, "target")
    ):
        detected_provides.add("target")
    if renderer_file.exists():
        detected_provides.add("renderer")
    if hooks_file.exists():
        detected_provides.add("hooks")
    if (candidate / "router.py").exists():
        detected_provides.add("router")
    if (candidate / "tools").is_dir() and any((candidate / "tools").glob("*.py")):
        detected_provides.add("tools")
    if (candidate / "skills").is_dir() and any((candidate / "skills").glob("*.md")):
        detected_provides.add("skills")
    if (candidate / "machine_control.py").exists() or _get_manifest_field(integration_id, "machine_control"):
        detected_provides.add("machine_control")

    from app.services.integration_manifests import set_detected_provides
    set_detected_provides(integration_id, detected_provides)

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


def _get_process_config(
    candidate: Path, integration_id: str, is_external: bool, source: str,
) -> dict | None:
    """Get process config from process.py or the manifest's ``process`` section.

    Returns ``{"cmd": [...], "required_env": [...], "description": "...",
    "watch_paths": [...] | None}`` or ``None`` if neither source declares a
    process.  ``process.py`` wins when both exist.
    """
    process_file = candidate / "process.py"
    if process_file.exists():
        try:
            mod = _import_module(integration_id, "process", process_file, is_external, source)
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

    # Fall back to manifest cache (integration.yaml) process section
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

    # Fall back to parsing integration.yaml directly from disk (covers
    # cases where the manifest cache isn't populated yet, e.g. unit tests)
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


def discover_setup_status(base_url: str = "") -> list[dict]:
    """Return setup status for all integrations.

    Returns list of dicts with id, name, capabilities, env var status,
    webhook info, overall status, and README contents.
    """
    results: list[dict] = []

    for candidate, integration_id, is_external, source in _iter_integration_candidates():
        proc_cfg = _get_process_config(candidate, integration_id, is_external, source)
        has_process = proc_cfg is not None
        process_description = proc_cfg["description"] if proc_cfg else None
        process_launchable = has_process
        entry: dict = {
            "id": integration_id,
            "name": integration_id.replace("_", " ").replace("-", " ").title(),
            "source": source,
            "icon": "Plug",
            "has_router": (candidate / "router.py").exists(),
            "has_dispatcher": False,  # legacy — dispatcher system removed
            "has_renderer": (candidate / "renderer.py").exists(),
            "has_hooks": (candidate / "hooks.py").exists(),
            "has_tools": any((candidate / "tools").glob("*.py")) if (candidate / "tools").is_dir() else False,
            "has_skills": any((candidate / "skills").glob("**/*.md")) if (candidate / "skills").is_dir() else False,
            "has_process": has_process,
            "process_launchable": process_launchable,
            "process_description": process_description,
            "process_status": None,
            "env_vars": [],
            "webhook": None,
            "api_permissions": None,
            "provides": [],
            "machine_control": None,
            "status": "not_configured",
            "readme": None,
        }

        # Enumerate tool/skill names for detail display
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
        # Self-healing: if tools exist on disk but aren't loaded, and
        # the integration is active, load them now and index into
        # ToolEmbedding so they show up in the bot editor's Tool Pool.
        # Without the index_local_tools call, tools live in the in-memory
        # registry but are invisible to /bots/{id}/editor-data, which
        # queries ToolEmbedding directly.
        if entry["tool_files"] and not entry["tool_names"]:
            try:
                from app.services.integration_settings import is_active as _is_active
                if _is_active(integration_id):
                    from app.tools.loader import load_integration_tools
                    _loaded = load_integration_tools(candidate)
                    if _loaded:
                        logger.info("Self-healed tool loading for %s: %s", integration_id, _loaded)
                        entry["tool_names"] = sorted(
                            name for name, meta in _reg_tools.items()
                            if meta.get("source_integration") == integration_id
                        )
                        # Schedule ToolEmbedding upsert so the Tool Pool
                        # shows these immediately. Fire-and-forget: the
                        # admin endpoint is sync from the user's POV and
                        # we don't want to block page load on embedding.
                        try:
                            import asyncio
                            from app.agent.tools import index_local_tools
                            loop = asyncio.get_running_loop()
                            loop.create_task(index_local_tools())
                        except RuntimeError:
                            pass  # no running loop (e.g. startup); index_local_tools runs elsewhere
            except Exception:
                pass
        skills_dir = candidate / "skills"
        if skills_dir.is_dir():
            entry["skill_files"] = sorted(
                f.stem for f in skills_dir.glob("**/*.md")
            )
        else:
            entry["skill_files"] = []
        # Tool widget templates (declared in integration.yaml tool_widgets section)
        _tw_names: list[str] = []
        try:
            from app.services.widget_templates import get_widget_template
            from app.services.integration_manifests import get_manifest
            _manifest = get_manifest(integration_id)
            if _manifest and isinstance(_manifest.get("tool_widgets"), dict):
                _tw_names = sorted(_manifest["tool_widgets"].keys())
        except Exception:
            pass
        entry["has_tool_widgets"] = len(_tw_names) > 0
        entry["tool_widget_names"] = _tw_names

        # Lifecycle status — drives Library vs. Active in the UI.
        try:
            from app.services.integration_settings import get_status
            entry["lifecycle_status"] = get_status(integration_id)
        except Exception:
            entry["lifecycle_status"] = "available"

        # Include live process status if process manager is available
        if has_process and process_launchable:
            try:
                from app.services.integration_processes import process_manager
                entry["process_status"] = process_manager.status(integration_id)
            except ImportError:
                pass

        # Load manifest (from integration.yaml via DB cache, or setup.py fallback)
        setup = _get_setup(candidate, integration_id, is_external, source)
        entry["has_yaml"] = (candidate / "integration.yaml").exists()
        if setup:
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
                    # check_path: integration-specific path to check (e.g. local node_modules)
                    check_path = dep.get("check_path")
                    if check_path:
                        # Resolve relative paths against the integration directory
                        if not os.path.isabs(check_path):
                            check_path = os.path.join(str(candidate), check_path)
                        installed = os.path.exists(check_path)
                    else:
                        binary = dep.get("binary_name", dep["package"])
                        installed = (
                            shutil.which(binary) is not None
                            or os.path.isfile(os.path.join(_npm_bin, binary))
                        )
                    npm_status.append({"package": dep["package"], "binary_name": dep.get("binary_name", dep["package"]), "installed": installed})
                    if not installed:
                        all_npm_installed = False
                entry["npm_dependencies"] = npm_status
                entry["npm_deps_installed"] = all_npm_installed

            # System dependencies check (binaries that must be pre-installed)
            sys_deps = setup.get("system_dependencies", [])
            if sys_deps:
                import shutil as _shutil
                sys_status = []
                all_sys_installed = True
                for dep in sys_deps:
                    binary = dep.get("binary", "")
                    alternatives = dep.get("alternatives", [])
                    found = False
                    for candidate_bin in [binary, *alternatives]:
                        if _shutil.which(candidate_bin):
                            found = True
                            break
                    sys_status.append({
                        "binary": binary,
                        "apt_package": dep.get("apt_package", binary),
                        "install_hint": dep.get("install_hint", ""),
                        "installed": found,
                    })
                    if not found:
                        all_sys_installed = False
                entry["system_dependencies"] = sys_status
                entry["system_deps_installed"] = all_sys_installed

            # OAuth config (pass through to UI)
            oauth = setup.get("oauth")
            if oauth:
                entry["oauth"] = oauth

            # API permissions
            ap = setup.get("api_permissions")
            if ap:
                entry["api_permissions"] = ap

            provides = setup.get("provides")
            if isinstance(provides, list):
                entry["provides"] = [str(v) for v in provides if str(v).strip()]

            mc = setup.get("machine_control")
            if isinstance(mc, dict):
                entry["machine_control"] = {
                    "provider_id": str(mc.get("provider_id") or integration_id),
                    "label": str(mc.get("label") or entry["name"]),
                    "driver": str(mc.get("driver") or "unknown"),
                    "metadata": mc.get("metadata") if isinstance(mc.get("metadata"), dict) else None,
                }

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

            # MCP servers declared by integration
            mcp = setup.get("mcp_servers")
            if mcp and isinstance(mcp, list):
                entry["mcp_servers"] = mcp

            # Declared events
            events = setup.get("events")
            if events and isinstance(events, list):
                entry["events"] = events

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
        deps_ok = entry.get("deps_installed", True) and entry.get("npm_deps_installed", True) and entry.get("system_deps_installed", True)
        if not required_vars:
            # No required vars declared — "ready" if has any capability file AND deps installed
            if entry["has_router"] or entry["has_dispatcher"] or entry["has_renderer"] or entry["has_hooks"] or entry["has_tools"]:
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
        setup = _get_setup(candidate, integration_id, is_external, source)
        if not setup:
            continue
        for mod in setup.get("dashboard_modules", []):
            results.append({
                "integration_id": integration_id,
                "module_id": mod["id"],
                "label": mod.get("label", mod["id"]),
                "icon": mod.get("icon", "Zap"),
                "description": mod.get("description", ""),
                "api_base": f"/integrations/{integration_id}/mc/{mod['id']}",
            })

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
        setup = _get_setup(candidate, integration_id, is_external, source)
        if not setup:
            continue
        try:
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


_activation_manifests: dict[str, dict] | None = None


def _discover_activation_tools(candidate: Path, integration_id: str) -> list[str]:
    """Best-effort tool list for activation manifests.

    Prefer the live registry because file names are only a fallback proxy for
    registered tool names. When tools are not loaded yet, fall back to the
    integration's ``tools/*.py`` filenames so the admin UI still has a useful
    summary.
    """
    try:
        from app.tools.registry import _tools as _reg_tools

        names = sorted(
            name for name, meta in _reg_tools.items()
            if meta.get("source_integration") == integration_id
        )
        if names:
            return names
    except Exception:
        logger.debug("Failed to inspect tool registry for %s", integration_id, exc_info=True)

    tools_dir = candidate / "tools"
    if not tools_dir.is_dir():
        return []
    return sorted(
        f.stem for f in tools_dir.glob("*.py") if not f.name.startswith("_")
    )


def discover_activation_manifests() -> dict[str, dict]:
    """Discover activation manifests from integration setup.py SETUP dicts.

    Returns {integration_id: activation_manifest} for integrations that
    declare an ``"activation"`` key in their SETUP dict.

    Supports ``"includes": ["other_integration"]`` — the including manifest
    inherits the included integration's declared tools (merged, deduped).
    """
    global _activation_manifests
    results: dict[str, dict] = {}

    for candidate, integration_id, is_external, source in _iter_integration_candidates():
        setup = _get_setup(candidate, integration_id, is_external, source)
        if not setup:
            continue
        activation = setup.get("activation")
        if activation and isinstance(activation, dict):
            # Embed version from top-level SETUP into the manifest
            version = setup.get("version")
            if version and "version" not in activation:
                activation = {**activation, "version": version}
            if not activation.get("tools"):
                activation = {**activation, "tools": _discover_activation_tools(candidate, integration_id)}
            results[integration_id] = activation

    # Resolve "includes" — merge tools and config_fields from included
    # integrations.  requires_workspace is NOT inherited — each integration
    # declares its own requirement.
    for itype, manifest in results.items():
        includes = manifest.get("includes")
        if not includes or not isinstance(includes, list):
            continue
        merged_tools = list(manifest.get("tools", []))
        merged_config_fields = list(manifest.get("config_fields", []))
        existing_keys = {f["key"] for f in merged_config_fields}
        for included_id in includes:
            included = results.get(included_id)
            if not included:
                continue
            for tool_name in included.get("tools", []):
                if tool_name not in merged_tools:
                    merged_tools.append(tool_name)
            for field in included.get("config_fields", []):
                if field["key"] not in existing_keys:
                    merged_config_fields.append({
                        **field,
                        "source_integration": included_id,
                    })
                    existing_keys.add(field["key"])
        if merged_tools:
            manifest["tools"] = merged_tools
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
        setup = _get_setup(candidate, integration_id, is_external, source)
        if not setup:
            continue
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

    return results


def discover_binding_metadata() -> dict[str, dict]:
    """Return binding metadata for all integrations that have it.

    Returns {integration_id: {client_id_prefix, client_id_placeholder, ...}}
    """
    results: dict[str, dict] = {}

    for candidate, integration_id, is_external, source in _iter_integration_candidates():
        setup = _get_setup(candidate, integration_id, is_external, source)
        if not setup:
            continue
        binding = setup.get("binding")
        if binding:
            results[integration_id] = binding

    return results


def discover_integration_events() -> dict[str, list[dict]]:
    """Return declared events for all integrations that have them.

    Returns ``{integration_id: [{type, label, description?, category?}, ...]}``
    """
    results: dict[str, list[dict]] = {}

    for candidate, integration_id, is_external, source in _iter_integration_candidates():
        setup = _get_setup(candidate, integration_id, is_external, source)
        if not setup:
            continue
        events = setup.get("events")
        if events and isinstance(events, list):
            results[integration_id] = events

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
         enabled_setting, description}
    for integrations that declare a ``docker_compose`` key in SETUP.

    ``project_name`` supports ``${SPINDREL_INSTANCE_ID}`` interpolation so
    multiple agent-server instances sharing one Docker daemon get
    non-colliding project identities. Interpolation happens here in Python.
    The compose YAML itself is passed through unchanged — the compose CLI
    does its own env interpolation of ``${VAR}`` (including
    ``${AGENT_NETWORK_NAME}`` for the external-network attachment and
    ``${SPINDREL_INSTANCE_ID}`` for per-service aliases) inside the file at
    run time.
    """
    # Import locally to avoid a hard cycle: integrations is imported very
    # early during startup, before all of app is initialized.
    from app.config import settings as _settings

    def _interp(s):
        if not isinstance(s, str):
            return s
        return s.replace("${SPINDREL_INSTANCE_ID}", _settings.SPINDREL_INSTANCE_ID or "default")

    results: list[dict] = []

    for candidate, integration_id, is_external, source in _iter_integration_candidates():
        setup = _get_setup(candidate, integration_id, is_external, source)
        if not setup:
            continue
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

        enabled_callable = None

        project_name = _interp(dc.get("project_name", f"spindrel-{integration_id}"))

        results.append({
            "integration_id": integration_id,
            "project_name": project_name,
            "compose_definition": compose_definition,
            "config_files": config_files,
            "enabled_setting": enabled_setting,
            "enabled_default": enabled_default,
            "enabled_callable": enabled_callable,
            "description": dc.get("description", ""),
        })

    return results


def discover_processes() -> list[dict]:
    """Discover integration background processes.

    Returns list of dicts: {id, cmd, required_env, description}
    Only includes processes whose REQUIRED_ENV vars are all set.
    Wraps with watchfiles auto-reload when available.
    """
    results: list[dict] = []

    for candidate, integration_id, is_external, source in _iter_integration_candidates():
        proc_cfg = _get_process_config(candidate, integration_id, is_external, source)
        if not proc_cfg:
            continue

        required_env = proc_cfg["required_env"]
        cmd = _resolve_cmd(proc_cfg["cmd"], proc_cfg.get("watch_paths"))
        if all(os.environ.get(v) for v in required_env):
            results.append({
                "id": integration_id,
                "cmd": cmd,
                "required_env": required_env,
                "description": proc_cfg["description"],
            })
        else:
            missing = [v for v in required_env if not os.environ.get(v)]
            logger.debug(
                "Skipping process for integration %r: missing env vars %s",
                integration_id, missing,
            )

    return results
