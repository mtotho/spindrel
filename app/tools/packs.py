"""Tool packs: named groups derived from the registry by source module.

@tool-pack:knowledge expands to all tools from knowledge.py,
@tool-pack:memory to all tools from memory.py, etc.
Works for both built-in tools and externally-loaded tools from TOOL_DIRS.
"""
from __future__ import annotations


def get_tool_packs() -> dict[str, list[str]]:
    """Return pack_name → [tool_name, ...] grouped by the tool function's module.

    Pack name = last component of the module path, e.g.:
      app.tools.local.knowledge  →  "knowledge"
      my_custom_tools            →  "my_custom_tools"
    """
    from app.tools.registry import _tools
    packs: dict[str, list[str]] = {}
    for name, entry in _tools.items():
        module = getattr(entry.get("function"), "__module__", None) or ""
        pack_name = module.split(".")[-1] if module else ""
        if not pack_name or pack_name in ("__init__", "registry"):
            continue
        packs.setdefault(pack_name, []).append(name)
    return packs
