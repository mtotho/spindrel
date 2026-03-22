import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_tools: dict[str, dict[str, Any]] = {}

# Set by loader.py before importing each external tool file so @register picks up the source dir.
_current_load_source_dir: str | None = None
# Set by loader.py to the actual .py file path being imported.
_current_load_source_file: str | None = None
# Set by loader.py when importing integration tool files.
_current_source_integration: str | None = None


def register(schema: dict, *, source_dir: str | None = None):
    """Decorator that registers a local tool function with its OpenAI function schema."""

    def decorator(func: Callable):
        name = schema["function"]["name"]
        effective_source_dir = source_dir or _current_load_source_dir
        source_file = Path(_current_load_source_file).name if _current_load_source_file else None
        _tools[name] = {
            "function": func,
            "schema": schema,
            "source_dir": effective_source_dir,
            "source_integration": _current_source_integration,
            "source_file": source_file,
        }
        logger.info("Registered local tool: %s", name)
        return func

    return decorator


def iter_registered_tools() -> list[tuple[str, dict[str, Any], str | None, str | None, str | None]]:
    """Yields (tool_name, schema, source_dir, source_integration, source_file) for indexing."""
    out = []
    for name, entry in _tools.items():
        out.append((
            name,
            entry["schema"],
            entry.get("source_dir"),
            entry.get("source_integration"),
            entry.get("source_file"),
        ))
    return out


def get_local_tool_schemas(allowed_names: list[str] | None = None) -> list[dict]:
    if allowed_names is None or len(allowed_names) == 0:
        return []
    return [
        _tools[name]["schema"]
        for name in allowed_names
        if name in _tools
    ]


def is_local_tool(name: str) -> bool:
    return name in _tools


async def call_local_tool(name: str, arguments: str) -> str:
    entry = _tools.get(name)
    if entry is None:
        return json.dumps({"error": f"Unknown local tool: {name}"})
    try:
        args = json.loads(arguments) if arguments else {}
        t0 = time.monotonic()
        result = await entry["function"](**args)
        elapsed = time.monotonic() - t0
        logger.debug("Tool %s completed in %.1fms", name, elapsed * 1000)
        return result if isinstance(result, str) else json.dumps(result)
    except Exception as e:
        logger.exception("Error executing local tool %s", name)
        return json.dumps({"error": str(e)})
