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


def _json_default(value: Any) -> str:
    return str(value)


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


def register(
    schema: dict,
    *,
    source_dir: str | None = None,
    safety_tier: str = "readonly",
    execution_policy: str = "normal",
    required_capabilities: "frozenset | None" = None,
    required_integrations: "frozenset[str] | None" = None,
    requires_bot_context: bool = False,
    requires_channel_context: bool = False,
    returns: dict | None = None,
):
    """Decorator that registers a local tool function with its OpenAI function schema.

    Args:
        schema: OpenAI function-call schema dict.
        source_dir: Override auto-detected source directory.
        safety_tier: One of 'readonly', 'mutating', 'exec_capable', 'control_plane'.
            Defaults to 'readonly' (safe by default).
        execution_policy: Additional runtime execution gate applied on top of
            tool policy. "normal" = no extra gate, "interactive_user" =
            requires a live JWT-authenticated user context, "live_target_lease"
            = requires an active session-bound machine-control lease.
        required_capabilities: Renderer capabilities that must be
            supported by at least one binding on a channel for this tool
            to be exposed to the LLM. Used by ``app/agent/context_
            assembly.py`` to filter the per-turn tool list — e.g.
            ``respond_privately`` declares ``{Capability.EPHEMERAL}`` so
            it never appears on a channel with no ephemeral-capable
            binding. None = unrestricted.
        required_integrations: Integration ids (e.g. ``"slack"``) that
            must be bound on a channel for this tool to be exposed.
            Slack-only surface tools (``slack_pin_message``,
            ``slack_add_bookmark``, ``slack_schedule_message``) use this
            to stay hidden on non-Slack channels rather than erroring at
            invocation time. None = unrestricted.
        returns: Optional JSON Schema describing the tool's return shape
            (the parsed-JSON structure of the string the tool returns).
            Surfaced via ``get_tool_info`` and ``list_tool_signatures``,
            and consumed by ``run_script`` to generate Python helper
            docstrings so a script can compose tool calls without
            guessing field names. Required for new readonly tools (lint
            pin in tests/unit/test_tool_returns_schema_coverage.py).
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
            "execution_policy": execution_policy,
            "required_capabilities": required_capabilities,
            "required_integrations": required_integrations,
            "requires_bot_context": requires_bot_context,
            "requires_channel_context": requires_channel_context,
            "returns": returns,
        }
        logger.info("Registered local tool: %s (tier=%s)", name, safety_tier)
        return func

    return decorator


def get_tool_returns_schema(name: str) -> dict | None:
    """Return the declared ``returns`` JSON Schema for a tool, or None if undeclared."""
    entry = _tools.get(name)
    return entry.get("returns") if entry else None


def get_tool_capability_requirements(name: str) -> tuple["frozenset | None", "frozenset[str] | None"]:
    """Return ``(required_capabilities, required_integrations)`` for a tool.

    Either component is ``None`` when the tool has no gating along that
    axis. Used by the context-assembly filter to drop tools the current
    channel's bindings cannot honor.
    """
    entry = _tools.get(name)
    if entry is None:
        return (None, None)
    return (
        entry.get("required_capabilities"),
        entry.get("required_integrations"),
    )


def get_tool_context_requirements(name: str) -> tuple[bool, bool]:
    """Return ``(requires_bot_context, requires_channel_context)`` for a tool.

    Both default False for unknown tools. Drives the dev-panel sandbox's
    pre-run validation and the dashboard refresh path's ContextVar setup —
    without these flags a tool that calls ``current_bot_id.get()`` returns
    ``"No bot context available."`` from any non-agent caller.
    """
    entry = _tools.get(name)
    if entry is None:
        return (False, False)
    return (
        bool(entry.get("requires_bot_context", False)),
        bool(entry.get("requires_channel_context", False)),
    )


def get_tool_safety_tier(name: str) -> str:
    """Return the safety tier of a registered tool, or 'unknown' if not found."""
    entry = _tools.get(name)
    return entry["safety_tier"] if entry else "unknown"


def get_tool_execution_policy(name: str) -> str:
    """Return the runtime execution policy for a registered tool."""
    entry = _tools.get(name)
    return str(entry.get("execution_policy") or "normal") if entry else "normal"


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
        return json.dumps({"error": f"Unknown local tool: {name}"}, ensure_ascii=False)
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
        return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=_json_default)
    except Exception as e:
        logger.exception("Error executing local tool %s", name)
        from app.security.prompt_sanitize import sanitize_exception
        return json.dumps({"error": sanitize_exception(e)}, ensure_ascii=False)
