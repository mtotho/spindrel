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


def _scan_integration_tools(base_dir: Path) -> None:
    """Scan base_dir/*/tools/*.py for integration tools."""
    import app.tools.registry as _registry

    if not base_dir.is_dir():
        return
    for intg_tools_dir in sorted(base_dir.glob("*/tools")):
        if not intg_tools_dir.is_dir():
            continue
        integration_id = intg_tools_dir.parent.name
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

    # Auto-discover integrations/*/tools/*.py (in-repo)
    _scan_integration_tools(root / "integrations")

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
                _scan_integration_tools(Path(p).expanduser().resolve())
