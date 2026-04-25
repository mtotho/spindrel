"""Registry + persistence helpers for first-party native app widgets."""
from __future__ import annotations

import copy
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.domain.errors import NotFoundError, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import WidgetDashboardPin, WidgetInstance
from app.services.widget_contracts import build_native_widget_contract, build_widget_presentation


NativeWidgetCronHandler = Callable[[AsyncSession, "WidgetInstance"], Awaitable[None]]


@dataclass(frozen=True)
class NativeWidgetCronSpec:
    """Cron contract for a native widget that ticks on a schedule.

    Only native widgets that declare this on their ``NativeWidgetSpec`` are
    candidates for the native-cron dispatcher in ``widget_cron.py``. The
    handler runs under the owning bot scope, can mutate ``instance.state``
    (must call ``flag_modified(instance, "state")``), and is responsible for
    rewriting ``state["next_tick_at"]`` when it wants to run again. Missing
    or past ``next_tick_at`` + ``status == "running"`` is how the scheduler
    knows an instance is due.
    """

    handler: NativeWidgetCronHandler
    default_interval_seconds: int = 60
    max_wall_seconds: float = 2.0


NATIVE_APP_CONTENT_TYPE = "application/vnd.spindrel.native-app+json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class NativeWidgetActionSpec:
    id: str
    description: str
    args_schema: dict[str, Any] = field(default_factory=dict)
    returns_schema: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "description": self.description,
            "args_schema": self.args_schema or {"type": "object", "properties": {}},
        }
        if self.returns_schema:
            data["returns_schema"] = self.returns_schema
        return data


@dataclass(frozen=True)
class NativeWidgetSpec:
    widget_ref: str
    name: str
    display_label: str
    description: str
    icon: str | None = None
    supported_scopes: tuple[str, ...] = ("channel", "dashboard")
    default_config: dict[str, Any] = field(default_factory=dict)
    config_schema: dict[str, Any] | None = None
    layout_hints: dict[str, Any] | None = None
    default_state: dict[str, Any] = field(default_factory=dict)
    actions: tuple[NativeWidgetActionSpec, ...] = ()
    context_export: dict[str, Any] | None = None
    presentation_family: str = "card"
    panel_title: str | None = None
    show_panel_title: bool | None = None
    catalog_visible: bool = True
    cron: NativeWidgetCronSpec | None = None

    def catalog_entry(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "scope": "core",
            "format": "native_app",
            "widget_kind": "native_app",
            "widget_binding": "standalone",
            "theme_support": "none",
            "display_label": self.display_label,
            "description": self.description,
            "icon": self.icon,
            "presentation_family": self.presentation_family,
            "panel_title": self.panel_title,
            "show_panel_title": self.show_panel_title,
            "widget_ref": self.widget_ref,
            "actions": [action.as_dict() for action in self.actions],
            "supported_scopes": list(self.supported_scopes),
            "config_schema": copy.deepcopy(
                self.config_schema
                if self.config_schema is not None
                else {"type": "object", "properties": {}}
            ),
            "layout_hints": copy.deepcopy(self.layout_hints),
            "widget_presentation": build_widget_presentation(
                presentation_family=self.presentation_family,
                panel_title=self.panel_title,
                show_panel_title=self.show_panel_title,
                layout_hints=self.layout_hints,
            ),
            "widget_contract": build_native_widget_contract(
                actions=[action.as_dict() for action in self.actions],
                supported_scopes=self.supported_scopes,
                layout_hints=self.layout_hints,
                context_export=self.context_export,
                instantiation_kind="native_catalog",
            ),
            "context_export": copy.deepcopy(self.context_export),
        }


_NOTES_ACTIONS = (
    NativeWidgetActionSpec(
        id="replace_body",
        description="Replace the full note body with new markdown/plain text content.",
        args_schema={
            "type": "object",
            "properties": {
                "body": {
                    "type": "string",
                    "description": "Full note body to save.",
                },
            },
            "required": ["body"],
        },
        returns_schema={
            "type": "object",
            "properties": {
                "body": {"type": "string"},
                "updated_at": {"type": "string"},
            },
            "required": ["body", "updated_at"],
        },
    ),
    NativeWidgetActionSpec(
        id="append_text",
        description="Append text to the end of the current note body.",
        args_schema={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to append to the note body.",
                },
            },
            "required": ["text"],
        },
        returns_schema={
            "type": "object",
            "properties": {
                "body": {"type": "string"},
                "updated_at": {"type": "string"},
            },
            "required": ["body", "updated_at"],
        },
    ),
    NativeWidgetActionSpec(
        id="clear",
        description="Clear the note body.",
        args_schema={"type": "object", "properties": {}},
        returns_schema={
            "type": "object",
            "properties": {"cleared": {"type": "boolean"}},
            "required": ["cleared"],
        },
    ),
)

_TODO_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "title": {"type": "string"},
        "done": {"type": "boolean"},
        "position": {"type": "integer"},
        "created_at": {"type": "string"},
        "updated_at": {"type": "string"},
    },
    "required": ["id", "title", "done", "position", "created_at", "updated_at"],
}

_TODO_COUNTS_SCHEMA = {
    "type": "object",
    "properties": {
        "total": {"type": "integer"},
        "open": {"type": "integer"},
        "completed": {"type": "integer"},
    },
    "required": ["total", "open", "completed"],
}

_TODO_ACTIONS = (
    NativeWidgetActionSpec(
        id="add_item",
        description="Add a new open todo item to the list.",
        args_schema={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Todo text to add.",
                },
            },
            "required": ["title"],
        },
        returns_schema={
            "type": "object",
            "properties": {
                "item": _TODO_ITEM_SCHEMA,
                "counts": _TODO_COUNTS_SCHEMA,
            },
            "required": ["item", "counts"],
        },
    ),
    NativeWidgetActionSpec(
        id="toggle_item",
        description="Toggle a todo item's done state, or force it with `done`.",
        args_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Todo item id."},
                "done": {
                    "type": "boolean",
                    "description": "Optional explicit done state. Omit to flip the current value.",
                },
            },
            "required": ["id"],
        },
        returns_schema={
            "type": "object",
            "properties": {
                "item": _TODO_ITEM_SCHEMA,
                "counts": _TODO_COUNTS_SCHEMA,
            },
            "required": ["item", "counts"],
        },
    ),
    NativeWidgetActionSpec(
        id="rename_item",
        description="Rename an existing todo item.",
        args_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Todo item id."},
                "title": {"type": "string", "description": "New todo title."},
            },
            "required": ["id", "title"],
        },
        returns_schema={
            "type": "object",
            "properties": {"item": _TODO_ITEM_SCHEMA},
            "required": ["item"],
        },
    ),
    NativeWidgetActionSpec(
        id="delete_item",
        description="Delete a todo item entirely.",
        args_schema={
            "type": "object",
            "properties": {"id": {"type": "string", "description": "Todo item id."}},
            "required": ["id"],
        },
        returns_schema={
            "type": "object",
            "properties": {
                "deleted": {"type": "boolean"},
                "id": {"type": "string"},
                "counts": _TODO_COUNTS_SCHEMA,
            },
            "required": ["deleted", "id", "counts"],
        },
    ),
    NativeWidgetActionSpec(
        id="reorder_items",
        description="Reorder the open todo lane using the complete ordered id list.",
        args_schema={
            "type": "object",
            "properties": {
                "ordered_ids": {
                    "type": "array",
                    "description": "Ordered ids for every open todo item.",
                },
            },
            "required": ["ordered_ids"],
        },
        returns_schema={
            "type": "object",
            "properties": {
                "items": {"type": "array", "items": _TODO_ITEM_SCHEMA},
                "counts": _TODO_COUNTS_SCHEMA,
            },
            "required": ["items", "counts"],
        },
    ),
    NativeWidgetActionSpec(
        id="clear_completed",
        description="Delete every completed todo item.",
        args_schema={"type": "object", "properties": {}},
        returns_schema={
            "type": "object",
            "properties": {
                "cleared": {"type": "integer"},
                "items": {"type": "array", "items": _TODO_ITEM_SCHEMA},
                "counts": _TODO_COUNTS_SCHEMA,
            },
            "required": ["cleared", "items", "counts"],
        },
    ),
)

_PINNED_FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "pinned_at": {"type": "string"},
        "pinned_by": {"type": "string"},
    },
    "required": ["path", "pinned_at", "pinned_by"],
}

_PINNED_FILES_ACTIONS = (
    NativeWidgetActionSpec(
        id="set_active_path",
        description="Switch the currently previewed pinned file.",
        args_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Pinned file path to focus.",
                },
            },
            "required": ["path"],
        },
        returns_schema={
            "type": "object",
            "properties": {
                "active_path": {"type": "string"},
            },
            "required": ["active_path"],
        },
    ),
    NativeWidgetActionSpec(
        id="unpin_path",
        description="Remove a file from the pinned-files list.",
        args_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Pinned file path to remove.",
                },
            },
            "required": ["path"],
        },
        returns_schema={
            "type": "object",
            "properties": {
                "removed": {"type": "boolean"},
                "path": {"type": "string"},
                "active_path": {"type": ["string", "null"]},
                "pinned_files": {"type": "array", "items": _PINNED_FILE_SCHEMA},
            },
            "required": ["removed", "path", "active_path", "pinned_files"],
        },
    ),
)


def _standing_order_cron_spec() -> "NativeWidgetCronSpec":
    # Lazy to avoid importing ``standing_orders`` at module load — the
    # registry is evaluated at import time, but cron dispatch is a runtime
    # concern. Standing Orders imports ``native_app_widgets`` lazily, so
    # top-level symmetry isn't free; keep the import here.
    from app.services.standing_orders import on_tick as _standing_order_on_tick

    return NativeWidgetCronSpec(handler=_standing_order_on_tick, default_interval_seconds=60)


_STANDING_ORDER_ACTIONS = (
    NativeWidgetActionSpec(
        id="pause",
        description="Pause a running standing order. Its cron stops firing until resumed.",
        args_schema={"type": "object", "properties": {}},
        returns_schema={
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"],
        },
    ),
    NativeWidgetActionSpec(
        id="resume",
        description="Resume a paused standing order. Reschedules the next tick.",
        args_schema={"type": "object", "properties": {}},
        returns_schema={
            "type": "object",
            "properties": {"status": {"type": "string"}, "next_tick_at": {"type": ["string", "null"]}},
            "required": ["status"],
        },
    ),
    NativeWidgetActionSpec(
        id="cancel",
        description="Cancel a standing order. Terminal — it will not tick again.",
        args_schema={"type": "object", "properties": {}},
        returns_schema={
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"],
        },
    ),
    NativeWidgetActionSpec(
        id="edit_goal",
        description="Rewrite the human-readable goal shown on the tile.",
        args_schema={
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "New goal text."},
            },
            "required": ["goal"],
        },
        returns_schema={
            "type": "object",
            "properties": {"goal": {"type": "string"}},
            "required": ["goal"],
        },
    ),
)


def _ecosystem_default_state() -> dict[str, Any]:
    # Lazy import — `app.services.games.ecosystem` itself imports this module
    # for the `register_game` registry, so a top-level import would cycle.
    from app.services.games.ecosystem import default_state

    return default_state()


def _blockyard_default_state() -> dict[str, Any]:
    from app.services.games.blockyard import default_state

    return default_state()


_ECOSYSTEM_REASONING_FIELD = {
    "reasoning": {
        "type": "string",
        "description": (
            "One short sentence explaining your move. Visible in the turn "
            "log to other participants — make it interesting."
        ),
    },
}


_ECOSYSTEM_ACTIONS = (
    NativeWidgetActionSpec(
        id="define_species",
        description=(
            "Define your species and claim a starting cell. Setup phase only. "
            "Pick an emoji avatar, a hex color, and up to 3 traits from: "
            "aggressive, fast, slow, photosynthetic, parasitic, thorny, burrowing, luminous."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "emoji": {"type": "string"},
                "color": {"type": "string", "description": "Hex color like #7aa2c8."},
                "traits": {"type": "array", "items": {"type": "string"}},
                **_ECOSYSTEM_REASONING_FIELD,
            },
        },
    ),
    NativeWidgetActionSpec(
        id="expand",
        description=(
            "Spread into an adjacent empty cell. Costs 1 food. Defaults from "
            "your most recently claimed cell unless you specify `from`."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["north", "south", "east", "west"],
                },
                "from": {
                    "type": "object",
                    "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
                },
                **_ECOSYSTEM_REASONING_FIELD,
            },
            "required": ["direction"],
        },
    ),
    NativeWidgetActionSpec(
        id="evolve_trait",
        description="Add or remove a trait. Max 3 traits at any time.",
        args_schema={
            "type": "object",
            "properties": {
                "op": {"type": "string", "enum": ["add", "remove"]},
                "trait": {"type": "string"},
                **_ECOSYSTEM_REASONING_FIELD,
            },
            "required": ["op", "trait"],
        },
    ),
    NativeWidgetActionSpec(
        id="eat_neighbor",
        description=(
            "Claim an adjacent enemy cell. Requires the 'aggressive' trait. "
            "Transfers half their food to you."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                **_ECOSYSTEM_REASONING_FIELD,
            },
            "required": ["x", "y"],
        },
    ),
    NativeWidgetActionSpec(
        id="set_participants",
        description="User-only: rewrite the participant bot list.",
        args_schema={
            "type": "object",
            "properties": {
                "bot_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["bot_ids"],
        },
    ),
    NativeWidgetActionSpec(
        id="set_phase",
        description="User-only: transition between setup, playing, and ended.",
        args_schema={
            "type": "object",
            "properties": {
                "phase": {"type": "string", "enum": ["setup", "playing", "ended"]},
            },
            "required": ["phase"],
        },
    ),
    NativeWidgetActionSpec(
        id="set_environment",
        description="User-only: change weather and place food sources.",
        args_schema={
            "type": "object",
            "properties": {
                "weather": {"type": "string", "enum": ["neutral", "drought", "flood", "bloom"]},
                "food_sources": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "integer"},
                            "y": {"type": "integer"},
                            "amount": {"type": "integer"},
                        },
                        "required": ["x", "y"],
                    },
                },
            },
        },
    ),
    NativeWidgetActionSpec(
        id="advance_round",
        description=(
            "User-only: bump the round counter and apply weather + food source effects. "
            "Drought halves food; bloom doubles; food sources grant their owner +amount. "
            "Photosynthetic species harvest sunlight; parasitic species leech 1 food per "
            "adjacent enemy."
        ),
        args_schema={"type": "object", "properties": {}},
    ),
    NativeWidgetActionSpec(
        id="feed_species",
        description=(
            "User-only: directly grant (or take) food from a species. Useful when a "
            "species gets stomped early and needs help — or when one is running away "
            "with the game and needs a cap."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "bot_id": {"type": "string"},
                "amount": {"type": "integer"},
            },
            "required": ["bot_id", "amount"],
        },
    ),
)


_BLOCKYARD_REASONING_FIELD = {
    "reasoning": {
        "type": "string",
        "description": (
            "One short sentence explaining your move. Visible in the turn "
            "log to other participants — what are you building?"
        ),
    },
}


_BLOCKYARD_BLOCK_TYPES = (
    "stone",
    "wood",
    "glass",
    "dirt",
    "water",
    "wool",
    "light",
    "leaves",
    "sand",
    "brick",
)


_BLOCKYARD_ACTIONS = (
    NativeWidgetActionSpec(
        id="place",
        description=(
            "Place one block at (x, y, z). You have an unlimited palette — "
            "any block type, any empty cell within bounds, every turn. "
            "Optionally label it (e.g. 'doorframe', 'roof', 'lantern')."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "z": {"type": "integer"},
                "type": {"type": "string", "enum": list(_BLOCKYARD_BLOCK_TYPES)},
                "label": {"type": "string", "description": "Optional short label for this block."},
                **_BLOCKYARD_REASONING_FIELD,
            },
            "required": ["x", "y", "z", "type"],
        },
    ),
    NativeWidgetActionSpec(
        id="remove",
        description=(
            "Break the block at (x, y, z) — yours or anyone else's. "
            "Counts as your move for this turn."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "z": {"type": "integer"},
                **_BLOCKYARD_REASONING_FIELD,
            },
            "required": ["x", "y", "z"],
        },
    ),
    NativeWidgetActionSpec(
        id="inspect",
        description=(
            "Read what (if anything) occupies (x, y, z). Free — does not "
            "consume your turn."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "z": {"type": "integer"},
            },
            "required": ["x", "y", "z"],
        },
    ),
    NativeWidgetActionSpec(
        id="set_participants",
        description="User-only: rewrite the participant bot list.",
        args_schema={
            "type": "object",
            "properties": {
                "bot_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["bot_ids"],
        },
    ),
    NativeWidgetActionSpec(
        id="set_phase",
        description="User-only: transition between setup, playing, and ended.",
        args_schema={
            "type": "object",
            "properties": {
                "phase": {"type": "string", "enum": ["setup", "playing", "ended"]},
            },
            "required": ["phase"],
        },
    ),
    NativeWidgetActionSpec(
        id="set_player_color",
        description=(
            "User-only: change a player's display color (hex). Cosmetic — "
            "does not affect gameplay."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "bot_id": {"type": "string"},
                "color": {"type": "string", "description": "Hex like #c8a45a."},
            },
            "required": ["bot_id", "color"],
        },
    ),
    NativeWidgetActionSpec(
        id="advance_round",
        description=(
            "User-only: bump the round counter. Skips any participant who "
            "hasn't moved this round — no penalty, they get a fresh turn."
        ),
        args_schema={"type": "object", "properties": {}},
    ),
    NativeWidgetActionSpec(
        id="clear_blocks",
        description=(
            "User-only: wipe all blocks. Keeps participants and turn log."
        ),
        args_schema={"type": "object", "properties": {}},
    ),
)


_REGISTRY: dict[str, NativeWidgetSpec] = {
    "core/game_blockyard": NativeWidgetSpec(
        widget_ref="core/game_blockyard",
        name="game_blockyard",
        display_label="Blockyard",
        description=(
            "Async collaborative voxel-stacking on a shared 3D grid. Each "
            "bot places blocks every turn — towers, gardens, bridges, "
            "whatever fits their personality. The user plays alongside."
        ),
        icon="boxes",
        supported_scopes=("dashboard",),
        layout_hints={"preferred_zone": "grid", "min_cells": {"w": 6, "h": 6}, "max_cells": {"w": 12, "h": 12}},
        default_state=_blockyard_default_state(),
        actions=_BLOCKYARD_ACTIONS,
        context_export={"enabled": False, "summary_kind": "native_state", "hint_kind": "none"},
        panel_title="Blockyard",
        show_panel_title=True,
    ),
    "core/game_ecosystem": NativeWidgetSpec(
        widget_ref="core/game_ecosystem",
        name="game_ecosystem",
        display_label="Ecosystem Sim",
        description=(
            "Async turn-based ecosystem on a tiny floating asteroid. Each bot "
            "owns a species; the user plays the environment layer (weather, "
            "food sources). Bots take turns at heartbeat — expand, evolve, eat."
        ),
        icon="bug",
        supported_scopes=("dashboard",),
        layout_hints={"preferred_zone": "grid", "min_cells": {"w": 6, "h": 6}, "max_cells": {"w": 12, "h": 12}},
        default_state=_ecosystem_default_state(),
        actions=_ECOSYSTEM_ACTIONS,
        context_export={"enabled": False, "summary_kind": "native_state", "hint_kind": "none"},
        panel_title="Ecosystem Sim",
        show_panel_title=True,
    ),
    "core/notes_native": NativeWidgetSpec(
        widget_ref="core/notes_native",
        name="notes_native",
        display_label="Notes",
        description="First-party native notes widget with persistent state and bot-callable actions.",
        icon="notebook-pen",
        supported_scopes=("channel", "dashboard"),
        layout_hints={"preferred_zone": "grid", "min_cells": {"w": 6, "h": 4}, "max_cells": {"w": 12, "h": 10}},
        default_state={
            "body": "",
            "created_at": "",
            "updated_at": "",
        },
        actions=_NOTES_ACTIONS,
        context_export={"enabled": True, "summary_kind": "native_state", "hint_kind": "invoke_widget_action"},
        panel_title="Notes",
        show_panel_title=True,
    ),
    "core/todo_native": NativeWidgetSpec(
        widget_ref="core/todo_native",
        name="todo_native",
        display_label="Todo",
        description="First-party native todo widget with persistent task state and bot-callable actions.",
        icon="check-square",
        supported_scopes=("channel", "dashboard"),
        layout_hints={"preferred_zone": "grid", "min_cells": {"w": 4, "h": 3}, "max_cells": {"w": 12, "h": 8}},
        default_state={
            "items": [],
            "created_at": "",
            "updated_at": "",
        },
        actions=_TODO_ACTIONS,
        context_export={"enabled": True, "summary_kind": "native_state", "hint_kind": "invoke_widget_action"},
        panel_title="Todo",
        show_panel_title=True,
    ),
    "core/context_tracker": NativeWidgetSpec(
        widget_ref="core/context_tracker",
        name="context_tracker",
        display_label="Context tracker",
        description="First-party native channel context tracker with live budget and compaction status.",
        icon="gauge",
        supported_scopes=("channel",),
        layout_hints={"preferred_zone": "header", "min_cells": {"w": 6, "h": 2}, "max_cells": {"w": 12, "h": 2}},
        default_state={
            "created_at": "",
            "updated_at": "",
        },
        actions=(),
        context_export={"enabled": True, "summary_kind": "server_provider", "hint_kind": "none"},
        panel_title="Context tracker",
        show_panel_title=True,
    ),
    "core/usage_forecast_native": NativeWidgetSpec(
        widget_ref="core/usage_forecast_native",
        name="usage_forecast_native",
        display_label="Usage forecast",
        description="First-party native global usage forecast with compact activity charting.",
        icon="chart-column",
        supported_scopes=("channel", "dashboard"),
        layout_hints={"preferred_zone": "grid", "min_cells": {"w": 4, "h": 2}, "max_cells": {"w": 12, "h": 6}},
        default_state={
            "created_at": "",
            "updated_at": "",
        },
        actions=(),
        context_export={"enabled": True, "summary_kind": "server_provider", "hint_kind": "none"},
        panel_title="Usage forecast",
        show_panel_title=True,
    ),
    "core/channel_files_native": NativeWidgetSpec(
        widget_ref="core/channel_files_native",
        name="channel_files_native",
        display_label="Channel files",
        description="First-party native channel file browser with recent activity and drag-drop upload.",
        icon="folder-tree",
        supported_scopes=("channel",),
        layout_hints={"preferred_zone": "grid", "min_cells": {"w": 6, "h": 4}, "max_cells": {"w": 12, "h": 10}},
        default_state={
            "created_at": "",
            "updated_at": "",
        },
        actions=(),
        context_export={"enabled": False, "summary_kind": "server_provider", "hint_kind": "none"},
        panel_title="Channel files",
        show_panel_title=True,
    ),
    "core/pinned_files_native": NativeWidgetSpec(
        widget_ref="core/pinned_files_native",
        name="pinned_files_native",
        display_label="Pinned files",
        description="First-party native channel widget for channel-scoped pinned file previews.",
        icon="panel-right-dashed",
        supported_scopes=("channel",),
        layout_hints={"preferred_zone": "grid", "min_cells": {"w": 6, "h": 4}, "max_cells": {"w": 12, "h": 10}},
        default_state={
            "pinned_files": [],
            "active_path": None,
            "created_at": "",
            "updated_at": "",
        },
        actions=_PINNED_FILES_ACTIONS,
        context_export={"enabled": True, "summary_kind": "native_state", "hint_kind": "invoke_widget_action"},
        panel_title="Pinned files",
        show_panel_title=True,
        catalog_visible=False,
    ),
    "core/upcoming_activity_native": NativeWidgetSpec(
        widget_ref="core/upcoming_activity_native",
        name="upcoming_activity_native",
        display_label="Upcoming activity",
        description="First-party native schedule window for upcoming heartbeats, tasks, and dreaming runs.",
        icon="calendar-range",
        supported_scopes=("channel", "dashboard"),
        layout_hints={"preferred_zone": "grid", "min_cells": {"w": 4, "h": 2}, "max_cells": {"w": 12, "h": 6}},
        default_state={
            "created_at": "",
            "updated_at": "",
        },
        actions=(),
        context_export={"enabled": True, "summary_kind": "server_provider", "hint_kind": "none"},
        panel_title="Upcoming activity",
        show_panel_title=True,
    ),
    "core/machine_control_native": NativeWidgetSpec(
        widget_ref="core/machine_control_native",
        name="machine_control_native",
        display_label="Machine control",
        description="First-party native session-scoped machine lease and target control surface.",
        icon="monitor-cog",
        supported_scopes=("channel",),
        layout_hints={"preferred_zone": "dock", "min_cells": {"w": 4, "h": 3}, "max_cells": {"w": 12, "h": 6}},
        default_state={
            "created_at": "",
            "updated_at": "",
        },
        actions=(),
        context_export={"enabled": False, "summary_kind": "server_provider", "hint_kind": "none"},
        panel_title="Machine control",
        show_panel_title=True,
    ),
    "core/standing_order_native": NativeWidgetSpec(
        widget_ref="core/standing_order_native",
        name="standing_order_native",
        display_label="Standing order",
        description=(
            "A bot-spawned durable work item that ticks on a schedule. Watches, polls, "
            "or waits without consuming an LLM turn per tick, and pings back in chat "
            "when it completes. Cancellable by the channel owner at any time."
        ),
        icon="alarm-clock",
        supported_scopes=("channel", "dashboard"),
        layout_hints={"preferred_zone": "grid", "min_cells": {"w": 4, "h": 3}, "max_cells": {"w": 8, "h": 6}},
        default_state={
            "goal": "",
            "status": "running",
            "strategy": "timer",
            "strategy_args": {},
            "strategy_state": {},
            "interval_seconds": 60,
            "iterations": 0,
            "max_iterations": 1000,
            "completion": {},
            "log": [],
            "message_on_complete": None,
            "owning_bot_id": "",
            "owning_channel_id": "",
            "created_at": "",
            "updated_at": "",
            "next_tick_at": None,
            "last_tick_at": None,
            "terminal_reason": None,
        },
        actions=_STANDING_ORDER_ACTIONS,
        context_export={"enabled": True, "summary_kind": "native_state", "hint_kind": "invoke_widget_action"},
        panel_title="Standing order",
        show_panel_title=True,
        cron=_standing_order_cron_spec(),
    ),
}


def list_native_widget_catalog_entries() -> list[dict[str, Any]]:
    return [spec.catalog_entry() for spec in _REGISTRY.values() if spec.catalog_visible]


def get_native_widget_spec(widget_ref: str) -> NativeWidgetSpec | None:
    return _REGISTRY.get(widget_ref)


def get_native_widget_actions(widget_ref: str) -> list[dict[str, Any]]:
    spec = get_native_widget_spec(widget_ref)
    if spec is None:
        return []
    return [action.as_dict() for action in spec.actions]


def _scope_for_dashboard(
    dashboard_key: str,
    source_channel_id: uuid.UUID | None,
) -> tuple[str, str]:
    if dashboard_key.startswith("channel:") and source_channel_id is not None:
        return "channel", str(source_channel_id)
    return "dashboard", dashboard_key


def _merge_defaults(
    defaults: dict[str, Any],
    override: dict[str, Any] | None,
) -> dict[str, Any]:
    data = copy.deepcopy(defaults)
    if override:
        data.update(copy.deepcopy(override))
    return data


def build_native_widget_preview_envelope(
    widget_ref: str,
    *,
    display_label: str | None = None,
    state: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    widget_instance_id: uuid.UUID | str | None = None,
    source_bot_id: str | None = None,
) -> dict[str, Any]:
    spec = get_native_widget_spec(widget_ref)
    if spec is None:
        raise NotFoundError(f"Unknown native widget: {widget_ref!r}")
    body = {
        "widget_ref": widget_ref,
        "widget_kind": "native_app",
        "display_label": display_label or spec.display_label,
        "state": _merge_defaults(spec.default_state, state),
        "config": _merge_defaults(spec.default_config, config),
        "actions": [action.as_dict() for action in spec.actions],
    }
    if widget_instance_id is not None:
        body["widget_instance_id"] = str(widget_instance_id)
    return {
        "content_type": NATIVE_APP_CONTENT_TYPE,
        "body": body,
        "plain_body": spec.description,
        "display": "inline",
        "display_label": display_label or spec.display_label,
        "source_bot_id": source_bot_id,
        "presentation_family": spec.presentation_family,
        "panel_title": spec.panel_title,
        "show_panel_title": spec.show_panel_title,
    }


async def get_or_create_native_widget_instance(
    db: AsyncSession,
    *,
    widget_ref: str,
    dashboard_key: str,
    source_channel_id: uuid.UUID | None,
    config: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
) -> WidgetInstance:
    spec = get_native_widget_spec(widget_ref)
    if spec is None:
        raise NotFoundError(f"Unknown native widget: {widget_ref!r}")
    scope_kind, scope_ref = _scope_for_dashboard(dashboard_key, source_channel_id)
    if scope_kind not in spec.supported_scopes:
        raise ValidationError(
            f"Native widget {widget_ref!r} does not support scope {scope_kind!r}",
        )

    existing = (
        await db.execute(
            select(WidgetInstance).where(
                WidgetInstance.widget_kind == "native_app",
                WidgetInstance.widget_ref == widget_ref,
                WidgetInstance.scope_kind == scope_kind,
                WidgetInstance.scope_ref == scope_ref,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if config:
            existing.config = _merge_defaults(existing.config or {}, config)
            flag_modified(existing, "config")
        if state:
            existing.state = _merge_defaults(existing.state or {}, state)
            flag_modified(existing, "state")
        return existing

    merged_state = _merge_defaults(spec.default_state, state)
    merged_config = _merge_defaults(spec.default_config, config)
    if not merged_state.get("created_at"):
        merged_state["created_at"] = _now_iso()
    if not merged_state.get("updated_at"):
        merged_state["updated_at"] = merged_state["created_at"]
    instance = WidgetInstance(
        widget_kind="native_app",
        widget_ref=widget_ref,
        scope_kind=scope_kind,
        scope_ref=scope_ref,
        config=merged_config,
        state=merged_state,
    )
    db.add(instance)
    await db.flush()
    return instance


def build_envelope_for_native_instance(
    instance: WidgetInstance,
    *,
    display_label: str | None = None,
    source_bot_id: str | None = None,
) -> dict[str, Any]:
    return build_native_widget_preview_envelope(
        instance.widget_ref,
        display_label=display_label,
        state=instance.state or {},
        config=instance.config or {},
        widget_instance_id=instance.id,
        source_bot_id=source_bot_id,
    )


def _validate_args_against_schema(
    schema: dict[str, Any],
    args: dict[str, Any] | None,
) -> None:
    args = args or {}
    required = schema.get("required") or []
    props = schema.get("properties") or {}
    for key in required:
        if key not in args:
            raise ValidationError(f"Missing required action arg: {key}")
    for key, value in args.items():
        prop = props.get(key)
        if not isinstance(prop, dict):
            continue
        typ = prop.get("type")
        if typ == "string" and not isinstance(value, str):
            raise ValidationError(f"Action arg {key!r} must be a string")
        if typ == "boolean" and not isinstance(value, bool):
            raise ValidationError(f"Action arg {key!r} must be a boolean")
        if typ == "integer" and not (isinstance(value, int) and not isinstance(value, bool)):
            raise ValidationError(f"Action arg {key!r} must be an integer")
        if typ == "number" and not (
            (isinstance(value, int) and not isinstance(value, bool)) or isinstance(value, float)
        ):
            raise ValidationError(f"Action arg {key!r} must be a number")
        if typ == "object" and not isinstance(value, dict):
            raise ValidationError(f"Action arg {key!r} must be an object")
        if typ == "array" and not isinstance(value, list):
            raise ValidationError(f"Action arg {key!r} must be an array")


def _todo_state(instance: WidgetInstance) -> dict[str, Any]:
    state = copy.deepcopy(instance.state or {})
    state.setdefault("items", [])
    state.setdefault("created_at", "")
    state.setdefault("updated_at", "")
    return state


def _serialize_todo_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("id") or ""),
        "title": str(item.get("title") or ""),
        "done": bool(item.get("done")),
        "position": int(item.get("position") or 0),
        "created_at": str(item.get("created_at") or ""),
        "updated_at": str(item.get("updated_at") or ""),
    }


def _normalize_todo_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    open_items = [_serialize_todo_item(item) for item in items if not item.get("done")]
    completed_items = [_serialize_todo_item(item) for item in items if item.get("done")]
    for idx, item in enumerate(open_items):
        item["position"] = idx
    for idx, item in enumerate(completed_items):
        item["position"] = idx
    return open_items + completed_items


def _todo_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    completed = sum(1 for item in items if item["done"])
    total = len(items)
    return {"total": total, "open": total - completed, "completed": completed}


def _pinned_files_state(instance: WidgetInstance) -> dict[str, Any]:
    state = copy.deepcopy(instance.state or {})
    items: list[dict[str, str]] = []
    for item in state.get("pinned_files") or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        items.append(
            {
                "path": path,
                "pinned_at": str(item.get("pinned_at") or ""),
                "pinned_by": str(item.get("pinned_by") or "user"),
            }
        )
    state["pinned_files"] = items
    state["created_at"] = str(state.get("created_at") or "") or _now_iso()
    state["updated_at"] = str(state.get("updated_at") or "") or state["created_at"]
    active_path = str(state.get("active_path") or "").strip() or None
    valid_paths = {item["path"] for item in items}
    if active_path not in valid_paths:
        active_path = items[0]["path"] if items else None
    state["active_path"] = active_path
    return state


def _find_pinned_file(items: list[dict[str, str]], path: str) -> tuple[int, dict[str, str]]:
    for idx, item in enumerate(items):
        if item["path"] == path:
            return idx, item
    raise NotFoundError(f"unknown pinned file path: {path}")


def _require_todo_title(args: dict[str, Any] | None) -> str:
    title = str((args or {}).get("title") or "").strip()
    if not title:
        raise ValidationError("title is required")
    if len(title) > 500:
        raise ValidationError("title is too long (max 500 chars)")
    return title


def _find_todo_item(items: list[dict[str, Any]], item_id: str) -> tuple[int, dict[str, Any]]:
    for idx, item in enumerate(items):
        if item["id"] == item_id:
            return idx, item
    raise NotFoundError(f"unknown todo item id: {item_id}")


async def _dispatch_notes_action(
    db: AsyncSession,
    instance: WidgetInstance,
    action: str,
    args: dict[str, Any] | None,
) -> Any:
    state = copy.deepcopy(instance.state or {})
    body = str(state.get("body") or "")
    created_at = str(state.get("created_at") or "") or _now_iso()
    updated_at = _now_iso()
    if action == "replace_body":
        body = str((args or {}).get("body") or "")
        result: Any = {"body": body, "updated_at": updated_at}
    elif action == "append_text":
        body = body + str((args or {}).get("text") or "")
        result = {"body": body, "updated_at": updated_at}
    elif action == "clear":
        body = ""
        result = {"cleared": True}
    else:
        raise NotFoundError(f"Unsupported native widget action: {action!r}")
    state["body"] = body
    state["created_at"] = created_at
    state["updated_at"] = updated_at
    instance.state = state
    flag_modified(instance, "state")
    await db.flush()
    return result


async def _dispatch_todo_action(
    db: AsyncSession,
    instance: WidgetInstance,
    action: str,
    args: dict[str, Any] | None,
) -> Any:
    state = _todo_state(instance)
    items = _normalize_todo_items(list(state.get("items") or []))
    now = _now_iso()
    created_at = str(state.get("created_at") or "") or now

    if action == "add_item":
        item = {
            "id": str(uuid.uuid4()),
            "title": _require_todo_title(args),
            "done": False,
            "position": sum(1 for existing in items if not existing["done"]),
            "created_at": now,
            "updated_at": now,
        }
        items.append(item)
        items = _normalize_todo_items(items)
        result: Any = {"item": next(entry for entry in items if entry["id"] == item["id"])}
    elif action == "toggle_item":
        item_id = str((args or {}).get("id") or "").strip()
        if not item_id:
            raise ValidationError("id is required")
        idx, current = _find_todo_item(items, item_id)
        next_done = not current["done"] if "done" not in (args or {}) else bool((args or {})["done"])
        current = copy.deepcopy(current)
        current["done"] = next_done
        current["updated_at"] = now
        items[idx] = current
        items = _normalize_todo_items(items)
        result = {"item": next(entry for entry in items if entry["id"] == item_id)}
    elif action == "rename_item":
        item_id = str((args or {}).get("id") or "").strip()
        if not item_id:
            raise ValidationError("id is required")
        title = _require_todo_title(args)
        idx, current = _find_todo_item(items, item_id)
        current = copy.deepcopy(current)
        current["title"] = title
        current["updated_at"] = now
        items[idx] = current
        items = _normalize_todo_items(items)
        result = {"item": next(entry for entry in items if entry["id"] == item_id)}
    elif action == "delete_item":
        item_id = str((args or {}).get("id") or "").strip()
        if not item_id:
            raise ValidationError("id is required")
        idx, _current = _find_todo_item(items, item_id)
        del items[idx]
        items = _normalize_todo_items(items)
        result = {"deleted": True, "id": item_id}
    elif action == "reorder_items":
        ordered_ids = [str(value) for value in ((args or {}).get("ordered_ids") or [])]
        open_items = [item for item in items if not item["done"]]
        completed_items = [item for item in items if item["done"]]
        if ordered_ids != [item["id"] for item in open_items] and set(ordered_ids) != {item["id"] for item in open_items}:
            raise ValidationError("ordered_ids must list each open item exactly once")
        if len(ordered_ids) != len(open_items):
            raise ValidationError("ordered_ids must list each open item exactly once")
        lookup = {item["id"]: item for item in open_items}
        items = [lookup[item_id] for item_id in ordered_ids] + completed_items
        items = _normalize_todo_items(items)
        result = {"items": items}
    elif action == "clear_completed":
        cleared = sum(1 for item in items if item["done"])
        items = [item for item in items if not item["done"]]
        items = _normalize_todo_items(items)
        result = {"cleared": cleared, "items": items}
    else:
        raise NotFoundError(f"Unsupported native widget action: {action!r}")

    state["items"] = items
    state["created_at"] = created_at
    state["updated_at"] = now
    instance.state = state
    flag_modified(instance, "state")
    await db.flush()
    result.setdefault("counts", _todo_counts(items))
    return result


async def _dispatch_pinned_files_action(
    db: AsyncSession,
    instance: WidgetInstance,
    action: str,
    args: dict[str, Any] | None,
) -> Any:
    state = _pinned_files_state(instance)
    items = list(state.get("pinned_files") or [])
    path = str((args or {}).get("path") or "").strip()
    if not path:
        raise ValidationError("path is required")

    if action == "set_active_path":
        _find_pinned_file(items, path)
        state["active_path"] = path
        state["updated_at"] = _now_iso()
        result: Any = {"active_path": path}
    elif action == "unpin_path":
        idx, _ = _find_pinned_file(items, path)
        del items[idx]
        state["pinned_files"] = items
        if state.get("active_path") == path:
            state["active_path"] = items[0]["path"] if items else None
        state["updated_at"] = _now_iso()
        result = {
            "removed": True,
            "path": path,
            "active_path": state.get("active_path"),
            "pinned_files": items,
        }
    else:
        raise NotFoundError(f"Unsupported native widget action: {action!r}")

    instance.state = state
    flag_modified(instance, "state")
    await db.flush()

    if instance.scope_kind == "channel":
        from app.services.pinned_panels import replace_channel_paths

        try:
            replace_channel_paths(
                uuid.UUID(instance.scope_ref),
                [item["path"] for item in state.get("pinned_files") or []],
            )
        except ValueError:
            pass
    return result


async def _dispatch_standing_order_action(
    db: AsyncSession,
    instance: WidgetInstance,
    action: str,
    args: dict[str, Any] | None,
) -> Any:
    state = copy.deepcopy(instance.state or {})
    current_status = str(state.get("status") or "running")
    now = _now_iso()

    if action == "pause":
        if current_status not in ("running", "paused"):
            raise ValidationError(
                f"Cannot pause a standing order in status {current_status!r}",
            )
        state["status"] = "paused"
        state["updated_at"] = now
        result: Any = {"status": "paused"}
    elif action == "resume":
        if current_status != "paused":
            raise ValidationError(
                f"Cannot resume a standing order in status {current_status!r}",
            )
        interval = int(state.get("interval_seconds") or 60)
        next_tick = (datetime.now(timezone.utc) + timedelta(seconds=interval)).isoformat()
        state["status"] = "running"
        state["next_tick_at"] = next_tick
        state["updated_at"] = now
        result = {"status": "running", "next_tick_at": next_tick}
    elif action == "cancel":
        if current_status in ("done", "cancelled", "failed"):
            raise ValidationError(
                f"Standing order is already terminal (status={current_status!r})",
            )
        state["status"] = "cancelled"
        state["next_tick_at"] = None
        state["terminal_reason"] = "cancelled by user"
        state["updated_at"] = now
        result = {"status": "cancelled"}
    elif action == "edit_goal":
        new_goal = str((args or {}).get("goal") or "").strip()
        if not new_goal:
            raise ValidationError("edit_goal requires a non-empty 'goal'")
        if len(new_goal) > 500:
            raise ValidationError("goal must be 500 characters or fewer")
        state["goal"] = new_goal
        state["updated_at"] = now
        result = {"goal": new_goal}
    else:
        raise NotFoundError(f"Unsupported standing order action: {action!r}")

    instance.state = state
    flag_modified(instance, "state")
    await db.flush()
    return result


async def dispatch_native_widget_action(
    db: AsyncSession,
    *,
    instance: WidgetInstance,
    action: str,
    args: dict[str, Any] | None,
    bot_id: str | None = None,
) -> Any:
    spec = get_native_widget_spec(instance.widget_ref)
    if spec is None:
        raise NotFoundError(f"Unknown native widget: {instance.widget_ref!r}")
    action_spec = next((candidate for candidate in spec.actions if candidate.id == action), None)
    if action_spec is None:
        raise NotFoundError(
            f"Unknown action {action!r} for native widget {instance.widget_ref!r}",
        )
    _validate_args_against_schema(action_spec.args_schema, args or {})

    # Spatial-canvas games own their own dispatcher and need to know the
    # caller (bot vs user) to enforce participation and turn order. Route
    # through the games registry so each game's rules stay self-contained.
    from app.services.games import ACTOR_USER, get_dispatcher, is_game_widget

    if is_game_widget(instance.widget_ref):
        dispatcher = get_dispatcher(instance.widget_ref)
        if dispatcher is None:
            raise NotFoundError(
                f"Game widget {instance.widget_ref!r} has no registered dispatcher.",
            )
        actor = bot_id or ACTOR_USER
        return await dispatcher(db, instance, action, args, actor=actor)

    if instance.widget_ref == "core/notes_native":
        return await _dispatch_notes_action(db, instance, action, args)
    if instance.widget_ref == "core/todo_native":
        return await _dispatch_todo_action(db, instance, action, args)
    if instance.widget_ref == "core/pinned_files_native":
        return await _dispatch_pinned_files_action(db, instance, action, args)
    if instance.widget_ref == "core/standing_order_native":
        return await _dispatch_standing_order_action(db, instance, action, args)

    raise NotFoundError(f"No native action dispatcher registered for {instance.widget_ref!r}")


async def get_widget_instance(
    db: AsyncSession,
    widget_instance_id: uuid.UUID | str,
) -> WidgetInstance | None:
    instance_id = widget_instance_id
    if isinstance(instance_id, str):
        instance_id = uuid.UUID(instance_id)
    return await db.get(WidgetInstance, instance_id)


async def get_native_widget_instance_for_pin(
    db: AsyncSession,
    pin: WidgetDashboardPin,
) -> WidgetInstance | None:
    if pin.widget_instance_id is None:
        return None
    return await db.get(WidgetInstance, pin.widget_instance_id)


def pin_supports_native_widget(pin: WidgetDashboardPin | dict[str, Any]) -> bool:
    envelope = pin.envelope if hasattr(pin, "envelope") else (pin.get("envelope") or {})
    return envelope.get("content_type") == NATIVE_APP_CONTENT_TYPE


def extract_native_widget_ref_from_envelope(envelope: dict[str, Any]) -> str | None:
    if envelope.get("content_type") != NATIVE_APP_CONTENT_TYPE:
        return None
    body = envelope.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except Exception:
            return None
    if not isinstance(body, dict):
        return None
    widget_ref = body.get("widget_ref")
    return str(widget_ref) if isinstance(widget_ref, str) and widget_ref else None


def action_manifest_for_pin(
    pin: WidgetDashboardPin | dict[str, Any],
) -> list[dict[str, Any]]:
    envelope = pin.envelope if hasattr(pin, "envelope") else (pin.get("envelope") or {})
    widget_ref = extract_native_widget_ref_from_envelope(envelope)
    if not widget_ref:
        return []
    return get_native_widget_actions(widget_ref)
