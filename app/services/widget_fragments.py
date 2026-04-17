"""Fragment resolution for widget templates.

A widget definition can declare ``fragments:`` — named component bodies
that are inlined wherever ``{type: fragment, ref: <name>}`` appears.
Resolution runs once at registration time; the expanded template is
what gets cached in ``_widget_templates``, so runtime substitution is
unchanged.

The key win is retiring the ``template:`` / ``state_poll.template:``
duplication that every refreshable widget pays today. A fragment
referenced in both positions is authored once and rendered twice.

Grammar
-------

Fragment body can be a single component dict or a list of components.
Lists spread at the parent list position; dicts replace 1:1::

    fragments:
      task_props:                       # list body — spreads
        - type: heading
          text: "{{title}}"
        - type: status
          text: "{{status}}"
      header:                           # dict body — replaces 1:1
        type: heading
        text: "{{title}}"
        level: 3

    template:
      v: 1
      components:
        - {type: fragment, ref: header}
        - {type: fragment, ref: task_props}

Resolution is recursive — a fragment may reference other fragments — and
cycle-protected. A ``list`` body referenced in a scalar position (e.g.
``children: {type: fragment, ref: multi_node_frag}``) is an error.
"""
from __future__ import annotations

import copy
from typing import Any


def resolve_fragments(widget_def: dict) -> tuple[dict, list[str]]:
    """Return ``(resolved_def, errors)``.

    - Expands every ``{type: fragment, ref: <name>}`` node against
      ``widget_def["fragments"]``.
    - Resolves inside ``template.components`` and
      ``state_poll.template.components`` (the positions that end up on
      screen). Doesn't touch siblings like ``default_config`` or
      ``display_label`` — fragments are a component-tree construct.
    - Strips the top-level ``fragments:`` key from the returned dict
      (there's no reason to keep it after expansion).
    - Returns the original dict unchanged when no ``fragments:`` key is
      present *and* the template contains no fragment refs. Otherwise we
      walk the tree so unknown refs are caught even without an explicit
      ``fragments:`` block.
    """
    fragments_raw = widget_def.get("fragments")
    if fragments_raw is not None and not isinstance(fragments_raw, dict):
        return widget_def, ["fragments: must be a mapping"]
    fragments: dict = fragments_raw if isinstance(fragments_raw, dict) else {}

    if not fragments and not _contains_fragment_ref(widget_def):
        return widget_def, []

    errors: list[str] = []
    resolved = copy.deepcopy(widget_def)

    template = resolved.get("template")
    if isinstance(template, dict) and isinstance(template.get("components"), list):
        template["components"] = _resolve_list(
            template["components"], fragments, errors, seen=set(),
        )

    state_poll = resolved.get("state_poll")
    if isinstance(state_poll, dict):
        sp_template = state_poll.get("template")
        if isinstance(sp_template, dict) and isinstance(sp_template.get("components"), list):
            sp_template["components"] = _resolve_list(
                sp_template["components"], fragments, errors, seen=set(),
            )

    resolved.pop("fragments", None)
    return resolved, errors


def _contains_fragment_ref(obj: Any) -> bool:
    """Cheap pre-walk — avoids a full deepcopy when there's no work."""
    if isinstance(obj, dict):
        if obj.get("type") == "fragment":
            return True
        return any(_contains_fragment_ref(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_contains_fragment_ref(x) for x in obj)
    return False


def _resolve_list(
    items: list, fragments: dict, errors: list[str], seen: set[str],
) -> list:
    """Walk a list; expand list-bodied fragments via spread, dict-bodied 1:1."""
    out: list[Any] = []
    for item in items:
        if isinstance(item, dict) and item.get("type") == "fragment":
            resolved = _expand_ref(item, fragments, errors, seen)
            if isinstance(resolved, list):
                out.extend(resolved)
            elif resolved is not None:
                out.append(resolved)
        elif isinstance(item, dict):
            out.append(_resolve_dict(item, fragments, errors, seen))
        elif isinstance(item, list):
            out.append(_resolve_list(item, fragments, errors, seen))
        else:
            out.append(item)
    return out


def _resolve_dict(
    node: dict, fragments: dict, errors: list[str], seen: set[str],
) -> dict:
    """Walk a dict's values, recursing into nested dicts/lists."""
    out: dict[str, Any] = {}
    for k, v in node.items():
        if isinstance(v, dict):
            if v.get("type") == "fragment":
                resolved = _expand_ref(v, fragments, errors, seen)
                if isinstance(resolved, list):
                    errors.append(
                        f"fragment {v.get('ref')!r} has a list body but was "
                        f"referenced at '{k}:' — that position needs a single node",
                    )
                    continue
                if resolved is not None:
                    out[k] = resolved
            else:
                out[k] = _resolve_dict(v, fragments, errors, seen)
        elif isinstance(v, list):
            out[k] = _resolve_list(v, fragments, errors, seen)
        else:
            out[k] = v
    return out


def _expand_ref(
    node: dict, fragments: dict, errors: list[str], seen: set[str],
) -> Any:
    """Look up a fragment ref and recursively resolve its body."""
    ref = node.get("ref")
    if not isinstance(ref, str) or not ref:
        errors.append("fragment ref must be a non-empty string")
        return None
    if ref in seen:
        errors.append(f"fragment cycle detected through {ref!r}")
        return None
    if ref not in fragments:
        errors.append(f"unknown fragment ref: {ref!r}")
        return None

    body = copy.deepcopy(fragments[ref])
    next_seen = seen | {ref}

    if isinstance(body, list):
        return _resolve_list(body, fragments, errors, next_seen)
    if isinstance(body, dict):
        return _resolve_dict(body, fragments, errors, next_seen)

    errors.append(f"fragment {ref!r} body must be a mapping or list")
    return None
