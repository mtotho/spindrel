"""Bot tool: pin_suite — atomically pin every member of a widget suite
onto a dashboard.

A widget *suite* is a group of bundles that share a SQLite DB (see
``app/services/widget_suite.py``). The default suite ships with the
server is ``mission-control`` (Timeline + Kanban + Tasks). Use
``list_suites`` to discover what's available.

The suite members land on the dashboard in grid order via
``_default_grid_layout``, appending below anything that's already there.
Users drag to rearrange. Scope is the dashboard — two pins of the same
member on different dashboards see different data; every pin on the same
dashboard shares one DB.
"""
from __future__ import annotations

import json
import logging

from app.agent.context import current_bot_id, current_channel_id
from app.tools.registry import register

logger = logging.getLogger(__name__)


_PIN_SUITE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "pin_suite",
        "description": (
            "Atomically pin every member of a widget suite onto a "
            "dashboard. Call `list_suites` first to discover suite_ids and "
            "their members. By default pins to the current channel's "
            "dashboard (scope = that channel); pass an explicit "
            "`dashboard_key` to pin to a global dashboard (scope = that "
            "dashboard). All pins land in the grid zone, appending below "
            "existing pins."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "suite_id": {
                    "type": "string",
                    "description": (
                        "Suite slug (e.g. 'mission-control'). Must be a "
                        "known suite from `list_suites`."
                    ),
                },
                "dashboard_key": {
                    "type": "string",
                    "description": (
                        "Optional. Dashboard slug to pin onto. Defaults to "
                        "the current channel's dashboard "
                        "('channel:<channel_id>'). Pass 'default' or any "
                        "other global dashboard slug to pin there instead."
                    ),
                },
                "members": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional. Narrow to a subset of suite members "
                        "(e.g. ['mc_kanban', 'mc_tasks'] to skip the "
                        "timeline). Defaults to the full member list."
                    ),
                },
            },
            "required": ["suite_id"],
        },
    },
}


_LIST_SUITES_SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_suites",
        "description": (
            "List every widget suite installed on this server. Each suite "
            "ships one or more bundled widgets that share a dashboard-"
            "scoped SQLite DB."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}


_PIN_SUITE_RETURNS = {
    "type": "object",
    "properties": {
        "llm": {"type": "string"},
        "suite_id": {"type": "string"},
        "dashboard_key": {"type": "string"},
        "pin_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
        "error": {"type": "string"},
    },
}


_LIST_SUITES_RETURNS = {
    "type": "object",
    "properties": {
        "llm": {"type": "string"},
        "suites": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "suite_id": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "members": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "error": {"type": "string"},
    },
}


@register(
    _LIST_SUITES_SCHEMA,
    safety_tier="readonly",
    returns=_LIST_SUITES_RETURNS,
)
async def list_suites() -> str:
    from app.services.widget_suite import scan_suites

    suites = scan_suites()
    out = {
        "suites": [
            {
                "suite_id": s.suite_id,
                "name": s.name,
                "description": s.description,
                "members": s.members,
            }
            for s in suites
        ],
    }
    out["llm"] = (
        "Installed widget suites:\n" + "\n".join(
            f"- {s['suite_id']}: {s['name']} — members: {', '.join(s['members'])}"
            for s in out["suites"]
        )
        if out["suites"]
        else "No widget suites installed."
    )
    return json.dumps(out)


@register(
    _PIN_SUITE_SCHEMA,
    safety_tier="mutating",
    requires_bot_context=True,
    returns=_PIN_SUITE_RETURNS,
)
async def pin_suite(
    suite_id: str,
    dashboard_key: str | None = None,
    members: list[str] | None = None,
) -> str:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.db.engine import async_session
    from app.services.dashboard_pins import create_suite_pins
    from app.services.widget_suite import load_suite

    suite = load_suite(suite_id)
    if suite is None:
        return json.dumps({
            "error": f"Unknown suite: {suite_id!r}. Call list_suites to see installed suites.",
            "llm": f"pin_suite: no suite named {suite_id!r} — nothing to pin.",
        })

    bot_id = current_bot_id.get()
    channel_id = current_channel_id.get()

    # Default scope is the current channel's dashboard. Bots in non-channel
    # contexts must pass dashboard_key explicitly.
    if dashboard_key is None:
        if channel_id is None:
            return json.dumps({
                "error": (
                    "no dashboard_key provided and no channel context — "
                    "pass dashboard_key='default' (or a specific dashboard "
                    "slug) explicitly."
                ),
            })
        dashboard_key = f"channel:{channel_id}"

    async_sess: AsyncSession
    async with async_session() as async_sess:  # type: ignore[assignment]
        try:
            pins = await create_suite_pins(
                async_sess,
                suite_id=suite_id,
                dashboard_key=dashboard_key,
                source_bot_id=bot_id,
                source_channel_id=channel_id,
                member_slugs=members,
            )
        except Exception as exc:
            logger.exception("pin_suite failed")
            return json.dumps({"error": str(exc)})

    pin_ids = [str(p.id) for p in pins]
    pinned_names = [p.display_label or p.id for p in pins]
    return json.dumps({
        "suite_id": suite_id,
        "dashboard_key": dashboard_key,
        "pin_ids": pin_ids,
        "llm": (
            f"Pinned {len(pins)} member(s) of suite {suite_id!r} to "
            f"{dashboard_key}: {', '.join(str(n) for n in pinned_names)}."
        ),
    })
