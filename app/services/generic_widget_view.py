"""Generic JSON → component-tree auto-renderer.

When a tool has no bespoke widget template, this module turns its raw JSON
result into a reasonable component tree so it can be pinned to the dashboard
as a card. Pin-only — not wired into chat rendering.

Rules in priority order:
  1. Top-level scalars → `properties` component (key/value rows).
  2. Top-level homogeneous-object arrays → `table` (columns capped at 8).
  3. Top-level scalar arrays → `properties` list.
  4. One-level-nested objects → `heading` + `properties`.
  5. Size caps and "N more fields" truncation for deep / wide payloads.
"""
from __future__ import annotations

import json
from typing import Any

from app.agent.tool_dispatch import ToolResultEnvelope

# Content type every templated widget envelope uses. Generic view rides the
# same rendering path on the frontend (ComponentRenderer).
_COMPONENTS_CT = "application/vnd.spindrel.components+json"

# Serialized-size safety caps.
_BODY_CAP_BYTES = 50_000
_PLAIN_BODY_CAP = 200

# Auto-pick shape caps.
_MAX_TABLE_COLUMNS = 8
_MAX_TABLE_ROWS = 50
_MAX_PROPERTIES_ROWS = 20
_MAX_NESTED_SECTIONS = 3
_VALUE_DISPLAY_CAP = 200


def render_generic_view(
    raw_result: Any,
    *,
    tool_name: str = "",
    config: dict | None = None,
) -> ToolResultEnvelope:
    """Produce a `ToolResultEnvelope` from an arbitrary JSON tool result.

    ``config`` is reserved for future configurability (field selections,
    per-field labels / styles). v1 ignores it.
    """
    data = _coerce_json(raw_result)
    components = _build_components(data)
    body = json.dumps({"v": 1, "components": components})

    if len(body.encode("utf-8")) > _BODY_CAP_BYTES:
        components = [
            {
                "type": "status",
                "text": "Result too large to auto-render",
                "color": "warning",
            },
            {
                "type": "text",
                "content": "Pin was truncated. Author a widget template for rich rendering.",
                "style": "muted",
            },
        ]
        body = json.dumps({"v": 1, "components": components})

    plain = _plain_summary(data)

    return ToolResultEnvelope(
        content_type=_COMPONENTS_CT,
        body=body,
        plain_body=plain[:_PLAIN_BODY_CAP],
        display="inline",
        display_label=None,
        refreshable=False,
        tool_name=tool_name,
    )


# ── JSON coercion ──

def _coerce_json(raw: Any) -> Any:
    """Best-effort JSON normalization.

    Accepts raw strings (will try to parse), already-decoded dicts/lists,
    or primitives. Returns a plain Python structure; strings that fail to
    parse are returned as-is.
    """
    if isinstance(raw, (dict, list, int, float, bool)) or raw is None:
        return raw
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return None
        try:
            return json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            return raw
    return str(raw)


# ── Component building ──

def _build_components(data: Any) -> list[dict]:
    """Top-level dispatch based on shape of the payload."""
    if data is None:
        return [{"type": "text", "content": "—", "style": "muted"}]

    if isinstance(data, (str, int, float, bool)):
        return [
            {
                "type": "properties",
                "items": [{"label": "Value", "value": _format_value(data)}],
            }
        ]

    if isinstance(data, list):
        return _components_for_array(data, heading=None)

    if isinstance(data, dict):
        return _components_for_object(data)

    return [{"type": "code", "content": str(data), "language": "text"}]


def _components_for_object(obj: dict) -> list[dict]:
    """Render an object as:
      - one `properties` block for top-level scalars
      - followed by sections for each array/nested-object field (up to cap).
    """
    scalar_items: list[dict] = []
    nested: list[tuple[str, Any]] = []

    for key, value in obj.items():
        if _is_scalar(value):
            scalar_items.append(
                {
                    "label": _humanize_key(key),
                    "value": _format_value(value),
                }
            )
        else:
            nested.append((key, value))

    components: list[dict] = []

    if scalar_items:
        # Cap the rows; overflow is summarized.
        capped = scalar_items[:_MAX_PROPERTIES_ROWS]
        components.append({"type": "properties", "items": capped})
        overflow = len(scalar_items) - len(capped)
        if overflow > 0:
            components.append(
                {
                    "type": "text",
                    "content": f"+ {overflow} more field{'s' if overflow != 1 else ''}",
                    "style": "muted",
                }
            )

    # Render nested fields, capped.
    shown = 0
    for key, value in nested:
        if shown >= _MAX_NESTED_SECTIONS:
            break
        label = _humanize_key(key)
        if isinstance(value, list):
            components.append({"type": "heading", "text": label, "level": 3})
            components.extend(_components_for_array(value, heading=None))
        elif isinstance(value, dict):
            components.append({"type": "heading", "text": label, "level": 3})
            components.extend(_components_for_flat_object(value))
        shown += 1

    remaining = max(0, len(nested) - shown)
    if remaining:
        components.append(
            {
                "type": "text",
                "content": f"+ {remaining} more section{'s' if remaining != 1 else ''}",
                "style": "muted",
            }
        )

    if not components:
        components.append(
            {"type": "text", "content": "Empty result", "style": "muted"}
        )

    return components


def _components_for_flat_object(obj: dict) -> list[dict]:
    """Render a nested object as a single `properties` block.

    Deeply nested values (another dict / list) are serialized as short JSON
    rather than recursed — we only go one level deep to keep cards scannable.
    """
    items: list[dict] = []
    for key, value in obj.items():
        items.append(
            {
                "label": _humanize_key(key),
                "value": _format_value(value),
            }
        )
    if not items:
        return [{"type": "text", "content": "Empty", "style": "muted"}]
    capped = items[:_MAX_PROPERTIES_ROWS]
    out: list[dict] = [{"type": "properties", "items": capped}]
    overflow = len(items) - len(capped)
    if overflow:
        out.append(
            {
                "type": "text",
                "content": f"+ {overflow} more field{'s' if overflow != 1 else ''}",
                "style": "muted",
            }
        )
    return out


def _components_for_array(arr: list, *, heading: str | None) -> list[dict]:
    """Render an array based on homogeneity:
      - homogeneous dicts → `table`
      - scalars → `properties` with numeric labels
      - mixed → code dump (last resort).
    """
    components: list[dict] = []
    if heading:
        components.append({"type": "heading", "text": heading, "level": 3})

    if not arr:
        components.append({"type": "text", "content": "Empty list", "style": "muted"})
        return components

    if all(isinstance(item, dict) for item in arr):
        return components + _render_object_array(arr)

    if all(_is_scalar(item) for item in arr):
        capped = arr[:_MAX_PROPERTIES_ROWS]
        items = [
            {"label": f"[{i}]", "value": _format_value(v)}
            for i, v in enumerate(capped)
        ]
        components.append({"type": "properties", "items": items})
        overflow = len(arr) - len(capped)
        if overflow:
            components.append(
                {
                    "type": "text",
                    "content": f"+ {overflow} more item{'s' if overflow != 1 else ''}",
                    "style": "muted",
                }
            )
        return components

    # Heterogeneous — fall back to compact JSON.
    components.append(
        {
            "type": "code",
            "content": json.dumps(arr[:_MAX_TABLE_ROWS], indent=2)[:_BODY_CAP_BYTES // 4],
            "language": "json",
        }
    )
    return components


def _render_object_array(arr: list[dict]) -> list[dict]:
    """Render a list-of-objects as a table with union-of-keys columns."""
    seen_keys: list[str] = []
    seen = set()
    sample = arr[: max(_MAX_TABLE_ROWS, 20)]
    for item in sample:
        for key in item.keys():
            if key not in seen:
                seen.add(key)
                seen_keys.append(key)

    columns = seen_keys[:_MAX_TABLE_COLUMNS]
    if not columns:
        return [{"type": "text", "content": "Empty rows", "style": "muted"}]

    rows: list[list[str]] = []
    for item in arr[:_MAX_TABLE_ROWS]:
        rows.append([_format_value(item.get(col)) for col in columns])

    out: list[dict] = [
        {
            "type": "table",
            "columns": [_humanize_key(c) for c in columns],
            "rows": rows,
            "compact": True,
        }
    ]
    overflow = len(arr) - len(rows)
    if overflow > 0:
        out.append(
            {
                "type": "text",
                "content": f"+ {overflow} more row{'s' if overflow != 1 else ''}",
                "style": "muted",
            }
        )
    dropped_cols = len(seen_keys) - len(columns)
    if dropped_cols > 0:
        out.append(
            {
                "type": "text",
                "content": f"+ {dropped_cols} more column{'s' if dropped_cols != 1 else ''}",
                "style": "muted",
            }
        )
    return out


# ── Value / key formatting ──

def _is_scalar(v: Any) -> bool:
    return isinstance(v, (str, int, float, bool)) or v is None


def _format_value(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        if len(v) > _VALUE_DISPLAY_CAP:
            return v[:_VALUE_DISPLAY_CAP].rstrip() + "…"
        return v
    if isinstance(v, (dict, list)):
        try:
            compact = json.dumps(v, separators=(",", ":"))
        except (TypeError, ValueError):
            compact = str(v)
        if len(compact) > _VALUE_DISPLAY_CAP:
            return compact[:_VALUE_DISPLAY_CAP].rstrip() + "…"
        return compact
    return str(v)[:_VALUE_DISPLAY_CAP]


def _humanize_key(key: str) -> str:
    """`snake_case` or `camelCase` → `Title Case`."""
    if not key:
        return key
    # Split camelCase by inserting a space before caps.
    buf: list[str] = []
    for i, ch in enumerate(key):
        if i > 0 and ch.isupper() and key[i - 1].islower():
            buf.append(" ")
        buf.append(ch)
    spaced = "".join(buf).replace("_", " ").replace("-", " ")
    return " ".join(w.capitalize() if w.islower() else w for w in spaced.split())


def _plain_summary(data: Any) -> str:
    """Short textual summary used for `plain_body`."""
    if data is None:
        return "(empty result)"
    if isinstance(data, dict):
        n = len(data)
        return f"Object with {n} field{'s' if n != 1 else ''}"
    if isinstance(data, list):
        n = len(data)
        return f"List with {n} item{'s' if n != 1 else ''}"
    return str(data)[:_PLAIN_BODY_CAP]
