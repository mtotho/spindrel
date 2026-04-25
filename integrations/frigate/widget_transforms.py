"""Widget-template data shaping for Frigate.

Each widget has a shared reshape core plus two adapters (state-poll and
widget-level code transform) — the dual signatures are a requirement of the
template engine's two entry points, not a design choice.

Events timeline (``frigate_get_events``):
  - ``_reshape_events`` coerces epoch floats → ISO 8601 Z, maps Frigate labels
    to ``SemanticSlot`` colors, derives lanes from distinct cameras.
  - ``events_view`` — state-poll.
  - ``render_events_widget`` — initial render.

Cameras grid (``frigate_list_cameras``):
  - ``_reshape_cameras`` turns each camera record into an image-first ``tiles``
    v2 item — ``image_url`` points directly at Frigate's
    ``/api/<camera>/latest.jpg`` (assumed browser-reachable on the same LAN as
    Spindrel), with a cache-buster so state_poll refresh pulls a fresh frame
    every cycle. A pre-computed ``status`` slot (enabled → ``success``,
    disabled → ``muted``) sits in the tile corner; click dispatches
    ``frigate_snapshot`` to open the authenticated full-size snapshot.
  - ``cameras_view`` — state-poll.
  - ``render_cameras_widget`` — initial render.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from integrations.sdk import to_iso_z_or_none

logger = logging.getLogger(__name__)


# Semantic colors keyed by Frigate label. Unknown labels fall through to
# ``muted`` so the timeline doesn't crash the enum — any new label is
# visible but uncolored until someone adds it here.
_LABEL_COLOR: dict[str, str] = {
    "person": "accent",
    "car": "success",
    "truck": "success",
    "motorcycle": "success",
    "dog": "warning",
    "cat": "warning",
    "bicycle": "info",
}


def _reshape_events(parsed: dict) -> dict:
    """Turn raw Frigate event JSON into timeline-primitive-ready shape.

    Events missing an ``id`` or an unparseable ``start_time`` are dropped —
    the timeline primitive needs stable ids and ISO 8601 starts to render
    anything meaningful.
    """
    raw_events = parsed.get("events") if isinstance(parsed, dict) else None
    if not isinstance(raw_events, list):
        raw_events = []

    cameras_seen: list[str] = []
    events: list[dict[str, Any]] = []
    for ev in raw_events:
        if not isinstance(ev, dict):
            continue
        ev_id = ev.get("id")
        start_iso = to_iso_z_or_none(ev.get("start_time"))
        if not ev_id or not start_iso:
            continue
        camera = str(ev.get("camera") or "unknown")
        if camera not in cameras_seen:
            cameras_seen.append(camera)
        label = str(ev.get("label") or "event")
        score = ev.get("score")
        subtitle = f"score {score:.2f}" if isinstance(score, (int, float)) else None
        events.append({
            "id": str(ev_id),
            "start": start_iso,
            "end": to_iso_z_or_none(ev.get("end_time")) or start_iso,
            "lane_id": camera,
            "label": label,
            "color": _LABEL_COLOR.get(label, "muted"),
            "subtitle": subtitle,
        })

    lanes = [{"id": cam, "label": cam} for cam in sorted(cameras_seen)]

    return {
        "events": events,
        "lanes": lanes,
        "count": len(events),
        "has_events": bool(events),
        "error": parsed.get("error") if isinstance(parsed, dict) else None,
    }


# ── state-poll transform ──


def events_view(raw_result: str, widget_meta: dict) -> dict:
    """State-poll transform: raw JSON → shaped dict for template substitution."""
    try:
        parsed = (
            json.loads(raw_result) if isinstance(raw_result, str) else (raw_result or {})
        )
    except (json.JSONDecodeError, TypeError):
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return _reshape_events(parsed)


# ── widget-level code transform (initial render) ──


def render_events_widget(data: dict, _components: list[dict]) -> list[dict]:
    """Widget-level code transform — builds components directly from data.

    Initial render can't route through ``events_view`` (different signature)
    so we build the component list programmatically from the same reshape
    core. The YAML top-level template is an empty placeholder.
    """
    shaped = _reshape_events(data if isinstance(data, dict) else {})

    if shaped.get("error"):
        return [{"type": "status", "text": shaped["error"], "color": "danger"}]

    if not shaped["has_events"]:
        return [{"type": "text", "content": "No events in this window.", "style": "muted"}]

    widget_config = data.get("widget_config") if isinstance(data, dict) else {}
    widget_config = widget_config if isinstance(widget_config, dict) else {}

    return [
        {
            "type": "status",
            "text": f"{shaped['count']} events",
            "color": "info",
        },
        {
            "type": "timeline",
            "events": shaped["events"],
            "lanes": shaped["lanes"],
            "on_event_click": {
                "dispatch": "widget_config",
                "value_key": "selected_event",
            },
            "selected_event_id": widget_config.get("selected_event"),
        },
    ]


# ── Cameras grid ──


def _build_snapshot_url(base: str, *, show_bbox: bool, cache_bust: int) -> str:
    """Attach bbox + cache-bust params to Frigate's ``/api/<camera>/latest.jpg``.

    The cache-bust epoch changes each reshape so state_poll refresh forces
    the browser to pull a fresh frame instead of reusing a cached response.
    """
    sep = "&" if "?" in base else "?"
    parts = [f"t={cache_bust}"]
    if show_bbox:
        parts.append("bbox=1")
    return f"{base}{sep}{'&'.join(parts)}"


def _reshape_cameras(parsed: dict, widget_config: dict) -> dict:
    """Turn the raw ``frigate_list_cameras`` payload into tile-primitive shape.

    Image-first tiles: ``image_url`` is the camera's direct Frigate snapshot
    URL (no server proxy — assumes the FRIGATE_URL the server is configured
    with is also reachable from the user's browser, typical for a home LAN
    deploy). ``image_auth: none`` because Frigate's ``/api/<camera>/latest.jpg``
    endpoint is public by default. Clicking a tile still dispatches the
    authenticated ``frigate_snapshot`` tool so the full-size lightbox goes
    through the attachment flow.
    """
    raw_cams = parsed.get("cameras") if isinstance(parsed, dict) else None
    if not isinstance(raw_cams, list):
        raw_cams = []

    show_bbox = bool(widget_config.get("show_bbox", True))
    # int() once per reshape — reused across tiles so the URLs don't drift
    # inside a single refresh cycle (would cause every tile to refetch on
    # every pass of a loop, not just across state_poll ticks).
    cache_bust = int(time.time())

    tiles: list[dict[str, Any]] = []
    enabled_count = 0
    for cam in raw_cams:
        if not isinstance(cam, dict):
            continue
        name = cam.get("name")
        if not isinstance(name, str) or not name:
            continue
        enabled = bool(cam.get("enabled", True))
        if enabled:
            enabled_count += 1
        w, h, fps = cam.get("width"), cam.get("height"), cam.get("fps")
        caption_bits: list[str] = []
        if isinstance(w, int) and isinstance(h, int):
            caption_bits.append(f"{w}×{h}")
        if isinstance(fps, (int, float)):
            caption_bits.append(f"{fps:g}fps")
        tile: dict[str, Any] = {
            "label": name,
            "caption": " · ".join(caption_bits) or None,
            "status": "success" if enabled else "muted",
            "action": {
                "dispatch": "tool",
                "tool": "frigate_snapshot",
                "args": {"camera": name, "bounding_box": show_bbox},
            },
        }
        snapshot_url = cam.get("snapshot_url")
        # Only enabled cameras have a live frame — disabled cameras fall back
        # to text-mode so the muted status is the sole visual signal.
        if enabled and isinstance(snapshot_url, str) and snapshot_url:
            tile["image_url"] = _build_snapshot_url(
                snapshot_url,
                show_bbox=show_bbox,
                cache_bust=cache_bust,
            )
            tile["image_aspect_ratio"] = "16 / 9"
            tile["image_auth"] = "none"
        tiles.append(tile)

    count = len(tiles)
    disabled_count = count - enabled_count
    if count == 0:
        summary = "No cameras"
    elif disabled_count == 0:
        summary = f"{count} live" if count != 1 else "1 live"
    else:
        summary = f"{enabled_count} live · {disabled_count} disabled"

    return {
        "tiles": tiles,
        "count": count,
        "enabled_count": enabled_count,
        "disabled_count": disabled_count,
        "summary": summary,
        "has_cameras": count > 0,
        "error": parsed.get("error") if isinstance(parsed, dict) else None,
    }


def cameras_view(raw_result: str, widget_meta: dict) -> dict:
    """State-poll transform: raw JSON → shaped dict for template substitution."""
    try:
        parsed = (
            json.loads(raw_result) if isinstance(raw_result, str) else (raw_result or {})
        )
    except (json.JSONDecodeError, TypeError):
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    widget_config = widget_meta.get("widget_config") or widget_meta.get("config") or {}
    if not isinstance(widget_config, dict):
        widget_config = {}
    return _reshape_cameras(parsed, widget_config)


def render_cameras_widget(data: dict, _components: list[dict]) -> list[dict]:
    """Widget-level code transform for initial render."""
    parsed = data if isinstance(data, dict) else {}
    widget_config = parsed.get("widget_config") if isinstance(parsed, dict) else {}
    widget_config = widget_config if isinstance(widget_config, dict) else {}
    shaped = _reshape_cameras(parsed, widget_config)

    if shaped.get("error"):
        return [{"type": "status", "text": shaped["error"], "color": "danger"}]

    if not shaped["has_cameras"]:
        return [{"type": "text", "content": "No cameras configured.", "style": "muted"}]

    return [
        {"type": "status", "text": shaped["summary"], "color": "info"},
        {"type": "tiles", "items": shaped["tiles"], "min_width": 280},
    ]
