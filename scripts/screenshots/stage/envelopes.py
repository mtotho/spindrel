"""Realistic native widget envelopes.

The server validates native envelopes by extracting ``body.widget_ref`` — so
the ``widget_ref`` must live **inside** ``envelope.body``, not at the top
level. The registered native widget refs are defined in
``app/services/native_app_widgets.py`` (``_REGISTRY``); screenshots only use
those nine.
"""
from __future__ import annotations

from typing import Any

NATIVE_CT = "application/vnd.spindrel.native-app+json"


def native(
    widget_ref: str,
    state: dict,
    *,
    display_label: str | None = None,
    config: dict | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "widget_ref": widget_ref,
        "widget_kind": "native_app",
        "state": state,
    }
    if config is not None:
        body["config"] = config
    if display_label:
        body["display_label"] = display_label
    env: dict[str, Any] = {
        "content_type": NATIVE_CT,
        "body": body,
        "display": "inline",
    }
    if display_label:
        env["display_label"] = display_label
    return env


def notes() -> dict[str, Any]:
    return native(
        "core/notes_native",
        {
            "body": (
                "# Morning brief\n\n"
                "- Review overnight alerts (3 new)\n"
                "- Ship screenshot pipeline to docs\n"
                "- Confirm Frigate camera 4 is back online\n"
            ),
            "updated_at": "just now",
        },
        display_label="Notes",
    )


def todos() -> dict[str, Any]:
    return native(
        "core/todo_native",
        {
            "items": [
                {"id": "t1", "text": "Pull Tuesday's weather report", "done": True},
                {"id": "t2", "text": "Drop stale dashboard pins", "done": True},
                {"id": "t3", "text": "Capture the flagship 8", "done": False},
                {"id": "t4", "text": "Send status to #ops", "done": False},
            ],
            "updated_at": "just now",
        },
        display_label="Todos",
    )


def usage_forecast() -> dict[str, Any]:
    return native(
        "core/usage_forecast_native",
        {"updated_at": "just now"},
        display_label="Usage forecast",
    )


def upcoming_activity() -> dict[str, Any]:
    return native(
        "core/upcoming_activity_native",
        {"updated_at": "just now"},
        display_label="Upcoming activity",
    )


def standing_order_poll() -> dict[str, Any]:
    return native(
        "core/standing_order_native",
        {
            "goal": "Watch package tracking",
            "status": "running",
            "strategy": "poll_url",
            "strategy_args": {"url": "https://example.com/track", "interval_seconds": 900},
            "strategy_state": {"last_status": "In transit"},
            "interval_seconds": 900,
            "iterations": 3,
            "max_iterations": 96,
            "completion": {},
            "log": [
                {"at": "08:14", "text": "Created — watching for delivery status"},
                {"at": "09:26", "text": "Status: In transit (Portland, OR)"},
                {"at": "10:41", "text": "Status: Out for delivery"},
            ],
            "message_on_complete": "Package delivered",
            "owning_bot_id": "",
            "owning_channel_id": "",
            "next_tick_at": "in 12 min",
            "last_tick_at": "3 min ago",
            "terminal_reason": None,
            "updated_at": "just now",
        },
        display_label="Standing order",
    )


def channel_files() -> dict[str, Any]:
    return native(
        "core/channel_files_native",
        {"updated_at": "just now"},
        display_label="Channel files",
    )


def context_tracker() -> dict[str, Any]:
    return native(
        "core/context_tracker",
        {"updated_at": "just now"},
        display_label="Context",
    )


def machine_control() -> dict[str, Any]:
    return native(
        "core/machine_control_native",
        {"updated_at": "just now"},
        display_label="Machine control",
    )


# Back-compat shims for the test + flagship code still calling old names.
def weather_sunny() -> dict[str, Any]:
    return upcoming_activity()


def frigate_cameras() -> dict[str, Any]:
    return channel_files()


def web_search_panel() -> dict[str, Any]:
    return usage_forecast()


def image_card() -> dict[str, Any]:
    return notes()


def excalidraw_diagram() -> dict[str, Any]:
    return todos()


def html_hero_envelope(bundle_url: str) -> dict[str, Any]:
    """Bot-authored interactive HTML widget envelope (used only by hero)."""
    return {
        "content_type": "application/vnd.spindrel.html+interactive",
        "widget_ref": bundle_url,
        "state": {"heroDemo": True},
    }
