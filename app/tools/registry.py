import json
import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

_tools: dict[str, dict[str, Any]] = {}

# Set by loader.py before importing each external tool file so @register picks up the source dir.
_current_load_source_dir: str | None = None


def register(schema: dict, *, source_dir: str | None = None):
    """Decorator that registers a local tool function with its OpenAI function schema."""

    def decorator(func: Callable):
        name = schema["function"]["name"]
        effective_source_dir = source_dir or _current_load_source_dir
        _tools[name] = {"function": func, "schema": schema, "source_dir": effective_source_dir}
        logger.info("Registered local tool: %s", name)
        return func

    return decorator


def iter_registered_tools() -> list[tuple[str, dict[str, Any], str | None]]:
    """(tool_name, openai_tool_schema_dict, source_dir_or_none) for indexing."""
    out: list[tuple[str, dict[str, Any], str | None]] = []
    for name, entry in _tools.items():
        out.append((name, entry["schema"], entry.get("source_dir")))
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
