"""Docs-repair scenario — seeds the 9 views referenced by guides today.

Each guide's ``![](../images/X.png)`` reference is covered by one spec in
``DOCS_REPAIR_SPECS`` and one small seed here.

Idempotent end-to-end: all records use the ``screenshot:*`` prefix so reruns
dedupe safely and ``teardown_docs_repair`` cleans cleanly.

Builds on top of ``stage_flagship``'s ``screenshot:chat-main`` channel —
running ``stage --only flagship`` before ``stage --only docs-repair`` is the
intended order, and ``stage_docs_repair`` will call through if chat-main is
missing.
"""
from __future__ import annotations

from . import StagedState
from . import bots as bot_scenarios
from .._exec import run_server_helper
from ..client import SpindrelClient


# Stable identifiers — namespace every created record.
SECRET_SEEDS: list[tuple[str, str, str]] = [
    ("SCREENSHOT_GITHUB_TOKEN", "ghp_demo_redacted_token_for_screenshot_use",
     "GitHub PAT used by the demo orchestrator"),
    ("SCREENSHOT_WEATHER_API_KEY", "demo_weather_api_key",
     "OpenWeather API key for the demo weather tool"),
    ("SCREENSHOT_HA_TOKEN", "demo_long_lived_ha_token",
     "Home Assistant long-lived access token"),
]

MCP_SEEDS: list[tuple[str, str, str]] = [
    ("screenshot-mcp-ha", "Home Assistant",
     "https://ha.example.internal/mcp"),
    ("screenshot-mcp-notes", "Notes (local)",
     "http://localhost:4455/mcp"),
]

SKILL_SEEDS: list[tuple[str, str, str]] = [
    ("screenshot/morning_brief",
     "Morning brief",
     "# Morning brief\n\nAssemble an overnight summary from alerts + calendar + weather."),
    ("screenshot/camera_triage",
     "Camera triage",
     "# Camera triage\n\nFor each offline Frigate camera, propose the next action (restart, replace, ignore)."),
    ("screenshot/package_watch",
     "Package watch",
     "# Package watch\n\nWatch Amazon order history and ping the channel on Out-for-delivery → Delivered transitions."),
]

BLUEBUBBLES_CHANNEL_CLIENT_ID = "screenshot:bluebubbles-hud"


def stage_docs_repair(
    client: SpindrelClient,
    *,
    ssh_alias: str,
    ssh_container: str,
    dry_run: bool = False,
) -> StagedState:
    state = StagedState()

    # 1. Ensure demo bots exist (cheap reuse — idempotent).
    demo_bot_ids = bot_scenarios.ensure_demo_bots(client)
    primary_bot = demo_bot_ids[0]
    state.bots["primary"] = primary_bot

    # 2. Heartbeat — reuse flagship's chat-main channel if present, else mint.
    chat_main = client.ensure_channel(
        client_id="screenshot:chat-main",
        bot_id=primary_bot,
        name="Evening check-in",
        category="Daily",
    )
    state.channels["chat_main"] = str(chat_main["id"])
    # Toggle on so the Heartbeat tab shows an enabled row. Field edits
    # (prompt / interval / quiet hours) happen through the channel PATCH
    # path, which the UI also exposes — seeding via toggle is enough to
    # render the tab in its active state.
    try:
        client.toggle_heartbeat(channel_id=str(chat_main["id"]), enabled=True)
    except Exception as e:  # non-fatal — capture may still succeed on a toggled-off tab
        import logging
        logging.getLogger(__name__).warning("heartbeat toggle failed: %s", e)

    # 3. Secrets — 3 cleanly named rows.
    existing_secret_names = {s.get("name") for s in client.list_secret_values()}
    for name, value, desc in SECRET_SEEDS:
        if name in existing_secret_names:
            continue
        client.create_secret_value(name=name, value=value, description=desc)

    # 4. MCP servers — 2 rows.
    for server_id, display_name, url in MCP_SEEDS:
        client.ensure_mcp_server(
            server_id=server_id,
            display_name=display_name,
            url=url,
            is_enabled=True,
        )

    # 5. Skills — 3 bot-authored-looking rows for learning analytics surface.
    for skill_id, name, content in SKILL_SEEDS:
        client.ensure_skill(skill_id=skill_id, name=name, content=content)

    # 6. Usage events for the usage-and-forecast view. Reuses the flagship
    #    helper which seeds a spread of model+tokens+cost rows.
    run_server_helper(
        ssh_alias=ssh_alias,
        container=ssh_container,
        helper_name="seed_usage_events",
        args=demo_bot_ids,
        dry_run=dry_run,
    )

    # 7. BlueBubbles channel with integration binding.
    bb_channel = client.ensure_channel(
        client_id=BLUEBUBBLES_CHANNEL_CLIENT_ID,
        bot_id=primary_bot,
        name="BlueBubbles demo",
        category="Home",
    )
    state.channels["bluebubbles"] = str(bb_channel["id"])
    try:
        client.create_channel_binding(
            channel_id=str(bb_channel["id"]),
            integration_type="bluebubbles",
            client_id="screenshot:bluebubbles-binding",
            display_name="BlueBubbles (demo)",
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "bluebubbles binding create failed (integration may be un-installed on this instance): %s", e
        )

    # Seed chat messages so the BlueBubbles channel isn't an empty skeleton.
    run_server_helper(
        ssh_alias=ssh_alias,
        container=ssh_container,
        helper_name="seed_chat_messages",
        args=[str(bb_channel["id"]), primary_bot],
        dry_run=dry_run,
    )

    return state


def teardown_docs_repair(client: SpindrelClient) -> None:
    """Delete everything this scenario created. Flagship teardown handles its
    own channels — we only delete the bluebubbles channel and the records
    keyed to docs-repair seeds.
    """
    # Channels — the bluebubbles channel is ours.
    for ch in client.list_channels():
        cid = ch.get("client_id") or ""
        if cid == BLUEBUBBLES_CHANNEL_CLIENT_ID:
            client.delete_channel(str(ch["id"]))

    # Secrets
    target_secret_names = {name for name, _, _ in SECRET_SEEDS}
    for s in client.list_secret_values():
        if s.get("name") in target_secret_names:
            client.delete_secret_value(str(s["id"]))

    # MCP servers
    target_mcp_ids = {sid for sid, _, _ in MCP_SEEDS}
    for s in client.list_mcp_servers():
        if s.get("id") in target_mcp_ids:
            client.delete_mcp_server(str(s["id"]))

    # Skills
    for skill_id, _, _ in SKILL_SEEDS:
        client.delete_skill(skill_id)
