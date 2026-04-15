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


def get_settings():
    """Create a settings reader for the current integration. Call at module level.

    Automatically detects which integration the tool belongs to — no manual ID needed.
    Returns a function: setting(key, default="") -> str that reads from
    DB (admin UI) first, then falls back to os.environ.

    Usage::

        from app.tools.registry import register, get_settings

        setting = get_settings()

        @register({...})
        async def my_tool() -> str:
            api_key = setting("MY_API_KEY")
            ...
    """
    import os
    integration_id = _current_source_integration

    if not integration_id:
        # Not inside an integration — just read env vars
        return lambda key, default="": os.environ.get(key, default)

    def _get(key: str, default: str = "") -> str:
        try:
            from app.services.integration_settings import get_value
            return get_value(integration_id, key, default)
        except ImportError:
            return os.environ.get(key, default)

    return _get


def register(schema: dict, *, source_dir: str | None = None, safety_tier: str = "readonly"):
    """Decorator that registers a local tool function with its OpenAI function schema.

    Args:
        schema: OpenAI function-call schema dict.
        source_dir: Override auto-detected source directory.
        safety_tier: One of 'readonly', 'mutating', 'exec_capable', 'control_plane'.
            Defaults to 'readonly' (safe by default).
    """

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
            "safety_tier": safety_tier,
        }
        logger.info("Registered local tool: %s (tier=%s)", name, safety_tier)
        return func

    return decorator


def get_tool_safety_tier(name: str) -> str:
    """Return the safety tier of a registered tool, or 'unknown' if not found."""
    entry = _tools.get(name)
    return entry["safety_tier"] if entry else "unknown"


def get_all_tool_tiers() -> dict[str, str]:
    """Return a dict mapping tool name → safety tier for all registered tools."""
    return {name: entry.get("safety_tier", "readonly") for name, entry in _tools.items()}


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


def unregister_integration_tools(integration_id: str) -> list[str]:
    """Remove all tools belonging to an integration. Returns removed tool names."""
    to_remove = [
        name for name, entry in _tools.items()
        if entry.get("source_integration") == integration_id
    ]
    for name in to_remove:
        del _tools[name]
        logger.info("Unregistered tool %s (integration %s disabled)", name, integration_id)
    return to_remove


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


def _coerce_args(args: dict, schema_props: dict) -> dict:
    """Fix common LLM type mistakes based on declared schema.

    Handles:
    - scalar value passed for an array parameter → wrap in list
    - string value passed for an integer parameter → int()
    - string value passed for a number parameter → float()
    - string "true"/"false" passed for a boolean parameter → bool
    """
    for key, val in args.items():
        prop = schema_props.get(key)
        if prop is None or val is None:
            continue
        declared = prop.get("type")
        if declared == "array" and not isinstance(val, list):
            args[key] = [val]
        elif declared == "integer" and isinstance(val, str):
            try:
                args[key] = int(val)
            except (ValueError, TypeError):
                pass
        elif declared == "number" and isinstance(val, str):
            try:
                args[key] = float(val)
            except (ValueError, TypeError):
                pass
        elif declared == "boolean" and isinstance(val, str):
            args[key] = val.lower() in ("true", "1", "yes")
    return args


async def call_local_tool(name: str, arguments: str) -> str:
    entry = _tools.get(name)
    if entry is None:
        return json.dumps({"error": f"Unknown local tool: {name}"})
    try:
        args = {}
        if arguments:
            try:
                args = json.loads(arguments)
            except (json.JSONDecodeError, ValueError):
                # Model sent bare string instead of JSON object — recover if
                # the tool has exactly one required string parameter.
                params = (
                    entry.get("schema", {})
                    .get("function", {})
                    .get("parameters", {})
                )
                props = params.get("properties", {})
                required = params.get("required", [])
                str_params = [
                    k for k, v in props.items()
                    if v.get("type") == "string"
                ]
                if len(str_params) == 1 and str_params[0] in required:
                    args = {str_params[0]: arguments}
                else:
                    raise
        # Coerce args based on declared schema (e.g. string → list for array params)
        schema_props = (
            entry.get("schema", {})
            .get("function", {})
            .get("parameters", {})
            .get("properties", {})
        )
        if schema_props:
            _coerce_args(args, schema_props)
        t0 = time.monotonic()
        result = await entry["function"](**args)
        elapsed = time.monotonic() - t0
        logger.debug("Tool %s completed in %.1fms", name, elapsed * 1000)
        return result if isinstance(result, str) else json.dumps(result)
    except Exception as e:
        logger.exception("Error executing local tool %s", name)
        from app.security.prompt_sanitize import sanitize_exception
        return json.dumps({"error": sanitize_exception(e)})
