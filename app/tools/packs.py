"""Tool packs: named groups derived from the registry by source module.

@tool-pack:knowledge expands to all tools from knowledge.py,
@tool-pack:memory to all tools from memory.py, etc.
Works for both built-in tools and externally-loaded tools from TOOL_DIRS.
"""
from __future__ import annotations


def get_tool_packs() -> dict[str, list[str]]:
    """Return pack_name → [tool_name, ...] grouped by source file.

    Pack name = source filename without .py extension, e.g.:
      heartbeat_tools.py  →  "heartbeat_tools"
      knowledge.py        →  "knowledge"
    Falls back to last component of __module__ for tools without source_file.
    """
    from app.tools.registry import _tools
    packs: dict[str, list[str]] = {}
    for name, entry in _tools.items():
        source_file = entry.get("source_file") or ""
        if source_file:
            pack_name = source_file.removesuffix(".py")
        else:
            module = getattr(entry.get("function"), "__module__", None) or ""
            pack_name = module.split(".")[-1] if module else ""
        if not pack_name or pack_name in ("__init__", "registry"):
            continue
        packs.setdefault(pack_name, []).append(name)
    return packs
