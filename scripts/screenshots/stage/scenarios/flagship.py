"""Flagship-8 scenario stager.

Orchestrates bots + channels + pinned widgets + a mid-run pipeline + seeded
usage events so the capture layer can drive every route in one run.

Idempotent end-to-end: stable ``screenshot:*`` client_ids / bot ids / pipeline
titles keep reruns dedupe-safe.
"""
from __future__ import annotations

import json

from . import StagedState
from . import bots as bot_scenarios
from . import dashboards as dashboard_scenarios
from . import pipelines as pipeline_scenarios
from .._exec import run_server_helper
from ..client import SpindrelClient


# State bundles per widget_ref. Native widgets render from
# ``WidgetInstance.state`` on the server, not envelope.state, so we seed this
# directly after pins land.
WIDGET_STATE_SEEDS: dict[str, dict] = {
    "core/notes_native": {
        "body": (
            "# Evening check-in\n\n"
            "- Overnight alerts: 3 resolved, 1 open (camera 4 offline)\n"
            "- Shipped: screenshot pipeline, docs refresh Phase A\n"
            "- Tomorrow: flagship 8 review with the team\n"
        ),
        "updated_at": "2026-04-24T20:15:00Z",
    },
    "core/todo_native": {
        "items": [
            {"id": "t1", "text": "Review overnight alerts", "done": True},
            {"id": "t2", "text": "Bring camera 4 back online", "done": False},
            {"id": "t3", "text": "Ship docs refresh Phase A", "done": False},
            {"id": "t4", "text": "Send ops status to #team", "done": False},
        ],
        "updated_at": "2026-04-24T20:15:00Z",
    },
    "core/standing_order_native": {
        "goal": "Watch for package delivery (Amazon)",
        "status": "running",
        "strategy": "poll_url",
        "strategy_args": {
            "url": "https://www.amazon.com/gp/your-account/order-history",
            "interval_seconds": 900,
        },
        "strategy_state": {"last_status": "Out for delivery"},
        "interval_seconds": 900,
        "iterations": 3,
        "max_iterations": 96,
        "completion": {},
        "log": [
            {"at": "2026-04-24T17:00:00Z", "level": "info", "text": "Started watching order #112-4587"},
            {"at": "2026-04-24T17:45:00Z", "level": "info", "text": "Status: In transit (Portland, OR)"},
            {"at": "2026-04-24T19:30:00Z", "level": "info", "text": "Status: Out for delivery"},
        ],
        "message_on_complete": "Package delivered — ping the bot.",
        "owning_bot_id": "screenshot-orchestrator",
        "owning_channel_id": "",
        "next_tick_at": "2026-04-24T20:30:00Z",
        "last_tick_at": "2026-04-24T20:15:00Z",
        "terminal_reason": None,
        "updated_at": "2026-04-24T20:15:00Z",
    },
}


def _seed_widget_states_for_channel(
    channel_id: str,
    *,
    ssh_alias: str,
    ssh_container: str,
    dry_run: bool = False,
) -> None:
    """Best-effort seeding; missing WidgetInstance rows are skipped silently.

    Only native widgets whose WidgetInstance was created on this channel
    (via pin create) will seed — the helper exits non-zero when the row is
    absent, which is fine if e.g. standing_order_native wasn't pinned here.
    """
    import subprocess

    for widget_ref, state in WIDGET_STATE_SEEDS.items():
        try:
            run_server_helper(
                ssh_alias=ssh_alias,
                container=ssh_container,
                helper_name="seed_widget_instance_state",
                args=[channel_id, widget_ref, json.dumps(state)],
                dry_run=dry_run,
            )
        except RuntimeError as e:
            # Only swallow "not found" — everything else should surface.
            if "not found" in str(e).lower():
                continue
            raise
        except subprocess.CalledProcessError:
            continue


# (name, client_id, category) — `category` is a first-class channel field the
# home grid groups on. Picking a spread of categories showcases the grouping.
HOME_CHANNELS: list[tuple[str, str, str]] = [
    ("Morning briefing", "screenshot:home-1", "Daily"),
    ("Evening check-in", "screenshot:chat-main", "Daily"),
    ("House automation", "screenshot:home-2", "Home"),
    ("Frigate cameras",  "screenshot:home-5", "Home"),
    ("Inbox triage",     "screenshot:home-3", "Work"),
    ("Ops & deploys",    "screenshot:home-4", "Work"),
    ("Pipeline demo",    "screenshot:pipeline-demo", "Work"),
    ("Demo dashboard",   "screenshot:demo-dashboard", "Showcase"),
]

CHAT_MAIN_CLIENT_ID = "screenshot:chat-main"
DEMO_DASHBOARD_CLIENT_ID = "screenshot:demo-dashboard"
PIPELINE_CHANNEL_CLIENT_ID = "screenshot:pipeline-demo"


def stage_flagship(
    client: SpindrelClient,
    *,
    ssh_alias: str,
    ssh_container: str,
    dry_run: bool = False,
) -> StagedState:
    state = StagedState()

    # 1. Bots
    demo_bot_ids = bot_scenarios.ensure_demo_bots(client)
    primary_bot = demo_bot_ids[0]
    state.bots = {
        "primary": primary_bot,
        "researcher": demo_bot_ids[1],
        "ops": demo_bot_ids[2],
    }

    # 2. Home channels (for home.png) — category drives the home-grid grouping.
    # Every flagship channel is routed through this loop so a single rerun
    # reconciles categories across chat_main / demo dashboard / pipeline too.
    home_channel_ids: list[str] = []
    channel_ids_by_client: dict[str, str] = {}
    for name, client_id, category in HOME_CHANNELS:
        ch = client.ensure_channel(
            client_id=client_id,
            bot_id=primary_bot,
            name=name,
            category=category,
        )
        channel_ids_by_client[client_id] = str(ch["id"])
        home_channel_ids.append(str(ch["id"]))
    state.channels["home_list"] = ",".join(home_channel_ids)

    # 3. Chat-main channel (+ 2 rail widgets)
    chat_main_id = channel_ids_by_client[CHAT_MAIN_CLIENT_ID]
    state.channels["chat_main"] = chat_main_id
    dashboard_scenarios.pin_chat_rail_widgets(
        client, channel_id=chat_main_id, source_bot_id=primary_bot
    )
    _seed_widget_states_for_channel(
        chat_main_id, ssh_alias=ssh_alias, ssh_container=ssh_container, dry_run=dry_run
    )
    # Fake chat history so the channel isn't empty on capture.
    run_server_helper(
        ssh_alias=ssh_alias,
        container=ssh_container,
        helper_name="seed_chat_messages",
        args=[chat_main_id, primary_bot],
        dry_run=dry_run,
    )

    # 4. Demo dashboard (6 pins for widget-dashboard.png)
    demo_dashboard_id = channel_ids_by_client[DEMO_DASHBOARD_CLIENT_ID]
    state.channels["demo_dashboard"] = demo_dashboard_id
    dashboard_scenarios.pin_full_dashboard(
        client, channel_id=demo_dashboard_id, source_bot_id=primary_bot
    )
    _seed_widget_states_for_channel(
        demo_dashboard_id, ssh_alias=ssh_alias, ssh_container=ssh_container, dry_run=dry_run
    )

    # 5. Mid-run pipeline channel + task
    pipeline_channel_id = channel_ids_by_client[PIPELINE_CHANNEL_CLIENT_ID]
    state.channels["pipeline"] = pipeline_channel_id
    task_id = pipeline_scenarios.ensure_midrun_pipeline(
        client,
        bot_id=primary_bot,
        channel_id=pipeline_channel_id,
        ssh_alias=ssh_alias,
        ssh_container=ssh_container,
        dry_run=dry_run,
    )
    state.tasks["pipeline_live"] = task_id

    # 6. Seeded usage events for admin-bots-list cost pills
    run_server_helper(
        ssh_alias=ssh_alias,
        container=ssh_container,
        helper_name="seed_usage_events",
        args=demo_bot_ids,
        dry_run=dry_run,
    )

    return state


def teardown_flagship(client: SpindrelClient) -> None:
    # Pipelines first (FK on channel)
    for bot_id in [b["id"] for b in bot_scenarios.DEMO_BOTS]:
        pipeline_scenarios.teardown_midrun_pipelines(client, bot_id=bot_id)

    for ch in client.list_channels():
        cid = ch.get("client_id") or ""
        if cid.startswith("screenshot:"):
            client.delete_channel(str(ch["id"]))

    bot_scenarios.teardown_demo_bots(client)
