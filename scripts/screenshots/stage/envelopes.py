"""Realistic native widget envelopes.

Native widgets render from ``{content_type, widget_ref, state, config}`` without
needing a bot API key. Each helper returns the full ``envelope`` dict ready to
POST to ``/api/v1/widgets/dashboard/pins``.

Kept intentionally declarative — one dict per widget — so a future schema drift
is a single PR, not a scavenger hunt.
"""
from __future__ import annotations

from typing import Any

NATIVE_CT = "application/vnd.spindrel.native-app+json"


def native(widget_ref: str, state: dict, *, config: dict | None = None) -> dict[str, Any]:
    env = {
        "content_type": NATIVE_CT,
        "widget_ref": widget_ref,
        "state": state,
    }
    if config is not None:
        env["config"] = config
    return env


def weather_sunny() -> dict[str, Any]:
    return native(
        "core/weather_current",
        {
            "location": "Portland, OR",
            "temp_f": 62,
            "condition": "Partly Cloudy",
            "high_f": 68,
            "low_f": 54,
            "updated_at": "just now",
            "hourly": [
                {"hour": "12 PM", "temp_f": 62, "icon": "sun"},
                {"hour": " 1 PM", "temp_f": 64, "icon": "sun"},
                {"hour": " 2 PM", "temp_f": 66, "icon": "cloud-sun"},
                {"hour": " 3 PM", "temp_f": 67, "icon": "cloud-sun"},
                {"hour": " 4 PM", "temp_f": 65, "icon": "cloud"},
            ],
        },
    )


def frigate_cameras() -> dict[str, Any]:
    return native(
        "core/camera_grid",
        {
            "cameras": [
                {"name": "Front Door", "status": "online", "last_event": "2m ago"},
                {"name": "Back Yard", "status": "online", "last_event": "8m ago"},
                {"name": "Garage", "status": "online", "last_event": "17m ago"},
                {"name": "Driveway", "status": "offline", "last_event": "—"},
            ],
        },
    )


def web_search_panel() -> dict[str, Any]:
    return native(
        "core/search_results",
        {
            "query": "fastapi websocket reconnection",
            "results": [
                {
                    "title": "FastAPI — WebSockets",
                    "url": "https://fastapi.tiangolo.com/advanced/websockets/",
                    "snippet": "Working with WebSockets in FastAPI. Includes connection lifecycle and reconnection patterns.",
                },
                {
                    "title": "Robust WebSocket reconnection strategies",
                    "url": "https://example.com/ws-reconnection",
                    "snippet": "Exponential backoff, jitter, and resubscribe on reconnect. A review of the field.",
                },
                {
                    "title": "Handling WebSocket drops in production",
                    "url": "https://example.com/production-ws",
                    "snippet": "What worked, what didn't, and how we stopped waking up on-call.",
                },
            ],
        },
    )


def image_card() -> dict[str, Any]:
    return native(
        "core/image",
        {
            "src": "https://images.unsplash.com/photo-1502481851512-e9e2529bfbf9?w=640",
            "alt": "Coastal cliffs at sunset",
            "caption": "Generated: coastal cliffs at sunset",
        },
    )


def standing_order_poll() -> dict[str, Any]:
    return native(
        "core/standing_order_native",
        {
            "title": "Watch package tracking",
            "status": "active",
            "strategy": "poll_url",
            "last_checked_at": "3 min ago",
            "next_check_at": "in 12 min",
            "messages": [
                {"at": "08:14", "text": "Created — watching for delivery status"},
                {"at": "09:26", "text": "Status: In transit (Portland, OR)"},
                {"at": "10:41", "text": "Status: Out for delivery"},
            ],
        },
    )


def excalidraw_diagram() -> dict[str, Any]:
    return native(
        "core/image",
        {
            "src": "/api/v1/widget-demo/excalidraw-sample.svg",
            "alt": "System architecture diagram",
            "caption": "Excalidraw: ingestion pipeline",
        },
    )


def html_hero_envelope(bundle_url: str) -> dict[str, Any]:
    """Bot-authored interactive HTML widget envelope.

    The actual HTML is served by the emitting bot's widget bundle. Bundle URL
    lives in ``widget_ref`` for the library-indexed path.
    """
    return {
        "content_type": "application/vnd.spindrel.html+interactive",
        "widget_ref": bundle_url,
        "state": {"heroDemo": True},
    }
