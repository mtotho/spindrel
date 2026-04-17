"""Dynamic loader for widget-package Python code stored in the DB.

Packages can bundle a YAML template with an optional Python module that
defines transform functions. The Python source is treated as one module,
compiled once per (package_id, version), and registered in ``sys.modules``
under a reserved namespace so the existing ``importlib.import_module``
path in widget_templates.py resolves ``self:foo`` refs naturally.

Trust model: the code executes in-process, unsandboxed, with full admin
privileges. Package authoring is admin-only and comparable to editing an
integration's Python source on disk.
"""
from __future__ import annotations

import logging
import sys
import types
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:  # pragma: no cover
    from types import ModuleType

logger = logging.getLogger(__name__)

# Reserved namespace — never collide with real packages.
_MODULE_PREFIX = "spindrel.widget_packages.pkg_"
_PREVIEW_PREFIX = "spindrel.widget_packages.preview_"

# Cache: package_id → loaded version. Lets us skip re-exec when unchanged.
_loaded_versions: dict[UUID, int] = {}


def module_name_for(package_id: UUID) -> str:
    """Canonical synthetic module name for a persisted package."""
    return f"{_MODULE_PREFIX}{package_id.hex}"


def load_package_module(
    package_id: UUID, version: int, code: str | None,
) -> "ModuleType | None":
    """Ensure the synthetic module for a package exists at the given version.

    Returns the module on success, None if ``code`` is empty (module is also
    removed from ``sys.modules`` in that case). Raises the underlying
    ``SyntaxError`` / exec-time exception so the caller can surface it.
    """
    mod_name = module_name_for(package_id)

    if code is None or not code.strip():
        _loaded_versions.pop(package_id, None)
        sys.modules.pop(mod_name, None)
        return None

    cached = _loaded_versions.get(package_id)
    if cached == version and mod_name in sys.modules:
        return sys.modules[mod_name]

    compiled = compile(code, f"<widget_package:{package_id}@v{version}>", "exec")
    module = types.ModuleType(mod_name)
    module.__file__ = f"<widget_package:{package_id}@v{version}>"
    module.__loader__ = None  # type: ignore[assignment]
    # Register before exec so intra-module self-imports (rare but valid) work.
    sys.modules[mod_name] = module
    try:
        exec(compiled, module.__dict__)
    except Exception:
        sys.modules.pop(mod_name, None)
        _loaded_versions.pop(package_id, None)
        raise

    _loaded_versions[package_id] = version
    return module


def invalidate(package_id: UUID) -> None:
    """Drop cached module state for a package (on delete or code clear)."""
    _loaded_versions.pop(package_id, None)
    sys.modules.pop(module_name_for(package_id), None)


def resolve_transform_ref(ref: str | None, package_id: UUID) -> str | None:
    """Rewrite ``self:func`` to the synthetic module path; pass other refs through.

    Called at registry-registration time, not per request.
    """
    if not ref or not isinstance(ref, str):
        return ref
    if ref.startswith("self:"):
        func = ref.split(":", 1)[1]
        return f"{module_name_for(package_id)}:{func}"
    return ref


def load_preview_module(code: str | None) -> tuple["ModuleType | None", str | None]:
    """Load a throwaway module for the preview endpoint.

    Returns (module, module_name). The caller is responsible for calling
    ``discard_preview_module`` after the preview request completes so that
    mid-edit code doesn't pollute ``sys.modules``.
    """
    if code is None or not code.strip():
        return None, None

    import uuid as _uuid
    mod_name = f"{_PREVIEW_PREFIX}{_uuid.uuid4().hex}"
    compiled = compile(code, f"<widget_package_preview:{mod_name}>", "exec")
    module = types.ModuleType(mod_name)
    module.__file__ = f"<widget_package_preview:{mod_name}>"
    module.__loader__ = None  # type: ignore[assignment]
    sys.modules[mod_name] = module
    try:
        exec(compiled, module.__dict__)
    except Exception:
        sys.modules.pop(mod_name, None)
        raise
    return module, mod_name


def discard_preview_module(mod_name: str | None) -> None:
    """Remove a preview module from ``sys.modules``."""
    if mod_name:
        sys.modules.pop(mod_name, None)


def rewrite_refs_for_preview(template_dict: dict, mod_name: str | None) -> dict:
    """Rewrite ``self:`` transform refs in a YAML-parsed widget def for preview.

    Mutates a deep copy of the dict so the caller keeps the original for DB writes.
    """
    import copy as _copy
    out = _copy.deepcopy(template_dict)

    def _rewrite_ref(ref: str) -> str:
        if isinstance(ref, str) and ref.startswith("self:"):
            func = ref.split(":", 1)[1]
            if mod_name is None:
                # Preview has no code — leave ref as-is; caller handles missing fn.
                return ref
            return f"{mod_name}:{func}"
        return ref

    if "transform" in out:
        out["transform"] = _rewrite_ref(out["transform"])
    state_poll = out.get("state_poll")
    if isinstance(state_poll, dict) and "transform" in state_poll:
        state_poll["transform"] = _rewrite_ref(state_poll["transform"])
    return out
