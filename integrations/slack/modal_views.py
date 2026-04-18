"""Schema ↔ Slack Block Kit view translator.

The ``open_modal`` tool emits a platform-agnostic schema; renderers
translate to native form primitives. This module handles Slack:

  schema = {
    "title_field": {
      "type": "text" | "textarea" | "select" | "url" | "number" | "date",
      "label": "Human label",
      "required": True,
      "choices": [{"label": "A", "value": "a"}, ...],  # for select
      "placeholder": "Optional hint",
    },
    ...
  }

We emit a Block Kit ``view`` object consumable by ``views.open`` /
``views.publish``. Each field becomes an ``input`` block with the
field id as the ``block_id``; the corresponding action_id is a stable
``_field`` suffix so the view-submission payload parser can find
values reliably.

Extraction (``values_from_view``) walks the submission state and
returns ``{field_id: value}``. Missing optional fields → absent from
the dict. Multi-select and date fields return their typed values.
"""
from __future__ import annotations

from typing import Any

_ACTION_SUFFIX = "_field"


def schema_to_view(
    *,
    callback_id: str,
    title: str,
    schema: dict,
    submit_label: str = "Submit",
    private_metadata: str = "",
) -> dict:
    """Render a Block Kit modal view from the platform-agnostic schema."""
    blocks: list[dict] = []
    for field_id, field_spec in schema.items():
        blocks.append(_field_to_block(field_id, field_spec))

    view: dict[str, Any] = {
        "type": "modal",
        "callback_id": callback_id,
        "title": {"type": "plain_text", "text": (title or "Form")[:24]},
        "submit": {"type": "plain_text", "text": submit_label[:24]},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }
    if private_metadata:
        view["private_metadata"] = private_metadata
    return view


def _field_to_block(field_id: str, spec: dict) -> dict:
    ftype = (spec.get("type") or "text").lower()
    label = spec.get("label") or field_id
    required = bool(spec.get("required"))
    placeholder = spec.get("placeholder") or ""

    element: dict[str, Any] = {"action_id": f"{field_id}{_ACTION_SUFFIX}"}

    if ftype == "textarea":
        element.update({"type": "plain_text_input", "multiline": True})
    elif ftype == "select":
        options = []
        for choice in spec.get("choices") or []:
            options.append({
                "text": {"type": "plain_text", "text": str(choice.get("label", "?"))[:75]},
                "value": str(choice.get("value", "")),
            })
        element.update({"type": "static_select", "options": options})
    elif ftype == "date":
        element.update({"type": "datepicker"})
    elif ftype == "url":
        element.update({"type": "url_text_input"})
    elif ftype == "number":
        element.update({"type": "number_input", "is_decimal_allowed": True})
    else:  # "text" and anything unknown
        element.update({"type": "plain_text_input"})

    if placeholder and element["type"] in (
        "plain_text_input", "url_text_input", "number_input", "static_select",
    ):
        element["placeholder"] = {"type": "plain_text", "text": placeholder[:150]}

    return {
        "type": "input",
        "block_id": field_id,
        "optional": not required,
        "label": {"type": "plain_text", "text": label[:200]},
        "element": element,
    }


def values_from_view(view: dict) -> dict:
    """Extract ``{field_id: value}`` from a submitted Slack view payload."""
    state = (view or {}).get("state") or {}
    values_state = state.get("values") or {}
    out: dict[str, Any] = {}
    for block_id, action_map in values_state.items():
        for action_id, payload in (action_map or {}).items():
            if not action_id.endswith(_ACTION_SUFFIX):
                continue
            out[block_id] = _extract_value(payload)
            break
    return out


def _extract_value(payload: dict) -> Any:
    """Pull the typed value out of a Slack view-submission field payload."""
    ptype = payload.get("type")
    if ptype in ("plain_text_input", "url_text_input"):
        return payload.get("value")
    if ptype == "number_input":
        raw = payload.get("value")
        if raw in (None, ""):
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return raw
    if ptype == "datepicker":
        return payload.get("selected_date")
    if ptype == "static_select":
        selected = payload.get("selected_option") or {}
        return selected.get("value")
    return payload.get("value")
