"""Discover and import user tool modules from configured directories."""

import importlib.util
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _import_tool_file(path: Path) -> None:
    import app.tools.registry as _registry

    mod_name = f"_agent_tools_{path.stem}_{hash(path.parent) & 0xFFFF_FFFF:x}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        logger.warning("Could not load tool module spec from %s", path)
        return
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    _registry._current_load_source_dir = str(path.resolve().parent)
    _registry._current_load_source_file = str(path.resolve())
    try:
        spec.loader.exec_module(mod)
    except Exception:
        logger.exception("Failed to import tool file %s", path)
    finally:
        _registry._current_load_source_dir = None
        _registry._current_load_source_file = None


def _ensure_external_integration_importable(integration_dir: Path, integration_id: str) -> None:
    """Register an external integration's modules in sys.modules.

    External integrations live outside the in-repo ``integrations/`` package,
    so ``from integrations.{id}.config import settings`` would fail.  This
    pre-registers the integration directory as a package under
    ``integrations.{id}`` and file-imports any top-level .py modules (like
    ``config.py``) so that dotted imports resolve at tool-load time.
    """
    pkg_name = f"integrations.{integration_id}"
    if pkg_name in sys.modules:
        return

    # Register the directory itself as a package
    pkg_spec = importlib.util.spec_from_file_location(
        pkg_name,
        integration_dir / "__init__.py",
        submodule_search_locations=[str(integration_dir)],
    )
    if pkg_spec is None:
        # No __init__.py — create a namespace-style package
        import types
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(integration_dir)]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg
    else:
        pkg = importlib.util.module_from_spec(pkg_spec)
        sys.modules[pkg_name] = pkg
        try:
            pkg_spec.loader.exec_module(pkg)
        except Exception:
            logger.debug("Could not exec __init__.py for %s", pkg_name)

    # Pre-import top-level .py files (e.g. config.py) so dotted imports work
    for py_file in sorted(integration_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        mod_name = f"{pkg_name}.{py_file.stem}"
        if mod_name in sys.modules:
            continue
        spec = importlib.util.spec_from_file_location(mod_name, py_file)
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception:
            logger.debug("Could not pre-import %s for external integration %s", py_file.name, integration_id)


def _scan_integration_tools(base_dir: Path, *, is_external: bool = False) -> None:
    """Scan base_dir/*/tools/*.py for integration tools."""
    import app.tools.registry as _registry

    if not base_dir.is_dir():
        return
    for intg_tools_dir in sorted(base_dir.glob("*/tools")):
        if not intg_tools_dir.is_dir():
            continue
        integration_id = intg_tools_dir.parent.name
        # Skip globally disabled integrations
        try:
            from app.services.integration_settings import is_disabled
            if is_disabled(integration_id):
                logger.info("Skipping tools for disabled integration: %s", integration_id)
                continue
        except Exception:
            pass
        # External integrations need their modules registered for dotted imports
        if is_external:
            _ensure_external_integration_importable(intg_tools_dir.parent, integration_id)
        _registry._current_source_integration = integration_id
        try:
            for py_file in sorted(intg_tools_dir.glob("*.py")):
                if not py_file.name.startswith("_"):
                    _import_tool_file(py_file)
        finally:
            _registry._current_source_integration = None


def discover_and_load_tools(extra_dirs: list[Path] | None = None) -> None:
    """Import `*.py` from each directory (non-recursive). Underscore-prefixed files skipped.

    Also discovers tools from integrations/*/tools/*.py (in-repo and INTEGRATION_DIRS).
    """
    root = _project_root()
    dirs: list[Path] = [root / "tools"]
    if extra_dirs:
        dirs.extend(extra_dirs)

    for dir_path in dirs:
        if not dir_path.exists() or not dir_path.is_dir():
            continue
        for py_file in sorted(dir_path.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            _import_tool_file(py_file)

    # Auto-discover integrations/*/tools/*.py and packages/*/tools/*.py (in-repo)
    _scan_integration_tools(root / "integrations")
    _scan_integration_tools(root / "packages")

    # Auto-discover INTEGRATION_DIRS/*/tools/*.py (external)
    try:
        from app.config import settings
        extra = settings.INTEGRATION_DIRS
    except Exception:
        extra = ""
    if extra:
        for p in extra.split(":"):
            p = p.strip()
            if p:
                _scan_integration_tools(Path(p).expanduser().resolve(), is_external=True)


def load_integration_tools(integration_dir: Path) -> list[str]:
    """Load tools from a single integration directory.

    Scans {integration_dir}/tools/*.py, imports each via _import_tool_file().
    Returns list of newly registered tool names.
    """
    import app.tools.registry as _registry

    tools_dir = integration_dir / "tools"
    if not tools_dir.is_dir():
        return []

    # Check if this is an external integration (not under integrations/ or packages/)
    root = _project_root()
    is_external = not (
        str(integration_dir.resolve()).startswith(str(root / "integrations"))
        or str(integration_dir.resolve()).startswith(str(root / "packages"))
    )
    if is_external:
        _ensure_external_integration_importable(integration_dir, integration_dir.name)

    before = set(_registry._tools.keys())
    integration_id = integration_dir.name
    _registry._current_source_integration = integration_id
    try:
        for py_file in sorted(tools_dir.glob("*.py")):
            if not py_file.name.startswith("_"):
                _import_tool_file(py_file)
    finally:
        _registry._current_source_integration = None

    return list(set(_registry._tools.keys()) - before)
