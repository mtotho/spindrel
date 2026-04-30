"""Integration source discovery and side-effectful runtime loading."""
from __future__ import annotations

import dataclasses
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

_loaded_ids: set[str] = set()


@dataclasses.dataclass(frozen=True)
class IntegrationSource:
    """Resolved integration directory with source metadata.

    This is the side-effect-free source-of-truth for integration filesystem
    roots. Consumers that need assets, widgets, manifests, tools, harnesses,
    or setup metadata should resolve through this seam instead of rebuilding
    ``integrations/<id>`` paths locally.
    """

    integration_id: str
    path: Path
    source: str
    is_external: bool


def all_integration_dirs() -> list[Path]:
    """Return all integration directories: in-repo integrations/, packages/, + external."""
    dirs = [_INTEGRATIONS_DIR, _PACKAGES_DIR]

    try:
        from app.services.paths import effective_integration_dirs

        for p in effective_integration_dirs():
            dirs.append(Path(p))
    except Exception:
        extra = os.environ.get("INTEGRATION_DIRS", "")
        if extra:
            for p in extra.split(":"):
                p = p.strip()
                if p:
                    path = Path(p).expanduser().resolve()
                    if path.is_dir():
                        dirs.append(path)
    return dirs


def _source_for_base_dir(base_dir: Path) -> tuple[str, bool]:
    base_dir = Path(base_dir)
    if base_dir.resolve() == _INTEGRATIONS_DIR.resolve():
        return "integration", False
    if base_dir.resolve() == _PACKAGES_DIR.resolve():
        return "package", False
    return "external", True


def iter_integration_sources() -> list[IntegrationSource]:
    """Return resolved integration sources.

    Later directories override earlier ones, preserving the existing host
    policy: external dirs override packages, packages override in-repo
    integrations, and later external dirs override earlier external dirs.
    """
    seen: dict[str, int] = {}
    results: list[IntegrationSource] = []
    for base_dir in all_integration_dirs():
        base_dir = Path(base_dir)
        source, is_external = _source_for_base_dir(base_dir)
        if not base_dir.is_dir():
            continue
        for candidate in sorted(base_dir.iterdir()):
            if not candidate.is_dir() or candidate.name.startswith(("_", ".")):
                continue
            integration_source = IntegrationSource(
                integration_id=candidate.name,
                path=candidate.resolve(),
                source=source,
                is_external=is_external,
            )
            if candidate.name in seen:
                results[seen[candidate.name]] = integration_source
            else:
                seen[candidate.name] = len(results)
                results.append(integration_source)
    return results


def find_integration_source(integration_id: str) -> IntegrationSource | None:
    """Return the active source for ``integration_id`` or None."""
    if not integration_id or "/" in integration_id or "\\" in integration_id:
        return None
    if integration_id in {".", ".."}:
        return None
    for source in iter_integration_sources():
        if source.integration_id == integration_id:
            return source
    return None


def resolve_integration_path(integration_id: str, *parts: str | Path) -> Path | None:
    """Resolve a path under an integration source with traversal protection."""
    source = find_integration_source(integration_id)
    if source is None:
        return None
    target = source.path.joinpath(*parts).resolve()
    try:
        target.relative_to(source.path)
    except ValueError:
        return None
    return target


def import_integration_module(
    integration_id: str,
    module_name: str,
    file_path: Path,
    is_external: bool,
    source: str = "integration",
):
    """Import a module from an integration/package directory."""
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


def iter_integration_candidates() -> list[tuple[Path, str, bool, str]]:
    """Yield (candidate_dir, integration_id, is_external, source) candidates.

    Later directories override earlier ones: external > package > integration.
    """
    return [
        (source.path, source.integration_id, source.is_external, source.source)
        for source in iter_integration_sources()
    ]


def _auto_register_target(integration_id: str, target_spec: dict) -> bool:
    """Generate and register a DispatchTarget dataclass from a YAML target section."""
    from app.domain.dispatch_target import _BaseTarget
    from app.domain import target_registry

    type_name = target_spec.get("type")
    fields_spec = target_spec.get("fields", {})

    if not type_name:
        logger.error("YAML target for %r missing required 'type' field", integration_id)
        return False

    if target_registry.get(type_name) is not None:
        return True

    type_map = {"string": str, "str": str, "int": int, "bool": bool}
    dc_fields: list[tuple] = []
    for field_name, type_decl in fields_spec.items():
        type_decl = str(type_decl).strip()
        default = dataclasses.MISSING
        if "=" in type_decl:
            type_part, default_str = type_decl.split("=", 1)
            type_decl = type_part.strip()
            default_str = default_str.strip()
            if type_decl.rstrip("?") == "bool":
                default = default_str.lower() in ("true", "1", "yes")
            elif type_decl.rstrip("?") == "int":
                default = int(default_str)
            else:
                default = default_str

        optional = type_decl.endswith("?")
        base_type_str = type_decl.rstrip("?")
        py_type = type_map.get(base_type_str)
        if py_type is None:
            logger.error(
                "YAML target for %r: unknown type %r for field %r",
                integration_id,
                base_type_str,
                field_name,
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
        cls = dataclasses.make_dataclass(cls_name, dc_fields, bases=(_BaseTarget,), frozen=True)
        cls.type = type_name  # type: ignore[attr-defined]
        cls.integration_id = integration_id  # type: ignore[attr-defined]
        target_registry.register(cls)
        logger.debug(
            "Auto-registered YAML target %r (type=%r) for integration %r",
            cls_name,
            type_name,
            integration_id,
        )
        return True
    except Exception:
        logger.exception("Failed to auto-register YAML target for integration %r", integration_id)
        return False


def load_single_integration(candidate: Path, integration_id: str, is_external: bool, source: str) -> APIRouter | None:
    """Load target, renderer, hooks, and router for one integration."""
    from integrations.manifest_setup import get_manifest_field

    target_file = candidate / "target.py"
    if target_file.exists():
        try:
            import_integration_module(integration_id, "target", target_file, is_external, source)
            logger.debug("Loaded target for integration: %s", integration_id)
        except Exception:
            logger.exception("Failed to load target for integration %r", integration_id)
    else:
        try:
            from app.services.integration_manifests import get_manifest

            manifest = get_manifest(integration_id)
            if manifest and manifest.get("target"):
                _auto_register_target(integration_id, manifest["target"])
        except ImportError:
            pass

    renderer_file = candidate / "renderer.py"
    if renderer_file.exists():
        try:
            import_integration_module(integration_id, "renderer", renderer_file, is_external, source)
            logger.debug("Loaded renderer for integration: %s", integration_id)
        except Exception:
            logger.exception("Failed to load renderer for integration %r", integration_id)

    hooks_file = candidate / "hooks.py"
    if hooks_file.exists():
        try:
            import_integration_module(integration_id, "hooks", hooks_file, is_external, source)
            logger.debug("Loaded hooks for integration: %s", integration_id)
        except Exception:
            logger.exception("Failed to load hooks for integration %r", integration_id)

    detected_provides: set[str] = set()
    if target_file.exists() or (not target_file.exists() and get_manifest_field(integration_id, "target")):
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
    if (candidate / "harness.py").exists():
        detected_provides.add("harness")
    if (candidate / "machine_control.py").exists() or get_manifest_field(integration_id, "machine_control"):
        detected_provides.add("machine_control")

    from app.services.integration_manifests import set_detected_provides

    set_detected_provides(integration_id, detected_provides)

    router_file = candidate / "router.py"
    if not router_file.exists():
        return None

    try:
        module = import_integration_module(integration_id, "router", router_file, is_external, source)
    except Exception:
        logger.exception("Failed to load integration %r - skipping", integration_id)
        return None

    router = getattr(module, "router", None)
    if router is None or not isinstance(router, APIRouter):
        logger.warning("Integration %r has no APIRouter named 'router' - skipping", integration_id)
        return None
    return router


def discover_integrations() -> list[tuple[str, APIRouter]]:
    """Discover and load all integrations. Returns [(integration_id, router)]."""
    results: list[tuple[str, APIRouter]] = []
    for candidate, integration_id, is_external, source in iter_integration_candidates():
        router = load_single_integration(candidate, integration_id, is_external, source)
        _loaded_ids.add(integration_id)
        if router is not None:
            results.append((integration_id, router))
    return results


def load_new_integrations(app) -> list[tuple[str, Path]]:
    """Discover integrations added since last discovery and register routers."""
    newly_loaded: list[tuple[str, Path]] = []
    for candidate, integration_id, is_external, source in iter_integration_candidates():
        if integration_id in _loaded_ids:
            continue

        logger.info("Hot-loading new integration: %s (from %s)", integration_id, candidate)
        router = load_single_integration(candidate, integration_id, is_external, source)
        _loaded_ids.add(integration_id)

        if router is not None:
            app.include_router(router, prefix=f"/integrations/{integration_id}")
        newly_loaded.append((integration_id, candidate))
    return newly_loaded


def discover_identity_fields() -> list[dict]:
    """Discover integration identity fields for user profile linking."""
    results: list[dict] = []
    for candidate, integration_id, is_external, source in iter_integration_candidates():
        config_file = candidate / "config.py"
        if not config_file.exists():
            continue
        try:
            module = import_integration_module(integration_id, "config", config_file, is_external, source)
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


# Compatibility aliases for old private imports.
_all_integration_dirs = all_integration_dirs
_import_module = import_integration_module
_iter_integration_candidates = iter_integration_candidates
_load_single_integration = load_single_integration
