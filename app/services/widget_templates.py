"""Widget template engine — renders tool results as interactive components.

Integrations declare `tool_widgets:` in their YAML, and core tools use
co-located `*.widgets.yaml` files. When a tool returns JSON, the engine
checks for a matching template, substitutes variables from the result data,
and produces a ToolResultEnvelope.

Template syntax:
  - {{key}}          — simple key lookup from the parsed tool result JSON
  - {{a.b.c}}        — nested dot-path lookup
  - {{a[0].b}}       — array index + dot-path
  - {{a == 'x'}}     — equality expression → boolean
  - {{a | map: {label: name, value: id}}} — array map transform
  - {{a | in: x,y,z}} — membership test → boolean
  - {{a | not_empty}} — truthy test → boolean
  - {{a | status_color}} — map status strings to color names

Component-level features:
  - when: "{{expr}}"   — conditionally include/exclude a component
  - each: "{{array}}"  — iterate over an array to produce rows/items
    template: [...]     — template applied per item (use {{_.field}})

Code extensions:
  - transform: "module.path:function_name" — post-substitution Python hook
    receives (data: dict, components: list[dict]) → list[dict]
"""
from __future__ import annotations

import copy
import importlib
import json
import logging
import re
from pathlib import Path
from typing import Any

import yaml

from app.agent.tool_dispatch import ToolResultEnvelope

logger = logging.getLogger(__name__)

# Global map: tool_name → { content_type, display, template, transform? }
_widget_templates: dict[str, dict] = {}

# Template variable pattern — matches {{...}}
_VAR_PATTERN = re.compile(r"\{\{(.+?)\}\}")

# Status → color mapping (used by the status_color transform)
_STATUS_COLORS: dict[str, str] = {
    "active": "accent",
    "running": "info",
    "complete": "success",
    "completed": "success",
    "done": "success",
    "failed": "danger",
    "error": "danger",
    "cancelled": "muted",
    "canceled": "muted",
    "pending": "warning",
    "skipped": "muted",
    "open": "success",
    "closed": "muted",
    "merged": "accent",
}


# ── Template loading ──

def _register_widgets(source: str, widgets: dict) -> int:
    """Register tool_widgets from a source (integration ID, file path, etc.).

    Returns the number of templates registered. Later registrations do NOT
    override earlier ones — first-registered wins (integration > core).
    """
    count = 0
    for tool_name, widget_def in widgets.items():
        if not isinstance(widget_def, dict) or "template" not in widget_def:
            logger.warning(
                "%s: tool_widgets[%s] missing 'template', skipping",
                source, tool_name,
            )
            continue

        if tool_name in _widget_templates:
            logger.debug(
                "%s: tool_widgets[%s] already registered (from %s), skipping",
                source, tool_name, _widget_templates[tool_name].get("source", "?"),
            )
            continue

        _widget_templates[tool_name] = {
            "content_type": widget_def.get("content_type", "application/vnd.spindrel.components+json"),
            "display": widget_def.get("display", "inline"),
            "template": widget_def["template"],
            "transform": widget_def.get("transform"),
            "source": source,
        }
        count += 1
    return count


def load_widget_templates_from_manifests() -> None:
    """Load widget templates from all sources.

    Priority order (first-registered wins):
    1. Integration manifests (tool_widgets in integration.yaml)
    2. Core tool templates (*.widgets.yaml co-located with tool files)
    """
    from app.services.integration_manifests import get_all_manifests

    _widget_templates.clear()
    total = 0

    # 1. Integration manifests — highest priority
    for integration_id, manifest in get_all_manifests().items():
        tool_widgets = manifest.get("tool_widgets")
        if tool_widgets and isinstance(tool_widgets, dict):
            total += _register_widgets(f"integration:{integration_id}", tool_widgets)

    # 2. Core tool widget templates — co-located *.widgets.yaml
    core_dir = Path(__file__).parent.parent / "tools" / "local"
    if core_dir.is_dir():
        for yaml_path in sorted(core_dir.glob("*.widgets.yaml")):
            try:
                raw = yaml.safe_load(yaml_path.read_text())
                if isinstance(raw, dict):
                    total += _register_widgets(f"core:{yaml_path.stem}", raw)
            except Exception:
                logger.warning("Failed to load core widget template %s", yaml_path, exc_info=True)

    if total:
        logger.info("Loaded %d widget templates", total)


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

    # Apply code extension if declared
    transform_ref = tmpl.get("transform")
    if transform_ref and isinstance(filled, dict):
        components = filled.get("components")
        if isinstance(components, list):
            filled["components"] = _apply_code_transform(transform_ref, data, components)

    body = json.dumps(filled)
    plain_body = f"Widget: {tool_name}"

    return ToolResultEnvelope(
        content_type=tmpl["content_type"],
        body=body,
        plain_body=plain_body,
        display=tmpl["display"],
    )


# ── Code extension hook ──

def _apply_code_transform(ref: str, data: dict, components: list[dict]) -> list[dict]:
    """Call a Python transform function: 'module.path:function_name'.

    The function receives (data, components) and returns a modified components list.
    """
    try:
        module_path, func_name = ref.rsplit(":", 1)
        module = importlib.import_module(module_path)
        func = getattr(module, func_name)
        return func(data, components)
    except Exception:
        logger.warning("Widget transform '%s' failed, using template as-is", ref, exc_info=True)
        return components


# ── Variable substitution ──

def _substitute(obj: Any, data: dict) -> Any:
    """Recursively substitute {{...}} expressions in a template structure."""
    if isinstance(obj, str):
        return _substitute_string(obj, data)
    elif isinstance(obj, dict):
        # Handle `each:` expansion before recursing
        if "each" in obj and "template" in obj:
            return _expand_each(obj, data)
        return {k: _substitute(v, data) for k, v in obj.items() if k != "when"}
    elif isinstance(obj, list):
        # Filter items with `when:` conditionals, then substitute
        result = []
        for item in obj:
            if isinstance(item, dict) and "when" in item:
                condition = _substitute_string(item["when"], data) if isinstance(item["when"], str) else item["when"]
                if not _is_truthy(condition):
                    continue
            result.append(_substitute(item, data))
        return result
    return obj


def _is_truthy(value: Any) -> bool:
    """Determine if a value is truthy for `when:` conditionals."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value not in ("", "false", "False", "null", "None", "0")
    if isinstance(value, (list, dict)):
        return len(value) > 0
    if isinstance(value, (int, float)):
        return value != 0
    return True


def _expand_each(obj: dict, data: dict) -> Any:
    """Expand an `each:` directive into a list of items.

    ```yaml
    each: "{{items}}"
    template: ["{{_.name}}", "{{_.value}}"]
    ```

    Iterates over the resolved array, substituting `_` as the current item.
    """
    array_expr = obj["each"]
    template = obj["template"]

    # Resolve the array
    if isinstance(array_expr, str):
        array = _substitute_string(array_expr, data)
    else:
        array = array_expr

    if not isinstance(array, list):
        return []

    result = []
    for item in array:
        # Create a data overlay with `_` as the current item
        item_data = {**data, "_": item}
        row = _substitute(copy.deepcopy(template), item_data)
        result.append(row)
    return result


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
        if result is None:
            return ""
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
      - where: key=value                → filter list items
      - first                           → take first item from list
      - default: fallback               → use fallback if value is None
      - in: val1,val2,val3              → returns true if value is in the set
      - not_empty                       → returns true if value is truthy
      - status_color                    → map status string to a color name
      - count                           → return length of a list
    """
    # Chained transforms: "pluck: name | join: , "
    # Split on " | " (with spaces) to preserve separators like ", " in join
    if " | " in transform:
        idx = transform.index(" | ")
        left = transform[:idx]
        right = transform[idx + 3:]  # skip " | "
        intermediate = _apply_transform(value, left.strip(), data)
        return _apply_transform(intermediate, right, data)

    # in: val1,val2,val3 — membership test
    in_match = re.match(r"in:\s*(.+)", transform)
    if in_match:
        members = {m.strip() for m in in_match.group(1).split(",")}
        return str(value) in members if value is not None else False

    # not_empty — truthy test
    if transform.strip() == "not_empty":
        return _is_truthy(value)

    # status_color — map status strings to color names
    if transform.strip() == "status_color":
        if isinstance(value, str):
            return _STATUS_COLORS.get(value.lower(), "muted")
        return "muted"

    # count — length of a list
    if transform.strip() == "count":
        if isinstance(value, (list, dict)):
            return len(value)
        return 0

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

    # where: key=value — filter list items where item[key] == value
    where_match = re.match(r"where:\s*(\w+)\s*=\s*(.+)", transform)
    if where_match and isinstance(value, list):
        key = where_match.group(1)
        target = where_match.group(2).strip().strip("'\"")
        return [item for item in value if isinstance(item, dict) and item.get(key) == target]

    # first — take the first item from a list
    if transform.strip() == "first":
        if isinstance(value, list) and len(value) > 0:
            return value[0]
        return value

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
