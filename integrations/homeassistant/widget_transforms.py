"""Widget state poll transforms for Home Assistant.

GetLiveContext returns a JSON wrapper with YAML-formatted text listing all
exposed entities:

    {"success": true, "result": "Live Context: ...\\n- names: Office Desk LED Strip\\n  domain: light\\n  state: 'on'\\n  attributes:\\n    brightness: '255'\\n- names: ..."}

The ``entity_state`` transform extracts a single entity by display_label and
returns a flat dict the state_poll template can render.
"""
from __future__ import annotations

import copy
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
_TOGGLEABLE_DOMAINS = {"light", "switch", "fan", "input_boolean", "media_player"}


def _entity_id_from_live_entity(entity: dict) -> str:
    name = str(entity.get("name") or "").strip().lower()
    domain = str(entity.get("domain") or "").strip().lower()
    if not name or not domain:
        return ""
    slug = "".join(ch if ch.isalnum() else "_" for ch in name)
    while "__" in slug:
        slug = slug.replace("__", "_")
    slug = slug.strip("_")
    return f"{domain}.{slug}" if slug else ""


def _single_entity_view_from_live_context(raw_text: str, config: dict, display_label: str = "") -> dict:
    target = str(config.get("entity_id") or display_label or "").strip().lower()
    if not target:
        return {}

    for live_entity in _parse_live_context(raw_text):
        entity_id = _entity_id_from_live_entity(live_entity)
        name = str(live_entity.get("name") or "").strip()
        if target not in {entity_id.lower(), name.lower()}:
            continue

        attrs = dict(live_entity.get("attributes") or {})
        attrs.setdefault("friendly_name", name or entity_id)
        entity = {
            "entity_id": entity_id,
            "state": live_entity.get("state", ""),
            "attributes": attrs,
            "last_changed": live_entity.get("last_changed", ""),
            "last_updated": live_entity.get("last_updated", ""),
        }
        view = _single_entity_view(entity, config)
        if str(config.get("action_target") or "").strip().lower() == "name":
            view["toggle_target_entity_id"] = view.get("friendly_name", "") or entity_id
        view["is_live_summary"] = False
        view["is_entity_preset"] = True
        return view
    return {}


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

    config = widget_meta.get("config") if isinstance(widget_meta.get("config"), dict) else {}
    return _single_entity_view(entity, config)


def render_single_entity_widget(data: dict, _components: list[dict]) -> list[dict]:
    """Code transform for the initial ha_get_state render.

    The template language is intentionally small, so build the adaptive component
    tree in Python once from the same view-model used by state_poll refreshes.
    """
    entity = data.get("data") if isinstance(data.get("data"), dict) else {}
    if not entity or not entity.get("entity_id"):
        return _components
    config = data.get("config") if isinstance(data.get("config"), dict) else {}
    return _build_entity_widget_components(_single_entity_view(entity, config))


def _single_entity_view(entity: dict, config: dict) -> dict:
    entity_id = entity.get("entity_id") or ""
    state = entity.get("state", "")
    attrs = entity.get("attributes") or {}
    friendly = attrs.get("friendly_name") or entity_id
    unit = attrs.get("unit_of_measurement") or ""
    domain = entity_id.split(".", 1)[0] if entity_id else ""
    is_on = str(state).lower() in _ON_STATES

    supports_toggle = domain in _TOGGLEABLE_DOMAINS
    supports_brightness = domain == "light"
    forced_variant = str(config.get("preset_variant") or "").strip().lower()
    allow_action = bool(config.get("allow_action", False))

    if forced_variant in {"sensor_card", "light_card", "toggle_chip", "entity_chip"}:
        widget_variant = forced_variant
    elif domain == "sensor":
        widget_variant = "sensor_card"
    elif domain == "light":
        widget_variant = "light_card"
    elif supports_toggle:
        widget_variant = "toggle_chip"
    else:
        widget_variant = "entity_chip"

    brightness_raw = attrs.get("brightness")
    brightness = _parse_brightness(brightness_raw) if brightness_raw is not None else (100 if is_on else 0)
    show_brightness = supports_brightness and is_on and bool(config.get("show_brightness", True))
    primary_info = str(config.get("primary_info") or "").strip().lower() or "name"
    secondary_info = str(config.get("secondary_info") or "").strip().lower() or "none"
    primary_text = _entity_property_value(entity, primary_info, friendly_name=friendly, display_value=_format_display_value(state, unit))
    secondary_text = _entity_property_value(entity, secondary_info, friendly_name=friendly, display_value=_format_display_value(state, unit))
    if not primary_text and secondary_text:
        primary_text, secondary_text = secondary_text, ""
    if not primary_text:
        primary_text = friendly
    chip_text = primary_text
    if secondary_text:
        chip_text = f"{chip_text} · {secondary_text}".strip(" ·")

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
        "widget_variant": widget_variant,
        "is_sensor_card": widget_variant == "sensor_card",
        "is_light_card": widget_variant == "light_card",
        "is_toggle_chip": widget_variant == "toggle_chip",
        "is_entity_chip": widget_variant == "entity_chip",
        "supports_toggle": supports_toggle,
        "supports_brightness": supports_brightness,
        "allow_action": allow_action,
        "show_brightness": show_brightness,
        "brightness": brightness,
        "show_toggle_on": supports_toggle and not is_on and (
            widget_variant == "toggle_chip"
            or widget_variant == "light_card"
            or allow_action
        ),
        "show_toggle_off": supports_toggle and is_on and (
            widget_variant == "toggle_chip"
            or widget_variant == "light_card"
            or allow_action
        ),
        "show_light_status_on": widget_variant == "light_card" and is_on,
        "show_light_status_off": widget_variant == "light_card" and not is_on,
        "show_brightness_button_show": supports_brightness and is_on and not show_brightness,
        "show_brightness_button_hide": supports_brightness and is_on and show_brightness,
        "toggle_target_name": friendly,
        "toggle_target_entity_id": entity_id,
        "toggle_on_tool": "HassTurnOn" if supports_toggle else "",
        "toggle_off_tool": "HassTurnOff" if supports_toggle else "",
        "primary_info": primary_info,
        "secondary_info": secondary_info,
        "primary_text": primary_text,
        "secondary_text": secondary_text,
        "chip_text": chip_text,
        "chip_color": "success" if is_on else "accent",
    }


def _build_entity_widget_components(view: dict) -> list[dict]:
    components: list[dict] = []

    if view.get("is_sensor_card") or view.get("is_light_card"):
        components.append({
            "type": "heading",
            "text": view.get("friendly_name", ""),
            "level": 3,
        })

    if view.get("is_sensor_card"):
        components.append({
            "type": "status",
            "text": view.get("display_value", ""),
            "color": "accent",
        })

    if view.get("is_light_card"):
        components.append({
            "type": "status",
            "text": "On" if view.get("is_on") else "Off",
            "color": "success" if view.get("is_on") else "muted",
        })

    if view.get("is_toggle_chip") or view.get("is_entity_chip"):
        components.append({
            "type": "status",
            "text": view.get("chip_text", ""),
            "color": view.get("chip_color", "accent"),
        })

    if view.get("show_toggle_off"):
        components.append({
            "type": "toggle",
            "label": "Power",
            "value": True,
            "color": "success",
            "action": {
                "dispatch": "tool",
                "tool": view.get("toggle_off_tool", ""),
                "args": {"name": view.get("toggle_target_entity_id", "")},
                "optimistic": True,
            },
        })

    if view.get("show_toggle_on"):
        components.append({
            "type": "toggle",
            "label": "Power",
            "value": False,
            "action": {
                "dispatch": "tool",
                "tool": view.get("toggle_on_tool", ""),
                "args": {"name": view.get("toggle_target_entity_id", "")},
                "optimistic": True,
            },
        })

    if view.get("show_brightness_button_hide"):
        components.append({
            "type": "button",
            "label": "Hide brightness",
            "subtle": True,
            "action": {
                "dispatch": "widget_config",
                "config": {"show_brightness": False},
            },
        })
    elif view.get("show_brightness_button_show"):
        components.append({
            "type": "button",
            "label": "Show brightness",
            "subtle": True,
            "action": {
                "dispatch": "widget_config",
                "config": {"show_brightness": True},
            },
        })

    if view.get("show_brightness"):
        components.append({
            "type": "slider",
            "label": "Brightness",
            "value": view.get("brightness", 0),
            "min": 0,
            "max": 100,
            "step": 5,
            "unit": "%",
            "color": "accent",
            "action": {
                "dispatch": "tool",
                "tool": "HassLightSet",
                "args": {"name": view.get("toggle_target_entity_id", "")},
                "value_key": "brightness",
            },
        })

    props = [{"label": "entity", "value": view.get("entity_id", "")}]
    if view.get("is_sensor_card") or view.get("is_light_card"):
        props.append({"label": "updated", "value": view.get("last_changed", "")})
    components.append({
        "type": "properties",
        "layout": "inline",
        "items": props,
    })

    return copy.deepcopy(components)


def _compute_live_context_view(raw_text: str, raw_filter: str) -> dict:
    """Shared view-data helper used by both the main transform (for the
    initial in-thread render) and the state_poll transform (for pinned
    re-renders driven by config changes).

    Returns a flat dict with pre-computed counts, the active-entity
    tiles, and the data-driven filter button lists.
    """
    entities = [
        e for e in _parse_live_context(raw_text)
        if e.get("domain") and e.get("state")
    ]

    filter_lc = raw_filter.strip().lower()

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

    tallies: dict[str, int] = {}
    for e in matching:
        d = e.get("domain", "") or "unknown"
        tallies[d] = tallies.get(d, 0) + 1
    domain_counts = [
        {"label": d, "value": str(count)}
        for d, count in sorted(tallies.items(), key=lambda kv: -kv[1])
    ]

    total = len(entities)
    shown = len(matching)
    filter_active = bool(filter_lc)

    if filter_active:
        status_text = f"Filtered: {raw_filter.strip()} · {shown}/{total} entities"
        status_color = "accent"
    else:
        status_text = f"{total} entities · {len(active)} active"
        status_color = "info"

    area_buttons = [] if filter_active else [
        {"label": area, "filter_value": area} for area in all_areas
    ]
    domain_buttons = [] if filter_active else [
        {"label": domain, "filter_value": domain} for domain in all_domains
    ]

    return {
        "is_live_summary": True,
        "is_entity_preset": False,
        "status_text": status_text,
        "status_color": status_color,
        "total": total,
        "shown": shown,
        "filter_active": filter_active,
        "active_count": len(active),
        "active": active,
        "domain_counts": domain_counts,
        "area_buttons": area_buttons,
        "domain_buttons": domain_buttons,
    }


def live_context_summary(data: dict, components: list[dict]) -> list[dict]:
    """Main-template transform for homeassistant-GetLiveContext.

    Used for the initial in-thread render. The pinned-card interactive
    view is driven by ``live_context_poll`` + a state_poll template that
    uses each-blocks to emit buttons dynamically.

    Signature matches the top-level ``transform`` contract in
    ``app/services/widget_templates.py:_apply_code_transform``.
    """
    result_text = data.get("result")
    if not isinstance(result_text, str):
        return components

    cfg = data.get("config") if isinstance(data.get("config"), dict) else {}
    if cfg.get("entity_id") or cfg.get("preset_variant"):
        entity_view = _single_entity_view_from_live_context(
            result_text,
            cfg,
            str(data.get("display_label") or ""),
        )
        if entity_view:
            return _build_entity_widget_components(entity_view)

    view = _compute_live_context_view(result_text, str(cfg.get("filter", "") or ""))

    new_components: list[dict] = [
        {"type": "status", "text": view["status_text"], "color": view["status_color"]},
    ]
    if view["filter_active"]:
        new_components.append({
            "type": "button",
            "label": "Clear filter",
            "subtle": True,
            "action": {
                "dispatch": "widget_config",
                "config": {"filter": ""},
            },
        })
    if view["domain_counts"]:
        new_components.append({
            "type": "tiles",
            "min_width": 140,
            "items": view["domain_counts"],
        })
    if view["active"]:
        new_components.append({
            "type": "section",
            "label": f"Active now ({view['active_count']})",
            "collapsible": True,
            "defaultOpen": False,
            "children": [{"type": "tiles", "min_width": 180, "items": view["active"]}],
        })
    if not view["filter_active"] and (view["area_buttons"] or view["domain_buttons"]):
        area_btns = [
            {
                "type": "button", "label": b["label"], "subtle": True,
                "action": {
                    "dispatch": "widget_config",
                    "config": {"filter": b["filter_value"]},
                },
            }
            for b in view["area_buttons"]
        ]
        domain_btns = [
            {
                "type": "button", "label": b["label"], "subtle": True,
                "action": {
                    "dispatch": "widget_config",
                    "config": {"filter": b["filter_value"]},
                },
            }
            for b in view["domain_buttons"]
        ]
        children: list[dict] = []
        if area_btns:
            children.append({
                "type": "properties", "layout": "inline",
                "items": [{"label": "By area", "value": ""}],
            })
            children.extend(area_btns)
        if domain_btns:
            children.append({
                "type": "properties", "layout": "inline",
                "items": [{"label": "By domain", "value": ""}],
            })
            children.extend(domain_btns)
        new_components.append({
            "type": "section", "label": "Filter",
            "collapsible": True, "defaultOpen": False,
            "children": children,
        })

    return new_components


def live_context_poll(raw_result: str, widget_meta: dict) -> dict:
    """State-poll transform for homeassistant-GetLiveContext.

    Called on pin refresh (interval + widget_config changes). Returns the
    view-data dict that the state_poll template substitutes into an
    each-block driven component tree — so a Clear-filter or area-button
    click re-renders the pinned card without touching the DB for a new
    envelope.
    """
    parsed = _unwrap(raw_result)
    raw_text = parsed.get("result", "")
    if not isinstance(raw_text, str):
        raw_text = ""

    cfg = widget_meta.get("config") if isinstance(widget_meta.get("config"), dict) else {}
    if cfg.get("entity_id") or cfg.get("preset_variant"):
        entity_view = _single_entity_view_from_live_context(
            raw_text,
            cfg,
            str(widget_meta.get("display_label") or ""),
        )
        if entity_view:
            return entity_view
    return _compute_live_context_view(raw_text, str(cfg.get("filter", "") or ""))


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


def _entity_property_value(
    entity: dict,
    prop: str,
    *,
    friendly_name: str,
    display_value: str,
) -> str:
    attrs = entity.get("attributes") if isinstance(entity.get("attributes"), dict) else {}
    key = (prop or "").strip().lower()
    if not key or key == "none":
        return ""
    if key == "name":
        return _stringify_property_value(friendly_name or entity.get("entity_id") or "")
    if key == "state":
        return _stringify_property_value(display_value or entity.get("state") or "")
    if key == "last_changed":
        return _stringify_property_value(entity.get("last_changed"))
    if key == "last_updated":
        return _stringify_property_value(entity.get("last_updated") or entity.get("last_changed"))
    if key.startswith("attr:"):
        attr_key = key[5:]
        return _stringify_property_value(attrs.get(attr_key))
    return ""


def _stringify_property_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "On" if value else "Off"
    return str(value)


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
