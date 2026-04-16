"""Widget template engine — renders MCP tool results as interactive components.

Integrations declare `tool_widgets:` in their YAML, mapping tool names to
declarative component vocabulary templates. When an MCP tool returns raw JSON,
the engine checks for a matching template, substitutes variables from the
result data, and produces a ToolResultEnvelope.

Template syntax:
  - {{key}}          — simple key lookup from the parsed tool result JSON
  - {{a.b.c}}        — nested dot-path lookup
  - {{a[0].b}}       — array index + dot-path
  - {{a == 'x'}}     — equality expression → boolean
  - {{a | map: {label: name, value: id}}} — array map transform
"""
from __future__ import annotations

import copy
import json
import logging
import re
from typing import Any

from app.agent.tool_dispatch import ToolResultEnvelope

logger = logging.getLogger(__name__)

# Global map: tool_name → { content_type, display, template }
_widget_templates: dict[str, dict] = {}

# Template variable pattern — matches {{...}}
_VAR_PATTERN = re.compile(r"\{\{(.+?)\}\}")


def load_widget_templates_from_manifests() -> None:
    """Scan all integration manifests for tool_widgets and build the lookup map."""
    from app.services.integration_manifests import get_all_manifests

    _widget_templates.clear()
    count = 0

    for integration_id, manifest in get_all_manifests().items():
        tool_widgets = manifest.get("tool_widgets")
        if not tool_widgets or not isinstance(tool_widgets, dict):
            continue

        for tool_name, widget_def in tool_widgets.items():
            if not isinstance(widget_def, dict) or "template" not in widget_def:
                logger.warning(
                    "integration '%s': tool_widgets[%s] missing 'template', skipping",
                    integration_id, tool_name,
                )
                continue

            _widget_templates[tool_name] = {
                "content_type": widget_def.get("content_type", "application/vnd.spindrel.components+json"),
                "display": widget_def.get("display", "inline"),
                "template": widget_def["template"],
                "integration_id": integration_id,
            }
            count += 1

    if count:
        logger.info("Loaded %d widget templates from %d integrations",
                     count, len({t["integration_id"] for t in _widget_templates.values()}))


def get_widget_template(tool_name: str) -> dict | None:
    """Return the widget template for a tool name, or None."""
    return _widget_templates.get(tool_name)


def apply_widget_template(tool_name: str, raw_result: str) -> ToolResultEnvelope | None:
    """Apply a widget template to a raw tool result, returning an envelope or None.

    Returns None if no template exists or if the result can't be parsed as JSON.
    MCP tool names are often prefixed with the server name (e.g., "homeassistant-HassTurnOn"),
    so we try both the full name and the bare name (after stripping the server prefix).
    """
    tmpl = _widget_templates.get(tool_name)
    # Try stripping MCP server prefix: "server-ToolName" → "ToolName"
    if not tmpl and "-" in tool_name:
        bare_name = tool_name.split("-", 1)[1]
        tmpl = _widget_templates.get(bare_name)
    if not tmpl:
        return None

    # Parse the raw result as JSON for variable substitution
    try:
        data = json.loads(raw_result)
    except (json.JSONDecodeError, TypeError):
        logger.debug("Widget template for %s: result is not JSON, skipping", tool_name)
        return None

    if not isinstance(data, dict):
        logger.debug("Widget template for %s: result is not a dict, skipping", tool_name)
        return None

    # Deep-copy the template and substitute variables
    filled = _substitute(copy.deepcopy(tmpl["template"]), data)

    body = json.dumps(filled)
    plain_body = f"Widget: {tool_name}"

    return ToolResultEnvelope(
        content_type=tmpl["content_type"],
        body=body,
        plain_body=plain_body,
        display=tmpl["display"],
    )


# ── Variable substitution ──

def _substitute(obj: Any, data: dict) -> Any:
    """Recursively substitute {{...}} expressions in a template structure."""
    if isinstance(obj, str):
        return _substitute_string(obj, data)
    elif isinstance(obj, dict):
        return {k: _substitute(v, data) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_substitute(item, data) for item in obj]
    return obj


def _substitute_string(s: str, data: dict) -> Any:
    """Substitute {{...}} in a string.

    If the ENTIRE string is a single {{...}} expression, the result can be
    any type (bool, list, dict). If the string contains mixed text and
    expressions, the result is always a string.
    """
    # Fast path: entire string is a single expression
    m = _VAR_PATTERN.fullmatch(s.strip())
    if m:
        return _evaluate_expression(m.group(1).strip(), data)

    # Mixed content: substitute inline, convert results to strings
    def replacer(match: re.Match) -> str:
        result = _evaluate_expression(match.group(1).strip(), data)
        if isinstance(result, bool):
            return "true" if result else "false"
        return str(result)

    return _VAR_PATTERN.sub(replacer, s)


def _evaluate_expression(expr: str, data: dict) -> Any:
    """Evaluate a template expression.

    Supports:
      - key              → data["key"]
      - a.b.c            → data["a"]["b"]["c"]
      - a[0].b           → data["a"][0]["b"]
      - a == 'val'       → data["a"] == "val"  (returns bool)
      - a | map: {l: n}  → [{"l": item["n"]} for item in data["a"]]
    """
    # Pipe expressions: value | transform (preserve trailing whitespace in transforms
    # so separators like ", " in "join: , " aren't lost)
    if "|" in expr:
        parts = expr.split("|", 1)
        value = _resolve_path(parts[0].strip(), data)
        transform = parts[1].lstrip()  # only strip leading space, preserve trailing
        return _apply_transform(value, transform, data)

    # Equality expression: a == 'val' or a == "val"
    eq_match = re.match(r"(.+?)\s*==\s*['\"](.+?)['\"]", expr)
    if eq_match:
        left = _resolve_path(eq_match.group(1).strip(), data)
        right = eq_match.group(2)
        return left == right

    # Simple path lookup
    return _resolve_path(expr, data)


def _resolve_path(path: str, data: Any) -> Any:
    """Resolve a dot-path with optional array indices: a.b[0].c"""
    # Split on dots, handling array indices
    parts = re.split(r"\.(?![^\[]*\])", path)
    current = data

    for part in parts:
        if current is None:
            return None

        # Check for array index: key[0]
        idx_match = re.match(r"(.+?)\[(\d+)\]", part)
        if idx_match:
            key = idx_match.group(1)
            idx = int(idx_match.group(2))
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None
            if isinstance(current, list) and 0 <= idx < len(current):
                current = current[idx]
            else:
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None

    return current


def _apply_transform(value: Any, transform: str, data: dict) -> Any:
    """Apply a pipe transform to a value.

    Supported transforms:
      - map: {label: name, value: id}  → map each item to a new dict
      - pluck: key                      → extract a single field from each item
      - join: separator                 → join list items with separator (default ", ")
    """
    # Chained transforms: "pluck: name | join: , "
    # Split on " | " (with spaces) to preserve separators like ", " in join
    if " | " in transform:
        idx = transform.index(" | ")
        left = transform[:idx]
        right = transform[idx + 3:]  # skip " | "
        intermediate = _apply_transform(value, left.strip(), data)
        return _apply_transform(intermediate, right, data)

    # default: fallback_value — return fallback if value is None
    default_match = re.match(r"default:\s*(.*)", transform)
    if default_match:
        if value is None:
            fallback = default_match.group(1).strip()
            try:
                return int(fallback)
            except ValueError:
                try:
                    return float(fallback)
                except ValueError:
                    return fallback
        return value

    # join: separator
    join_match = re.match(r"join(?::\s*(.*))?", transform)
    if join_match and isinstance(value, list):
        sep = join_match.group(1) if join_match.group(1) is not None else ", "
        # Preserve the separator as-is (don't strip — ", " should stay ", ")
        return sep.join(str(item) for item in value if item)

    # pluck: key
    pluck_match = re.match(r"pluck:\s*(\w+)", transform)
    if pluck_match and isinstance(value, list):
        key = pluck_match.group(1)
        return [item.get(key, "") for item in value if isinstance(item, dict)]

    # map: {label: name, value: id}
    map_match = re.match(r"map:\s*\{(.+)\}", transform)
    if map_match and isinstance(value, list):
        mapping_str = map_match.group(1)
        mappings: dict[str, str] = {}
        for pair in mapping_str.split(","):
            pair = pair.strip()
            if ":" in pair:
                k, v = pair.split(":", 1)
                mappings[k.strip()] = v.strip()

        result = []
        for item in value:
            if isinstance(item, dict):
                mapped = {}
                for out_key, src_key in mappings.items():
                    mapped[out_key] = item.get(src_key, "")
                result.append(mapped)
        return result

    return value
