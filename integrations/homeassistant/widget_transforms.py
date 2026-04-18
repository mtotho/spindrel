"""Widget state poll transforms for Home Assistant.

GetLiveContext returns a JSON wrapper with YAML-formatted text listing all
exposed entities:

    {"success": true, "result": "Live Context: ...\\n- names: Office Desk LED Strip\\n  domain: light\\n  state: 'on'\\n  attributes:\\n    brightness: '255'\\n- names: ..."}

The ``entity_state`` transform extracts a single entity by display_label and
returns a flat dict the state_poll template can render.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)


def entity_state(raw_result: str, widget_meta: dict) -> dict:
    """Extract a single entity's state from GetLiveContext output.

    Returns a dict like::

        {
            "entity_name": "Office Desk LED Strip",
            "domain": "light",
            "state": "on",
            "is_on": True,
            "brightness": 69,
        }
    """
    display_label = (widget_meta.get("display_label") or "").strip()
    if not display_label:
        return {}

    # Parse the JSON wrapper
    try:
        parsed = json.loads(raw_result)
    except (json.JSONDecodeError, TypeError):
        logger.debug("entity_state: raw_result is not JSON")
        return {}

    result_text = parsed.get("result", "")
    if not isinstance(result_text, str):
        return {}

    # Parse the YAML-like entity list from GetLiveContext
    # Format: "- names: Foo\n  domain: light\n  state: 'on'\n  attributes:\n    brightness: '69'"
    entities = _parse_live_context(result_text)

    # The slider should only render on pins created from HassLightSet — the
    # turn-on/turn-off pins use the same shared template but don't expose
    # brightness. tool_name carries the MCP server prefix (e.g.
    # "homeassistant-HassLightSet"), so check via substring.
    pin_tool_name = widget_meta.get("tool_name") or ""
    is_light_set_pin = "HassLightSet" in pin_tool_name

    # Find matching entity (case-insensitive)
    target = display_label.lower()
    for entity in entities:
        if entity.get("name", "").lower() == target:
            state = entity.get("state", "unknown")
            is_on = state.lower() in ("on", "open", "playing", "home", "active")
            brightness_raw = entity.get("attributes", {}).get("brightness")
            brightness = _parse_brightness(brightness_raw) if brightness_raw else (100 if is_on else 0)

            return {
                "entity_name": entity.get("name", display_label),
                "domain": entity.get("domain", ""),
                "state": state,
                "is_on": is_on,
                "is_off": not is_on,
                "brightness": brightness,
                "show_brightness": is_on and is_light_set_pin,
            }

    logger.debug("entity_state: entity '%s' not found in %d entities", display_label, len(entities))
    return {}


_ON_STATES = ("on", "open", "playing", "home", "active", "unlocked", "heat", "cool")


def _unwrap(raw_result: str) -> dict:
    """Best-effort JSON parse of an MCP tool result string.

    Returns an empty dict if the input isn't a JSON string.
    """
    try:
        parsed = json.loads(raw_result)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _format_display_value(state: str, unit: str | None) -> str:
    """Format a sensor state + unit for a single-line status chip.

    Numeric values with a ``°`` unit get no separator (``75.3°F``); other
    units get a space (``100 %``). Non-numeric states just echo the state.
    """
    if state in (None, "", "unknown", "unavailable"):
        return state or ""
    if not unit:
        return str(state)
    try:
        float(state)
    except (TypeError, ValueError):
        return str(state)
    if unit.startswith("°") or unit == "%":
        sep = "" if unit.startswith("°") else " "
        return f"{state}{sep}{unit}"
    return f"{state} {unit}"


def single_entity_state(raw_result: str, widget_meta: dict) -> dict:
    """Transform ha_get_state result into flat template vars.

    Expected input shape::

        {"data": {"entity_id": "sensor.kitchen_temperature_temperature",
                  "state": "75.344",
                  "attributes": {"friendly_name": "Kitchen Temperature Temperature",
                                 "unit_of_measurement": "°F",
                                 "device_class": "temperature"},
                  "last_changed": "2026-04-18T03:15:51.821593+00:00"}}
    """
    parsed = _unwrap(raw_result)
    entity = parsed.get("data") or {}
    if not isinstance(entity, dict) or not entity.get("entity_id"):
        return {}

    entity_id = entity.get("entity_id") or ""
    state = entity.get("state", "")
    attrs = entity.get("attributes") or {}
    friendly = attrs.get("friendly_name") or entity_id
    unit = attrs.get("unit_of_measurement") or ""
    domain = entity_id.split(".", 1)[0] if entity_id else ""
    is_on = str(state).lower() in _ON_STATES

    return {
        "entity_id": entity_id,
        "state": state,
        "friendly_name": friendly,
        "unit": unit,
        "device_class": attrs.get("device_class") or "",
        "domain": domain,
        "last_changed": entity.get("last_changed") or "",
        "is_on": is_on,
        "is_off": not is_on,
        "display_value": _format_display_value(state, unit),
    }


def live_context_summary(data: dict, components: list[dict]) -> list[dict]:
    """Main-template transform for homeassistant-GetLiveContext.

    The raw result is a YAML blob nested inside the JSON wrapper's
    ``result`` string — no template dot-path can reach per-entity fields.
    So we parse it here and rebuild the component tree with computed
    counts, an "active now" section, and a filter UI driven by
    ``config.filter``.

    Filter semantics: a case-insensitive substring match against entity
    name / domain / area. Set via preset buttons (one per discovered
    area + domain) that dispatch ``widget_config`` — only functional on
    pinned cards, same constraint as other ``widget_config`` actions.

    Signature matches the top-level ``transform`` contract in
    ``app/services/widget_templates.py:_apply_code_transform``.
    """
    result_text = data.get("result")
    if not isinstance(result_text, str):
        return components

    entities = [
        e for e in _parse_live_context(result_text)
        if e.get("domain") and e.get("state")
    ]

    cfg = data.get("config") if isinstance(data.get("config"), dict) else {}
    raw_filter = str(cfg.get("filter", "") or "").strip()
    filter_lc = raw_filter.lower()

    # Derive the unique area + domain sets from the FULL entity list (not
    # the filtered one) so filter buttons stay visible/stable as the user
    # narrows.
    all_areas = sorted({e.get("area") for e in entities if e.get("area")})
    all_domains = sorted({e.get("domain") for e in entities if e.get("domain")})

    if filter_lc:
        matching = [
            e for e in entities
            if filter_lc in (e.get("name", "").lower())
            or filter_lc in (e.get("domain", "").lower())
            or filter_lc in (e.get("area", "").lower())
        ]
    else:
        matching = entities

    active = [
        {
            "label": e.get("name", ""),
            "value": e.get("state", ""),
            "caption": e.get("area") or e.get("domain", ""),
        }
        for e in matching
        if str(e.get("state", "")).lower() in _ON_STATES
    ]

    domain_tallies: dict[str, int] = {}
    for e in matching:
        d = e.get("domain", "") or "unknown"
        domain_tallies[d] = domain_tallies.get(d, 0) + 1
    domain_counts = [
        {"label": d, "value": str(count)}
        for d, count in sorted(domain_tallies.items(), key=lambda kv: -kv[1])
    ]

    total = len(entities)
    shown = len(matching)

    new_components: list[dict] = []

    if filter_lc:
        new_components.append({
            "type": "status",
            "text": f"Filtered: {raw_filter} · {shown}/{total} entities",
            "color": "accent",
        })
        new_components.append({
            "type": "button",
            "label": "Clear filter",
            "subtle": True,
            "action": {
                "dispatch": "widget_config",
                "config": {"filter": ""},
            },
        })
    else:
        new_components.append({
            "type": "status",
            "text": f"{total} entities · {len(active)} active",
            "color": "info",
        })

    if domain_counts:
        new_components.append({
            "type": "tiles",
            "min_width": 140,
            "items": domain_counts,
        })

    if active:
        new_components.append({
            "type": "section",
            "label": f"Active now ({len(active)})",
            "collapsible": True,
            "defaultOpen": False,
            "children": [
                {"type": "tiles", "min_width": 180, "items": active},
            ],
        })

    # Filter presets — one button per area, one per domain. Invisible
    # once the filter is set (user can pick a different one after
    # clearing). Only functional on pinned cards, matching the
    # widget_config dispatch contract.
    if not filter_lc and (all_areas or all_domains):
        area_buttons = [
            {
                "type": "button",
                "label": area,
                "subtle": True,
                "action": {
                    "dispatch": "widget_config",
                    "config": {"filter": area},
                },
            }
            for area in all_areas
        ]
        domain_buttons = [
            {
                "type": "button",
                "label": domain,
                "subtle": True,
                "action": {
                    "dispatch": "widget_config",
                    "config": {"filter": domain},
                },
            }
            for domain in all_domains
        ]

        filter_section_children: list[dict] = []
        if area_buttons:
            filter_section_children.append({
                "type": "properties",
                "layout": "inline",
                "items": [{"label": "By area", "value": ""}],
            })
            filter_section_children.extend(area_buttons)
        if domain_buttons:
            filter_section_children.append({
                "type": "properties",
                "layout": "inline",
                "items": [{"label": "By domain", "value": ""}],
            })
            filter_section_children.extend(domain_buttons)

        new_components.append({
            "type": "section",
            "label": "Filter",
            "collapsible": True,
            "defaultOpen": False,
            "children": filter_section_children,
        })

    return new_components


def _parse_brightness(raw: str | int | float) -> int:
    """Convert HA brightness (0-255 or 0-100 string) to percentage 0-100."""
    try:
        val = int(str(raw).strip("'\""))
    except (ValueError, TypeError):
        return 100

    # HA native brightness is 0-255; if > 100, convert to percentage
    if val > 100:
        return round(val * 100 / 255)
    return val


def _parse_live_context(text: str) -> list[dict]:
    """Parse the YAML-like entity list from GetLiveContext.

    Each entity block starts with "- names:" and contains domain, state,
    and optional attributes.
    """
    entities: list[dict] = []

    # Split on entity boundaries
    blocks = re.split(r"(?m)^- names?:\s*", text)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        entity: dict = {"attributes": {}}

        lines = block.split("\n")
        # First line is the entity name
        entity["name"] = lines[0].strip().strip("'\"")

        in_attributes = False
        for line in lines[1:]:
            stripped = line.strip()
            if not stripped or stripped.startswith("- names"):
                break

            if stripped.startswith("domain:"):
                entity["domain"] = stripped.split(":", 1)[1].strip().strip("'\"")
                in_attributes = False
            elif stripped.startswith("state:"):
                entity["state"] = stripped.split(":", 1)[1].strip().strip("'\"")
                in_attributes = False
            elif stripped.startswith("areas:"):
                entity["area"] = stripped.split(":", 1)[1].strip().strip("'\"")
                in_attributes = False
            elif stripped.startswith("attributes:"):
                in_attributes = True
            elif in_attributes and ":" in stripped:
                key, val = stripped.split(":", 1)
                entity["attributes"][key.strip()] = val.strip().strip("'\"")

        entities.append(entity)

    return entities
