"""Bot tools for dashboard-aware widget management.

Lets an agent act as a first-class collaborator on the channel dashboard:

  - ``describe_dashboard`` — read raw JSON + ASCII preview of the layout.
  - ``pin_widget`` — pin any library widget (builtin / integration / channel
    workspace) with optional zone + coords.
  - ``move_pins`` — batch-update zone + ``{x, y, w, h}`` for one or more pins.
  - ``unpin_widget`` — remove any pin on the dashboard.
  - ``promote_panel`` / ``demote_panel`` — toggle a pin's panel-mode role.

By default every tool operates on the current channel's implicit dashboard
(``channel:<channel_id>``); an explicit ``dashboard_key`` overrides that for
pinning to a named or global dashboard.

No HTTP layer — tools call the service helpers in
``app/services/dashboard_pins.py`` and ``app/services/dashboards.py``
directly (same pattern as ``pin_suite``).
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from app.agent.context import current_bot_id, current_channel_id
from app.tools.registry import register

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


_DESCRIBE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "describe_dashboard",
        "description": (
            "Return the current state of a widget dashboard as both raw "
            "pin JSON and an ASCII-art preview. Use this FIRST before "
            "proposing any layout change — it shows you what's pinned, "
            "where, and in which zone (rail, header, dock, grid).\n\n"
            "Two views are rendered side-by-side by default:\n"
            "  • CHAT VIEW — header + rail + dock (what the user sees "
            "while chatting alongside a chat column).\n"
            "  • FULL DASHBOARD VIEW — adds the grid zone (visible only on "
            "/widgets/channel/<uuid>).\n\n"
            "Each pin row carries a `visible_in_chat` boolean: True for "
            "rail/header/dock, False for grid. When the user says 'put it "
            "where I'll see it while chatting', pin to a visible-in-chat "
            "zone."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "dashboard_key": {
                    "type": "string",
                    "description": (
                        "Optional. Dashboard slug (e.g. 'channel:<uuid>', "
                        "'default', or a named user slug). Defaults to the "
                        "current channel's dashboard."
                    ),
                },
                "view": {
                    "type": "string",
                    "enum": ["chat", "full", "both"],
                    "description": (
                        "Which ASCII view(s) to render. 'both' (default) "
                        "renders chat then full."
                    ),
                },
            },
        },
    },
}


_PIN_WIDGET_SCHEMA = {
    "type": "function",
    "function": {
        "name": "pin_widget",
        "description": (
            "Pin a library widget onto a dashboard. Picks the widget by "
            "slug, file path, or name from one of three catalogs: "
            "'builtin' (ships with the server), 'integration' (bundled by "
            "a specific integration), or 'channel' (user/bot-authored in "
            "the channel workspace). Place-at defaults to the grid zone "
            "at the first empty slot; pass zone/x/y/w/h explicitly to "
            "override.\n\n"
            "Call `describe_dashboard` first to see what's already pinned "
            "— this tool refuses to pin a widget that already exists on "
            "the target dashboard with the same source+path."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "widget": {
                    "type": "string",
                    "description": (
                        "Widget slug, file path, or name. Matched against "
                        "the catalog entry's slug/path/name fields."
                    ),
                },
                "source_kind": {
                    "type": "string",
                    "enum": ["builtin", "integration", "channel"],
                    "description": (
                        "Which catalog to search. 'builtin' scans "
                        "app/tools/local/widgets/; 'integration' requires "
                        "source_integration_id; 'channel' scans the "
                        "current channel's workspace."
                    ),
                },
                "source_integration_id": {
                    "type": "string",
                    "description": (
                        "Required when source_kind='integration'. The "
                        "integration's directory name (e.g. 'homeassistant')."
                    ),
                },
                "dashboard_key": {
                    "type": "string",
                    "description": (
                        "Optional. Dashboard slug to pin onto. Defaults to "
                        "the current channel's dashboard."
                    ),
                },
                "zone": {
                    "type": "string",
                    "enum": ["rail", "header", "dock", "grid"],
                    "description": (
                        "Which zone to land in. Defaults to 'grid'. "
                        "rail/header/dock are chat-visible; grid is full-"
                        "dashboard-only."
                    ),
                },
                "x": {"type": "integer", "description": "Optional column offset."},
                "y": {"type": "integer", "description": "Optional row offset."},
                "w": {"type": "integer", "description": "Optional width in cols."},
                "h": {"type": "integer", "description": "Optional height in rows."},
                "display_label": {
                    "type": "string",
                    "description": (
                        "Optional user-facing label override. Falls back "
                        "to the widget's manifest display_label."
                    ),
                },
                "auth_scope": {
                    "type": "string",
                    "enum": ["user", "bot"],
                    "description": (
                        "How the widget iframe authenticates. 'user' "
                        "(default) means each viewer runs the widget with "
                        "their own credentials. 'bot' means every viewer "
                        "sees the widget run as THIS bot — use when the "
                        "widget needs bot-scoped data the viewer doesn't "
                        "have access to."
                    ),
                },
            },
            "required": ["widget"],
        },
    },
}


_MOVE_PINS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "move_pins",
        "description": (
            "Batch-update one or more pins' zone + coordinates on a "
            "dashboard. Every move is applied in a single transaction — "
            "on any validation failure, nothing changes.\n\n"
            "Omitted fields preserve the pin's current value (so you can "
            "move a pin to a new zone without respecifying its size)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "moves": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "pin_id": {"type": "string"},
                            "zone": {
                                "type": "string",
                                "enum": ["rail", "header", "dock", "grid"],
                            },
                            "x": {"type": "integer"},
                            "y": {"type": "integer"},
                            "w": {"type": "integer"},
                            "h": {"type": "integer"},
                        },
                        "required": ["pin_id"],
                    },
                },
                "dashboard_key": {
                    "type": "string",
                    "description": (
                        "Optional. Defaults to the current channel's "
                        "dashboard."
                    ),
                },
            },
            "required": ["moves"],
        },
    },
}


_UNPIN_SCHEMA = {
    "type": "function",
    "function": {
        "name": "unpin_widget",
        "description": (
            "Remove a pin from its dashboard. Use `describe_dashboard` to "
            "find the pin_id. Confirm with the user before unpinning "
            "widgets they authored (source_bot_id=null) — only unpin "
            "yourself's pins freely."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pin_id": {"type": "string"},
                "delete_bundle_data": {
                    "type": "boolean",
                    "description": (
                        "If True, also delete the widget's SQLite data "
                        "file (if one exists). Defaults to False — "
                        "unpinning preserves the data in case the user "
                        "re-pins later."
                    ),
                },
            },
            "required": ["pin_id"],
        },
    },
}


_PROMOTE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "promote_panel",
        "description": (
            "Make `pin_id` the dashboard's main panel — fills the "
            "dashboard's main area and suppresses the grid. At most one "
            "pin per dashboard can be the panel; promoting a new one "
            "demotes the existing panel pin atomically."
        ),
        "parameters": {
            "type": "object",
            "properties": {"pin_id": {"type": "string"}},
            "required": ["pin_id"],
        },
    },
}


_DEMOTE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "demote_panel",
        "description": (
            "Clear `pin_id`'s panel-mode flag. If this leaves the "
            "dashboard with no panel pin, the dashboard reverts to normal "
            "grid mode."
        ),
        "parameters": {
            "type": "object",
            "properties": {"pin_id": {"type": "string"}},
            "required": ["pin_id"],
        },
    },
}


# ---------------------------------------------------------------------------
# Returns schemas
# ---------------------------------------------------------------------------


_PIN_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "dashboard_key": {"type": "string"},
        "zone": {"type": "string"},
        "grid_layout": {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "w": {"type": "integer"},
                "h": {"type": "integer"},
            },
        },
        "tool_name": {"type": "string"},
        "display_label": {"type": ["string", "null"]},
        "source_kind": {"type": "string"},
        "source_bot_id": {"type": ["string", "null"]},
        "visible_in_chat": {"type": "boolean"},
    },
}


_DESCRIBE_RETURNS = {
    "type": "object",
    "properties": {
        "llm": {"type": "string"},
        "dashboard_key": {"type": "string"},
        "dashboard": {"type": "object"},
        "pins": {"type": "array", "items": _PIN_RESULT_SCHEMA},
        "ascii_preview": {"type": "string"},
        "error": {"type": "string"},
    },
}


_PIN_WIDGET_RETURNS = {
    "type": "object",
    "properties": {
        "llm": {"type": "string"},
        "pin_id": {"type": "string"},
        "zone": {"type": "string"},
        "grid_layout": {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "w": {"type": "integer"},
                "h": {"type": "integer"},
            },
        },
        "ascii_preview": {"type": "string"},
        "error": {"type": "string"},
    },
}


_MOVE_RETURNS = {
    "type": "object",
    "properties": {
        "llm": {"type": "string"},
        "updated": {"type": "integer"},
        "ascii_preview": {"type": "string"},
        "error": {"type": "string"},
    },
}


_UNPIN_RETURNS = {
    "type": "object",
    "properties": {
        "llm": {"type": "string"},
        "ok": {"type": "boolean"},
        "error": {"type": "string"},
    },
}


_PROMOTE_DEMOTE_RETURNS = {
    "type": "object",
    "properties": {
        "llm": {"type": "string"},
        "pin": _PIN_RESULT_SCHEMA,
        "error": {"type": "string"},
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_HTML_INTERACTIVE_CT = "application/vnd.spindrel.html+interactive"


def _resolve_dashboard_key(
    dashboard_key: str | None, channel_id: uuid.UUID | None,
) -> tuple[str | None, str | None]:
    """Resolve the effective dashboard_key and return ``(key, error)``.

    When both are None we can't infer a target dashboard — return an error
    string instead so the caller can surface a friendly message.
    """
    if dashboard_key:
        return dashboard_key, None
    if channel_id is None:
        return None, (
            "no dashboard_key provided and no channel context — "
            "pass dashboard_key='default' (or a specific dashboard slug)."
        )
    return f"channel:{channel_id}", None


def _visible_in_chat(zone: str) -> bool:
    return zone in ("rail", "header", "dock")


def _enriched_pins(pin_dicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add ``visible_in_chat`` to each serialized pin."""
    out: list[dict[str, Any]] = []
    for pin in pin_dicts:
        zone = pin.get("zone") or "grid"
        out.append({**pin, "visible_in_chat": _visible_in_chat(zone)})
    return out


async def _fetch_dashboard_and_pins(
    dashboard_key: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load the dashboard row + its pins, serialized."""
    from app.db.engine import async_session
    from app.services.dashboard_pins import list_pins, serialize_pin
    from app.services.dashboards import get_dashboard, serialize_dashboard

    async with async_session() as db:
        row = await get_dashboard(db, dashboard_key)
        pins = await list_pins(db, dashboard_key=dashboard_key)
        return (
            serialize_dashboard(row),
            [serialize_pin(p) for p in pins],
        )


def _find_entry_by_match(entries: list[dict[str, Any]], needle: str) -> dict | None:
    """Match on slug → path → name (case-insensitive)."""
    n = needle.strip().lower()
    for e in entries:
        if e.get("slug", "").lower() == n:
            return e
    for e in entries:
        if e.get("path", "").lower() == n:
            return e
    for e in entries:
        if e.get("name", "").lower() == n:
            return e
    return None


async def _resolve_widget_entry(
    widget: str,
    *,
    source_kind: str,
    source_integration_id: str | None,
    channel_id: uuid.UUID | None,
    bot_id: str | None,
) -> tuple[dict | None, str | None]:
    """Locate a catalog entry; return ``(entry, error)``."""
    from app.services.html_widget_scanner import (
        scan_builtin, scan_channel, scan_integration,
    )

    if source_kind == "builtin":
        entries = scan_builtin()
    elif source_kind == "integration":
        if not source_integration_id:
            return None, (
                "source_integration_id is required when source_kind='integration'."
            )
        entries = scan_integration(source_integration_id)
    elif source_kind == "channel":
        if channel_id is None:
            return None, (
                "source_kind='channel' requires channel context — "
                "run inside a channel."
            )
        if not bot_id:
            return None, (
                "source_kind='channel' requires bot context — no bot bound."
            )
        from app.agent.bots import get_bot
        bot = get_bot(bot_id)
        if bot is None:
            return None, f"bot {bot_id!r} not found."
        entries = scan_channel(str(channel_id), bot)
    else:
        return None, f"unknown source_kind: {source_kind!r}"

    entry = _find_entry_by_match(entries, widget)
    if entry is None:
        available = ", ".join(e.get("slug", "") for e in entries[:10])
        return None, (
            f"no {source_kind!r} widget matching {widget!r}. "
            f"First available: {available or '(none)'}."
        )
    return entry, None


def _envelope_for_entry(
    entry: dict[str, Any],
    *,
    channel_id: uuid.UUID | None,
    source_bot_id: str | None,
    display_label: str | None,
) -> dict[str, Any]:
    """Mirror of ``HtmlWidgetsTab.envelopeForEntry`` from the UI.

    Synthesizes the envelope we persist on the pin so the iframe renderer
    fetches content from the right endpoint based on ``source_kind``.
    """
    label = display_label or entry.get("display_label") or entry.get("name")
    envelope: dict[str, Any] = {
        "content_type": _HTML_INTERACTIVE_CT,
        "body": "",
        "plain_body": entry.get("description") or label,
        "display": "inline",
        "display_label": label,
        "source_path": entry.get("path"),
        "source_bot_id": source_bot_id,
        "extra_csp": entry.get("extra_csp"),
    }
    source = entry.get("source")
    if source == "builtin":
        envelope["source_kind"] = "builtin"
    elif source == "integration":
        envelope["source_kind"] = "integration"
        envelope["source_integration_id"] = entry.get("integration_id")
    else:  # channel
        envelope["source_kind"] = "channel"
        if channel_id is not None:
            envelope["source_channel_id"] = str(channel_id)
    return envelope


def _render_preview(dashboard: dict[str, Any], pins: list[dict[str, Any]]) -> str:
    from app.services.dashboard_ascii import render_layout

    return render_layout(dashboard, pins, view="both")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@register(
    _DESCRIBE_SCHEMA,
    safety_tier="readonly",
    requires_channel_context=False,
    returns=_DESCRIBE_RETURNS,
)
async def describe_dashboard(
    dashboard_key: str | None = None,
    view: str = "both",
) -> str:
    channel_id = current_channel_id.get()
    key, err = _resolve_dashboard_key(dashboard_key, channel_id)
    if err:
        return json.dumps({"error": err, "llm": err})

    # Channel dashboard — ensure it exists so a fresh channel doesn't 404 on
    # "what's pinned?" when nothing has been pinned yet.
    if key and key.startswith("channel:") and channel_id is not None:
        from app.db.engine import async_session
        from app.services.dashboards import ensure_channel_dashboard
        async with async_session() as db:
            await ensure_channel_dashboard(db, channel_id)

    try:
        dashboard, pin_dicts = await _fetch_dashboard_and_pins(key)
    except Exception as exc:
        logger.exception("describe_dashboard failed")
        return json.dumps({"error": str(exc), "llm": f"describe_dashboard failed: {exc}"})

    enriched = _enriched_pins(pin_dicts)

    from app.services.dashboard_ascii import render_layout
    v = view if view in ("chat", "full", "both") else "both"
    ascii_preview = render_layout(dashboard, enriched, view=v)  # type: ignore[arg-type]

    # Short narrative for the LLM: zone counts + panel-mode state.
    zone_counts: dict[str, int] = {"rail": 0, "header": 0, "dock": 0, "grid": 0}
    for pin in enriched:
        z = pin.get("zone") or "grid"
        if z in zone_counts:
            zone_counts[z] += 1
    visible = sum(1 for p in enriched if p.get("visible_in_chat"))
    panel_pins = [p for p in enriched if p.get("is_main_panel")]
    narrative = (
        f"Dashboard {key!r}: {len(enriched)} pin(s) total — "
        f"rail={zone_counts['rail']}, header={zone_counts['header']}, "
        f"dock={zone_counts['dock']}, grid={zone_counts['grid']}. "
        f"{visible} visible in chat view; "
        f"{len(panel_pins)} panel pin(s)."
    )

    return json.dumps({
        "dashboard_key": key,
        "dashboard": dashboard,
        "pins": enriched,
        "ascii_preview": ascii_preview,
        "llm": narrative + "\n\n" + ascii_preview,
    })


@register(
    _PIN_WIDGET_SCHEMA,
    safety_tier="mutating",
    requires_bot_context=True,
    requires_channel_context=False,
    returns=_PIN_WIDGET_RETURNS,
)
async def pin_widget(
    widget: str,
    source_kind: str = "builtin",
    source_integration_id: str | None = None,
    dashboard_key: str | None = None,
    zone: str = "grid",
    x: int | None = None,
    y: int | None = None,
    w: int | None = None,
    h: int | None = None,
    display_label: str | None = None,
    auth_scope: str = "user",
) -> str:
    if zone not in ("rail", "header", "dock", "grid"):
        return json.dumps({"error": f"invalid zone: {zone!r}"})
    if auth_scope not in ("user", "bot"):
        return json.dumps({"error": f"invalid auth_scope: {auth_scope!r}"})

    channel_id = current_channel_id.get()
    bot_id = current_bot_id.get()

    key, err = _resolve_dashboard_key(dashboard_key, channel_id)
    if err:
        return json.dumps({"error": err, "llm": err})

    entry, err = await _resolve_widget_entry(
        widget,
        source_kind=source_kind,
        source_integration_id=source_integration_id,
        channel_id=channel_id,
        bot_id=bot_id,
    )
    if err:
        return json.dumps({"error": err, "llm": err})
    assert entry is not None  # narrowing after err-check

    # Determine the pin's effective identity so we can refuse duplicates.
    effective_bot_id = bot_id if auth_scope == "bot" else None

    envelope = _envelope_for_entry(
        entry,
        channel_id=channel_id,
        source_bot_id=effective_bot_id,
        display_label=display_label,
    )

    # Resolve target slot — if any of (x, y) are missing, first-free-slot
    # within the zone at the defaulted or supplied (w, h).
    from app.services.dashboard_ascii import (
        default_size_for_zone,
        find_free_slot,
        resolve_preset_name,
    )
    from app.db.engine import async_session
    from app.services.dashboard_pins import (
        apply_layout_bulk,
        create_pin,
        list_pins,
        serialize_pin,
    )
    from app.services.dashboards import ensure_channel_dashboard, get_dashboard

    default_w, default_h = default_size_for_zone(zone)  # type: ignore[arg-type]
    wp = w if w is not None else default_w
    hp = h if h is not None else default_h

    async with async_session() as db:
        # Lazy-create the channel dashboard up front so list_pins below returns
        # an empty list instead of 404'ing on a never-viewed channel.
        if key.startswith("channel:") and channel_id is not None:
            await ensure_channel_dashboard(db, channel_id)
        dashboard_row = await get_dashboard(db, key)
        preset_name = resolve_preset_name(dashboard_row.grid_config)

        existing_pins = await list_pins(db, dashboard_key=key)
        existing = [serialize_pin(p) for p in existing_pins]

        # Refuse duplicates — same source + path on the same dashboard.
        needle_path = entry.get("path")
        for existing_pin in existing:
            env = existing_pin.get("envelope") or {}
            if (
                env.get("source_kind") == envelope.get("source_kind")
                and env.get("source_integration_id") == envelope.get("source_integration_id")
                and env.get("source_path") == needle_path
            ):
                err_msg = (
                    f"{widget!r} is already pinned to {key!r} as pin "
                    f"{existing_pin['id']}. Unpin it first or move the "
                    "existing pin instead of adding a duplicate."
                )
                return json.dumps({"error": err_msg, "llm": err_msg})

        zone_pins = [p for p in existing if (p.get("zone") or "grid") == zone]
        if x is None or y is None:
            fy, fx = find_free_slot(
                zone_pins, zone=zone, w=wp, h=hp, preset_name=preset_name,  # type: ignore[arg-type]
            )
            final_x = x if x is not None else fx
            final_y = y if y is not None else fy
        else:
            final_x, final_y = x, y

        try:
            pin = await create_pin(
                db,
                source_kind="adhoc",
                tool_name="emit_html_widget",  # renders through InteractiveHtmlRenderer
                envelope=envelope,
                source_channel_id=channel_id,
                source_bot_id=effective_bot_id,
                display_label=display_label or envelope.get("display_label"),
                dashboard_key=key,
            )
        except Exception as exc:
            logger.exception("pin_widget: create_pin failed")
            return json.dumps({"error": str(exc), "llm": f"pin_widget failed: {exc}"})

        # Place it in the requested zone + coords.
        try:
            await apply_layout_bulk(
                db,
                [{
                    "id": str(pin.id),
                    "x": int(final_x), "y": int(final_y),
                    "w": int(wp), "h": int(hp),
                    "zone": zone,
                }],
                dashboard_key=key,
            )
        except Exception as exc:
            logger.exception("pin_widget: apply_layout_bulk failed")
            return json.dumps({"error": str(exc)})

        # Re-fetch to render preview against final state.
        dashboard_dict, pins = await _fetch_dashboard_and_pins(key)

    enriched = _enriched_pins(pins)
    ascii_preview = _render_preview(dashboard_dict, enriched)
    label = envelope.get("display_label") or widget
    scope_desc = "user" if auth_scope == "user" else f"bot ({bot_id})"
    narrative = (
        f"Pinned {label!r} to {key} in zone={zone} at "
        f"x={final_x},y={final_y},w={wp},h={hp} (auth scope: {scope_desc}). "
        f"pin_id={pin.id}."
    )
    return json.dumps({
        "pin_id": str(pin.id),
        "zone": zone,
        "grid_layout": {"x": int(final_x), "y": int(final_y), "w": int(wp), "h": int(hp)},
        "ascii_preview": ascii_preview,
        "llm": narrative + "\n\n" + ascii_preview,
    })


@register(
    _MOVE_PINS_SCHEMA,
    safety_tier="mutating",
    requires_bot_context=True,
    returns=_MOVE_RETURNS,
)
async def move_pins(
    moves: list[dict[str, Any]] | None = None,
    dashboard_key: str | None = None,
) -> str:
    if not moves or not isinstance(moves, list):
        return json.dumps({"error": "moves must be a non-empty list"})

    channel_id = current_channel_id.get()
    key, err = _resolve_dashboard_key(dashboard_key, channel_id)
    if err:
        return json.dumps({"error": err, "llm": err})

    from app.db.engine import async_session
    from app.services.dashboard_pins import apply_layout_bulk, list_pins, serialize_pin
    from app.services.dashboards import get_dashboard, serialize_dashboard

    async with async_session() as db:
        existing = await list_pins(db, dashboard_key=key)
        by_id = {str(p.id): p for p in existing}

        items: list[dict[str, Any]] = []
        for m in moves:
            if not isinstance(m, dict):
                return json.dumps({"error": "each move must be an object"})
            pid = m.get("pin_id")
            if not pid or pid not in by_id:
                return json.dumps({
                    "error": f"pin_id {pid!r} not on dashboard {key!r}",
                })
            row = by_id[pid]
            current_layout = row.grid_layout or {}
            merged = {
                "id": pid,
                "x": int(m.get("x", current_layout.get("x", 0) or 0)),
                "y": int(m.get("y", current_layout.get("y", 0) or 0)),
                "w": int(m.get("w", current_layout.get("w", 1) or 1)),
                "h": int(m.get("h", current_layout.get("h", 1) or 1)),
            }
            if "zone" in m and m["zone"] is not None:
                merged["zone"] = m["zone"]
            else:
                merged["zone"] = row.zone or "grid"
            items.append(merged)

        try:
            result = await apply_layout_bulk(db, items, dashboard_key=key)
        except Exception as exc:
            logger.exception("move_pins: apply_layout_bulk failed")
            return json.dumps({"error": str(exc)})

        # Render preview of the post-move state.
        pins = await list_pins(db, dashboard_key=key)
        dashboard_row = await get_dashboard(db, key)
        dashboard_dict = serialize_dashboard(dashboard_row)
        pin_dicts = [serialize_pin(p) for p in pins]

    enriched = _enriched_pins(pin_dicts)
    ascii_preview = _render_preview(dashboard_dict, enriched)
    narrative = (
        f"Moved {result.get('updated', 0)} pin(s) on {key}. "
        f"Preview:"
    )
    return json.dumps({
        "updated": int(result.get("updated", 0)),
        "ascii_preview": ascii_preview,
        "llm": narrative + "\n" + ascii_preview,
    })


@register(
    _UNPIN_SCHEMA,
    safety_tier="mutating",
    requires_bot_context=True,
    returns=_UNPIN_RETURNS,
)
async def unpin_widget(
    pin_id: str,
    delete_bundle_data: bool = False,
) -> str:
    try:
        pid = uuid.UUID(pin_id)
    except (TypeError, ValueError):
        return json.dumps({"error": f"invalid pin_id: {pin_id!r}"})

    from app.db.engine import async_session
    from app.services.dashboard_pins import delete_pin

    async with async_session() as db:
        try:
            result = await delete_pin(
                db, pid, delete_bundle_data=bool(delete_bundle_data),
            )
        except Exception as exc:
            logger.exception("unpin_widget failed")
            return json.dumps({"error": str(exc)})

    llm = f"Unpinned widget {pin_id}."
    if result.get("bundle_data_deleted"):
        llm += f" Also deleted bundle data at {result.get('orphan_path')}."
    return json.dumps({"ok": True, "llm": llm})


@register(
    _PROMOTE_SCHEMA,
    safety_tier="mutating",
    requires_bot_context=True,
    returns=_PROMOTE_DEMOTE_RETURNS,
)
async def promote_panel(pin_id: str) -> str:
    try:
        pid = uuid.UUID(pin_id)
    except (TypeError, ValueError):
        return json.dumps({"error": f"invalid pin_id: {pin_id!r}"})

    from app.db.engine import async_session
    from app.services.dashboard_pins import promote_pin_to_panel

    async with async_session() as db:
        try:
            pin_dict = await promote_pin_to_panel(db, pid)
        except Exception as exc:
            logger.exception("promote_panel failed")
            return json.dumps({"error": str(exc)})

    label = pin_dict.get("display_label") or pin_dict.get("tool_name") or pin_id
    return json.dumps({
        "pin": {**pin_dict, "visible_in_chat": _visible_in_chat(pin_dict.get("zone") or "grid")},
        "llm": (
            f"Promoted {label!r} to the dashboard's main panel. The grid "
            "matrix is suppressed in favour of this pin."
        ),
    })


@register(
    _DEMOTE_SCHEMA,
    safety_tier="mutating",
    requires_bot_context=True,
    returns=_PROMOTE_DEMOTE_RETURNS,
)
async def demote_panel(pin_id: str) -> str:
    try:
        pid = uuid.UUID(pin_id)
    except (TypeError, ValueError):
        return json.dumps({"error": f"invalid pin_id: {pin_id!r}"})

    from app.db.engine import async_session
    from app.services.dashboard_pins import demote_pin_from_panel

    async with async_session() as db:
        try:
            pin_dict = await demote_pin_from_panel(db, pid)
        except Exception as exc:
            logger.exception("demote_panel failed")
            return json.dumps({"error": str(exc)})

    label = pin_dict.get("display_label") or pin_dict.get("tool_name") or pin_id
    return json.dumps({
        "pin": {**pin_dict, "visible_in_chat": _visible_in_chat(pin_dict.get("zone") or "grid")},
        "llm": f"Demoted {label!r} from panel mode.",
    })
