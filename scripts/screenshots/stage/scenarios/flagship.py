"""Flagship-8 scenario stager.

Orchestrates bots + channels + pinned widgets + a mid-run pipeline + seeded
usage events so the capture layer can drive every route in one run.

Idempotent end-to-end: stable ``screenshot:*`` client_ids / bot ids / pipeline
titles keep reruns dedupe-safe.
"""
from __future__ import annotations

from . import StagedState
from . import bots as bot_scenarios
from . import dashboards as dashboard_scenarios
from . import pipelines as pipeline_scenarios
from .._exec import run_server_helper
from ..client import SpindrelClient


HOME_CHANNEL_CLIENT_IDS = [
    ("Morning briefing", "screenshot:home-1"),
    ("House automation", "screenshot:home-2"),
    ("Inbox triage",     "screenshot:home-3"),
    ("Ops & deploys",    "screenshot:home-4"),
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

    # 2. Home channels (for home.png)
    home_channel_ids: list[str] = []
    for name, client_id in HOME_CHANNEL_CLIENT_IDS:
        ch = client.ensure_channel(client_id=client_id, bot_id=primary_bot, name=name)
        home_channel_ids.append(str(ch["id"]))
    state.channels["home_list"] = ",".join(home_channel_ids)

    # 3. Chat-main channel (+ 2 rail widgets)
    chat_main = client.ensure_channel(
        client_id=CHAT_MAIN_CLIENT_ID,
        bot_id=primary_bot,
        name="Evening check-in",
    )
    chat_main_id = str(chat_main["id"])
    state.channels["chat_main"] = chat_main_id
    dashboard_scenarios.pin_chat_rail_widgets(
        client, channel_id=chat_main_id, source_bot_id=primary_bot
    )

    # 4. Demo dashboard (6 pins for widget-dashboard.png)
    demo_dashboard = client.ensure_channel(
        client_id=DEMO_DASHBOARD_CLIENT_ID,
        bot_id=primary_bot,
        name="Demo dashboard",
    )
    demo_dashboard_id = str(demo_dashboard["id"])
    state.channels["demo_dashboard"] = demo_dashboard_id
    dashboard_scenarios.pin_full_dashboard(
        client, channel_id=demo_dashboard_id, source_bot_id=primary_bot
    )

    # 5. Mid-run pipeline channel + task
    pipeline_channel = client.ensure_channel(
        client_id=PIPELINE_CHANNEL_CLIENT_ID,
        bot_id=primary_bot,
        name="Pipeline demo",
    )
    pipeline_channel_id = str(pipeline_channel["id"])
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
