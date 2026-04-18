"""Generic JSON → component-tree auto-renderer.

When a tool has no bespoke widget template, this module turns its raw JSON
result into a reasonable component tree so it can be pinned to the dashboard
as a card. Pin-only — not wired into chat rendering.

Output shape mirrors hand-authored templates like ``get_system_status``
(``app/tools/local/admin.widgets.yaml``):

  heading  (tool name, when provided)
  status   (summary pill — top-level collection counts, when derivable)
  properties layout=inline      (top-level scalars)
  section collapsible defaultOpen=True   (per nested field — first 2)
    → table       (homogeneous-object array)
    → properties  (nested scalar object)
  section collapsible defaultOpen=False  (remaining nested fields up to cap)
  section collapsible "+ N more sections"  (overflow wrapper)

Additional dispatch rules:
  - ``{<list>, count}`` idiom → count folded into section label
    (``"Poop Logs · 10"``), redundant ``Count`` row suppressed.
  - Homogeneous-object arrays one level deep → inline table (not JSON string).
  - Size caps and "N more …" truncation for deep / wide payloads.
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
_MAX_NESTED_SECTIONS = 5
_VALUE_DISPLAY_CAP = 200

# Whitelist of array-field names that count-pair with a scalar ``count``
# sibling (e.g. ``{logs: [...], count: 10}``). When matched, the generic
# builder folds the count into the section label and suppresses the redundant
# ``Count`` property row.
_COUNT_PAIR_LIST_KEYS = frozenset(
    {"items", "logs", "visits", "data", "results", "rows", "list", "entries"}
)


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
    components = _build_components(data, tool_name=tool_name)
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

def _build_components(data: Any, *, tool_name: str = "") -> list[dict]:
    """Top-level dispatch based on shape of the payload.

    For dict/list payloads, prepends a ``heading`` (tool name) and optional
    ``status`` summary pill, mirroring the shape of hand-authored widget
    templates like ``get_system_status``.
    """
    if data is None:
        return [{"type": "text", "content": "—", "style": "muted"}]

    if isinstance(data, (str, int, float, bool)):
        return [
            {
                "type": "properties",
                "items": [{"label": "Value", "value": _format_value(data)}],
            }
        ]

    header = _header_components(data, tool_name=tool_name)

    if isinstance(data, list):
        return header + _components_for_array(data, heading=None)

    if isinstance(data, dict):
        return header + _components_for_object(data)

    return header + [{"type": "code", "content": str(data), "language": "text"}]


def _header_components(data: Any, *, tool_name: str) -> list[dict]:
    """Produce the leading ``heading`` + optional ``status`` pill.

    - Heading is emitted only when ``tool_name`` is provided, to avoid
      inventing a "Result" title for payloads invoked without a tool context.
    - Status pill is emitted only when a meaningful summary can be derived
      (e.g. top-level collection counts). Otherwise omitted.
    """
    out: list[dict] = []
    if tool_name:
        out.append(
            {"type": "heading", "text": _humanize_key(tool_name), "level": 3}
        )
    summary = _summary_pill_text(data)
    if summary:
        out.append({"type": "status", "text": summary, "color": "success"})
    return out


def _summary_pill_text(data: Any) -> str | None:
    """Short one-liner describing a payload's headline counts."""
    if isinstance(data, list):
        return f"{len(data)} item{'s' if len(data) != 1 else ''}"

    if not isinstance(data, dict):
        return None

    # Prefer explicit ``{<list>, count}`` pair at the top level.
    array_segments: list[str] = []
    for key, value in data.items():
        if isinstance(value, list):
            array_segments.append(f"{len(value)} {_humanize_key(key).lower()}")
        elif isinstance(value, dict):
            pair = _extract_count_pair(value, key)
            if pair is not None:
                array_segments.append(
                    f"{pair[1]} {_humanize_key(pair[0]).lower()}"
                )

    if not array_segments:
        return None

    # Cap at 4 segments — any more and the pill becomes an eye chart.
    return " · ".join(array_segments[:4])


def _extract_count_pair(obj: dict, parent_key: str) -> tuple[str, int] | None:
    """Return ``(list_key, count)`` when ``obj`` matches the ``{<list>, count}``
    idiom (plus at most two scalar siblings). Returns None otherwise.

    The list key is drawn from :data:`_COUNT_PAIR_LIST_KEYS` to keep the
    pattern-match conservative. When matched, callers fold the count into the
    parent section's label.
    """
    if not isinstance(obj, dict) or "count" not in obj:
        return None
    count_val = obj.get("count")
    if not isinstance(count_val, int):
        return None

    list_key: str | None = None
    extra_scalars = 0
    for key, value in obj.items():
        if key == "count":
            continue
        if key in _COUNT_PAIR_LIST_KEYS and isinstance(value, list):
            if list_key is not None:
                # Ambiguous — two list candidates — bail.
                return None
            list_key = key
        elif _is_scalar(value):
            extra_scalars += 1
        else:
            return None

    if list_key is None or extra_scalars > 2:
        return None
    # Prefer the parent field name (e.g. "poopLogs") over the generic "logs"
    # key when it's more descriptive.
    display_key = parent_key if parent_key and parent_key != list_key else list_key
    return (display_key, count_val)


def _components_for_object(obj: dict) -> list[dict]:
    """Render an object as:
      - one ``properties`` block (``layout: inline``) for top-level scalars
      - a collapsible ``section`` per array / nested-object field
      - overflow beyond the cap wrapped in one collapsible "+ N more sections".
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
        capped = scalar_items[:_MAX_PROPERTIES_ROWS]
        components.append(
            {"type": "properties", "layout": "inline", "items": capped}
        )
        overflow = len(scalar_items) - len(capped)
        if overflow > 0:
            components.append(
                {
                    "type": "text",
                    "content": f"+ {overflow} more field{'s' if overflow != 1 else ''}",
                    "style": "muted",
                }
            )

    # Render nested fields as collapsible sections.
    visible = nested[:_MAX_NESTED_SECTIONS]
    overflow_nested = nested[_MAX_NESTED_SECTIONS:]

    for index, (key, value) in enumerate(visible):
        components.append(
            _section_for_nested_field(
                key, value, default_open=index < 2
            )
        )

    if overflow_nested:
        remaining = len(overflow_nested)
        overflow_children: list[dict] = []
        for key, value in overflow_nested:
            overflow_children.append(
                _section_for_nested_field(key, value, default_open=False)
            )
        components.append(
            {
                "type": "section",
                "collapsible": True,
                "defaultOpen": False,
                "label": f"+ {remaining} more section{'s' if remaining != 1 else ''}",
                "children": overflow_children,
            }
        )

    if not components:
        components.append(
            {"type": "text", "content": "Empty result", "style": "muted"}
        )

    return components


def _section_for_nested_field(
    key: str, value: Any, *, default_open: bool
) -> dict:
    """Build one collapsible section for a nested object/array field.

    Applies the ``{<list>, count}`` promotion when the shape matches: the
    count is folded into the section label (e.g. ``"Poop Logs · 10"``) and
    the redundant ``Count`` property row is suppressed.
    """
    label = _humanize_key(key)
    children: list[dict]

    if isinstance(value, dict):
        pair = _extract_count_pair(value, key)
        if pair is not None:
            _, count_val = pair
            label = f"{label} · {count_val}"
            children = _children_for_count_pair(value)
        else:
            children = _components_for_flat_object(value)
    elif isinstance(value, list):
        children = _components_for_array(value, heading=None)
    else:
        # Defensive — _components_for_object only pushes non-scalars here, but
        # guard against future refactors.
        children = [
            {
                "type": "properties",
                "layout": "inline",
                "items": [{"label": label, "value": _format_value(value)}],
            }
        ]

    return {
        "type": "section",
        "collapsible": True,
        "defaultOpen": default_open,
        "label": label,
        "children": children,
    }


def _children_for_count_pair(obj: dict) -> list[dict]:
    """Render a ``{<list>, count, [scalar siblings]}`` object as a table
    (plus optional scalar-siblings properties block above).

    The ``count`` key is suppressed — it's already in the section label.
    """
    list_value: list = []
    scalar_items: list[dict] = []
    for key, value in obj.items():
        if key == "count":
            continue
        if isinstance(value, list):
            list_value = value
        elif _is_scalar(value):
            scalar_items.append(
                {
                    "label": _humanize_key(key),
                    "value": _format_value(value),
                }
            )

    children: list[dict] = []
    if scalar_items:
        children.append(
            {"type": "properties", "layout": "inline", "items": scalar_items}
        )
    children.extend(_components_for_array(list_value, heading=None))
    return children


def _components_for_flat_object(obj: dict) -> list[dict]:
    """Render a nested object one level deep.

    Per-value dispatch:
      - scalars → batched into one ``properties`` block (inline)
      - homogeneous-object arrays → rendered as a ``table`` inline (biggest
        visual win: avoids the ugly truncated JSON-string-in-a-row fallback)
      - scalar arrays → existing ``[i]`` properties block
      - nested dicts → short JSON string via ``_format_value`` (we still
        only go one level deep — dicts-inside-dicts stay compact)
      - anything else → ``_format_value`` fallback
    """
    if not obj:
        return [{"type": "text", "content": "Empty", "style": "muted"}]

    scalar_items: list[dict] = []
    out: list[dict] = []

    def _flush_scalars() -> None:
        if not scalar_items:
            return
        capped = scalar_items[:_MAX_PROPERTIES_ROWS]
        out.append(
            {"type": "properties", "layout": "inline", "items": list(capped)}
        )
        overflow = len(scalar_items) - len(capped)
        if overflow:
            out.append(
                {
                    "type": "text",
                    "content": f"+ {overflow} more field{'s' if overflow != 1 else ''}",
                    "style": "muted",
                }
            )
        scalar_items.clear()

    for key, value in obj.items():
        if _is_scalar(value):
            scalar_items.append(
                {
                    "label": _humanize_key(key),
                    "value": _format_value(value),
                }
            )
            continue

        if isinstance(value, list) and value and all(
            isinstance(item, dict) for item in value
        ):
            # Homogeneous-object array — promote to a table inline with a
            # small label above it so multiple arrays in the same parent
            # stay distinguishable.
            _flush_scalars()
            out.append(
                {
                    "type": "heading",
                    "text": f"{_humanize_key(key)} · {len(value)}",
                    "level": 4,
                }
            )
            out.extend(_render_object_array(value))
            continue

        if isinstance(value, list) and all(_is_scalar(item) for item in value):
            _flush_scalars()
            capped = value[:_MAX_PROPERTIES_ROWS]
            out.append(
                {
                    "type": "properties",
                    "layout": "inline",
                    "items": [
                        {"label": f"{_humanize_key(key)}[{i}]", "value": _format_value(v)}
                        for i, v in enumerate(capped)
                    ],
                }
            )
            overflow = len(value) - len(capped)
            if overflow:
                out.append(
                    {
                        "type": "text",
                        "content": f"+ {overflow} more item{'s' if overflow != 1 else ''}",
                        "style": "muted",
                    }
                )
            continue

        # Fallback: nested dict or mixed array — render as one scalar row
        # with compact JSON. We do not recurse further.
        scalar_items.append(
            {
                "label": _humanize_key(key),
                "value": _format_value(value),
            }
        )

    _flush_scalars()
    if not out:
        return [{"type": "text", "content": "Empty", "style": "muted"}]
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
