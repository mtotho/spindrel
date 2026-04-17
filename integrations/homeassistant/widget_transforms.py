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
            }

    logger.debug("entity_state: entity '%s' not found in %d entities", display_label, len(entities))
    return {}


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
            elif stripped.startswith("attributes:"):
                in_attributes = True
            elif in_attributes and ":" in stripped:
                key, val = stripped.split(":", 1)
                entity["attributes"][key.strip()] = val.strip().strip("'\"")

        entities.append(entity)

    return entities
