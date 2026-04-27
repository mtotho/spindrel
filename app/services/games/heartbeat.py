"""Heartbeat prompt block for active spatial-canvas games.

When a heartbeat fires for a channel whose primary bot is a participant in
any spatial games and hasn't moved this round, append a `[active_games]`
block listing each pending game with its pin id, summarized state, and the
actions available to that bot. The bot then calls ``invoke_widget_action``
to take its turn — exactly the same surface notes/todo widgets use.

This block lives outside the regular `[spatial canvas]` block so that
games can be enabled even when low-level spatial movement isn't.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    WidgetDashboardPin,
    WidgetInstance,
    WorkspaceSpatialNode,
)
from app.services.games import (
    PHASE_PLAYING,
    available_actions_for,
    directive_block,
    is_game_widget,
    localize_for_actor,
    summarize_state_for_prompt,
)
from app.services.dashboards import WORKSPACE_SPATIAL_DASHBOARD_KEY


logger = logging.getLogger(__name__)


async def build_active_games_block(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID | None,
    bot_id: str | None,
) -> str | None:
    """Return a `[active_games]` text block, or None when there's nothing
    pending for this bot. Channel id is unused today (games span the whole
    workspace) but kept on the signature for future per-channel scoping.
    """
    if not bot_id:
        return None

    # Spatial canvas pins now use synthetic per-instance scope_refs so
    # multiple Notes/Todo/Blockyard tiles can coexist. The canonical "is
    # this on the canvas" relationship is the WidgetDashboardPin row on
    # ``workspace:spatial`` — join through it to find game instances.
    instances_stmt = (
        select(WidgetInstance)
        .join(WidgetDashboardPin, WidgetDashboardPin.widget_instance_id == WidgetInstance.id)
        .where(
            WidgetInstance.widget_kind == "native_app",
            WidgetDashboardPin.dashboard_key == WORKSPACE_SPATIAL_DASHBOARD_KEY,
        )
    )
    try:
        instances = list((await db.execute(instances_stmt)).scalars().all())
    except Exception:
        logger.exception("active_games: failed to list spatial widget instances")
        return None

    pending: list[tuple[WidgetInstance, dict[str, Any]]] = []
    for instance in instances:
        if not is_game_widget(instance.widget_ref):
            continue
        state = instance.state or {}
        if state.get("phase") != PHASE_PLAYING:
            continue
        participants = state.get("participants") or []
        if bot_id not in participants:
            continue
        if state.get("last_actor") == bot_id:
            continue
        pending.append((instance, state))

    if not pending:
        return None

    pin_lookup: dict[uuid.UUID, WidgetDashboardPin] = {}
    node_lookup: dict[uuid.UUID, WorkspaceSpatialNode] = {}
    if pending:
        instance_ids = [inst.id for inst, _ in pending]
        pin_rows = list(
            (
                await db.execute(
                    select(WidgetDashboardPin).where(
                        WidgetDashboardPin.widget_instance_id.in_(instance_ids),
                    ),
                )
            )
            .scalars()
            .all(),
        )
        for pin in pin_rows:
            if pin.widget_instance_id is not None:
                pin_lookup[pin.widget_instance_id] = pin
        pin_ids = [pin.id for pin in pin_rows]
        if pin_ids:
            node_rows = list(
                (
                    await db.execute(
                        select(WorkspaceSpatialNode).where(
                            WorkspaceSpatialNode.widget_pin_id.in_(pin_ids),
                        ),
                    )
                )
                .scalars()
                .all(),
            )
            for node in node_rows:
                if node.widget_pin_id is not None:
                    node_lookup[node.widget_pin_id] = node

    lines: list[str] = ["[active_games]"]
    lines.append(
        f"⚠️ It is YOUR TURN in {len(pending)} spatial game(s). You MUST take your "
        f"turn now by calling invoke_widget_action — do not just acknowledge this block.",
    )
    for idx, (instance, state) in enumerate(pending, 1):
        pin = pin_lookup.get(instance.id)
        node = node_lookup.get(pin.id) if pin else None
        widget_ref = instance.widget_ref
        spec_label = (state.get("game_type") or widget_ref.split("/")[-1]).replace("_", " ")
        if node is not None:
            location = f"@ ({node.world_x:.0f}, {node.world_y:.0f})"
        else:
            location = ""
        pin_segment = f"dashboard_pin_id={pin.id}" if pin else "dashboard_pin_id=<missing>"
        header = f"  {idx}. {spec_label.title()} {location} {pin_segment}".rstrip()
        lines.append(header)
        directive_text = directive_block(state)
        if directive_text:
            for line in directive_text.splitlines():
                lines.append(f"     {line}")
        local_hint = localize_for_actor(widget_ref, state, bot_id)
        if local_hint:
            for line in local_hint.splitlines():
                lines.append(f"     {line}")
        digest = summarize_state_for_prompt(widget_ref, state)
        for digest_line in digest.splitlines():
            lines.append(f"     {digest_line}")
        actions = available_actions_for(widget_ref, state, bot_id)
        if actions:
            lines.append(f"     Available actions: {', '.join(actions)}.")
            pin_id_text = str(pin.id) if pin else "<missing>"
            if "place" in actions:
                lines.append(
                    f'     EXAMPLE: invoke_widget_action(dashboard_pin_id="{pin_id_text}", '
                    f'action="place", args={{"x": 3, "y": 5, "z": 0, "type": "wood", '
                    f'"label": "tower base", "reasoning": "starting a tower near center"}}).',
                )
                lines.append(
                    "     Pick coordinates within bounds, choose a block type from the list, "
                    "and CALL the tool now. Build on or beside your last placement; honor the "
                    "directive if one is set.",
                )
            if "add_stanza" in actions:
                lines.append(
                    f'     EXAMPLE: invoke_widget_action(dashboard_pin_id="{pin_id_text}", '
                    f'action="add_stanza", args={{"text": "Marta noticed the salt in '
                    f'its fur looked wrong.", "reasoning": "introduce a clue"}}).',
                )
                lines.append(
                    "     Continue the previous stanza — pick up its tone, advance the "
                    "story, leave a hook for the next player. Honor the directive.",
                )
    lines.append(
        "Take your turn now via invoke_widget_action. Do not wait, do not just describe "
        "what you would do — actually call the tool.",
    )
    return "\n".join(lines)
