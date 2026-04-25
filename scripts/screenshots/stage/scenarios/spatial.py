"""Spatial Canvas scenario stager.

Populates Spindrel's desktop home (``/``) with photogenic density:

  * ~12 demo bots (a household / dev / ops mix) so the canvas reads as
    "many bots, one workspace" at a glance.
  * ~18 channels spread across DAILY / HOME / WORK / SHOWCASE so the
    sidebar groupings are visible alongside the canvas.
  * 6 widget pins on the reserved ``workspace:spatial`` dashboard so the
    canvas has floating widget tiles + connection lines back to channels.
  * 8 heartbeat schedules at varied intervals (15m, 1h, 6h, 12h, 1d, 2d,
    3d, 5d) so the Now Well shows orbiting diamonds across every time
    band the geometry handles.
  * Recent chat messages on a handful of channels so density halos render
    with visible variation between busy and quiet channels.

WorkspaceSpatialNode rows are *not* explicitly written. ``GET /workspace/
spatial/nodes`` (``app/routers/api_v1_workspace_spatial.py:99``) auto-seeds
channel + bot positions via deterministic phyllotaxis on first read; the
stager triggers one read after creating channels so the layout is stable
before capture.

Idempotent end-to-end via stable ``screenshot:spatial:*`` client_ids and
``screenshot-spatial-*`` bot ids. Teardown is bounded to those prefixes.
"""
from __future__ import annotations

from . import StagedState
from . import bots as bot_scenarios
from .._exec import run_server_helper
from ..client import SpindrelClient
from .. import envelopes as env


# ---------------------------------------------------------------------------
# Channel cast — name, client_id, category, bot_slug (suffix on
# ``screenshot-spatial-``). Ordered so the seed-index → phyllotaxis layout is
# stable across reruns (server assigns positions in the order channels first
# appear in this list).
# ---------------------------------------------------------------------------

SPATIAL_CHANNEL_PREFIX = "screenshot:spatial:"

SPATIAL_CHANNELS: list[tuple[str, str, str, str]] = [
    # (name,                      client_id,                            category,    bot_slug)
    ("#gardening",                f"{SPATIAL_CHANNEL_PREFIX}gardening",        "Daily",   "sprout"),
    ("#baking",                   f"{SPATIAL_CHANNEL_PREFIX}baking",           "Daily",   "crumb"),
    ("#bennie",                   f"{SPATIAL_CHANNEL_PREFIX}bennie",           "Daily",   "bennie"),
    ("#bennie-loggins",           f"{SPATIAL_CHANNEL_PREFIX}bennie-loggins",   "Daily",   "bennie"),
    ("#grocery-list",             f"{SPATIAL_CHANNEL_PREFIX}grocery",          "Daily",   "penny"),
    ("#home-assistant",           f"{SPATIAL_CHANNEL_PREFIX}home-assistant",   "Home",    "home-assistant"),
    ("#docker-fun",               f"{SPATIAL_CHANNEL_PREFIX}docker-fun",       "Home",    "dev"),
    ("#system-audit-and-logs",    f"{SPATIAL_CHANNEL_PREFIX}system-audit",     "Home",    "log"),
    ("#developer-commits",        f"{SPATIAL_CHANNEL_PREFIX}dev-commits",      "Work",    "patch"),
    ("#quality-assurance",        f"{SPATIAL_CHANNEL_PREFIX}qa",               "Work",    "dev"),
    ("#widget-building",          f"{SPATIAL_CHANNEL_PREFIX}widget-building",  "Work",    "dev"),
    ("#spindrel-website",         f"{SPATIAL_CHANNEL_PREFIX}website",          "Work",    "dev"),
    ("crumb-testing",             f"{SPATIAL_CHANNEL_PREFIX}crumb-testing",    "Showcase","crumb"),
    ("sprout-testing",            f"{SPATIAL_CHANNEL_PREFIX}sprout-testing",   "Showcase","sprout"),
    ("ollama-testing",            f"{SPATIAL_CHANNEL_PREFIX}ollama-testing",   "Showcase","dev"),
    ("gary-texts",                f"{SPATIAL_CHANNEL_PREFIX}gary-texts",       "Showcase","kathy"),
    ("anthony-texts",             f"{SPATIAL_CHANNEL_PREFIX}anthony-texts",    "Showcase","kathy"),
    ("kathleen-texts",            f"{SPATIAL_CHANNEL_PREFIX}kathleen-texts",   "Showcase","kathy"),
]


# ---------------------------------------------------------------------------
# Canvas widget pins — six tiles spread across two channel clusters so the
# canvas shows visible widget→channel connection lines. Each tile gets an
# explicit world position so reruns reconcile to the same camera-friendly
# layout instead of drifting off-screen.
# ---------------------------------------------------------------------------

# (display_label, envelope-builder, source channel_slug, world coords)
SPATIAL_PINS: list[tuple[str, "callable", str, tuple[float, float, float, float]]] = [
    ("Notes",             env.notes,              "qa",              (-420.0, -180.0, 240.0, 160.0)),
    ("Todos",             env.todos,              "qa",              (-160.0, -200.0, 240.0, 160.0)),
    ("Standing order",    env.standing_order_poll,"widget-building", ( 360.0, -120.0, 260.0, 180.0)),
    ("Upcoming activity", env.upcoming_activity,  "dev-commits",     ( 460.0,  120.0, 240.0, 160.0)),
    ("Usage forecast",    env.usage_forecast,     "system-audit",    (-440.0,  140.0, 240.0, 160.0)),
    ("Notes · garden",env.notes,             "gardening",       (-700.0, -360.0, 220.0, 140.0)),
]


# ---------------------------------------------------------------------------
# Heartbeats — varied intervals so the Now Well's 15m / 1h / 6h / 12h / 1d /
# 2d / 3d / 5d / 1w bands all show at least one orbiting diamond.
# ``append_spatial_prompt=True`` enables the per-channel spatial prompt so
# the canvas reads as "alive" (heartbeats are spatially aware).
# ---------------------------------------------------------------------------

# (channel_slug, interval_minutes, prompt_summary)
SPATIAL_HEARTBEATS: list[tuple[str, int, str]] = [
    ("system-audit",     15,    "Scan logs for new errors and summarize."),
    ("dev-commits",      60,    "Triage incoming commits; flag review-worthy diffs."),
    ("qa",               360,   "Review test runs since last beat; surface flakes."),
    ("home-assistant",   720,   "Spot-check device states and surface offline gear."),
    ("gardening",        1440,  "Plan tomorrow's garden tasks."),
    ("baking",           2880,  "Update the sourdough timeline."),
    ("widget-building",  4320,  "Audit canvas widgets for stale state."),
    ("website",          7200,  "Skim spindrel.dev analytics for the week."),
]


# ---------------------------------------------------------------------------
# Channels that should look "alive" with recent chat history so density
# halos render with visible variation. Subset of SPATIAL_CHANNELS.
# ---------------------------------------------------------------------------
ACTIVE_CHANNEL_SLUGS = ("qa", "dev-commits", "gardening", "system-audit", "widget-building", "bennie")


def _ch_id(slug: str, by_slug: dict[str, str]) -> str:
    """Resolve a channel client_id slug (e.g. ``"qa"``) to its UUID, raising
    a clear error if the channel wasn't created above. Avoids silent KeyError
    deep inside a helper call."""
    try:
        return by_slug[slug]
    except KeyError as e:
        raise RuntimeError(
            f"spatial scenario: unknown channel slug {slug!r}; "
            f"known slugs: {sorted(by_slug)!r}"
        ) from e


def stage_spatial(
    client: SpindrelClient,
    *,
    ssh_alias: str,
    ssh_container: str,
    dry_run: bool = False,
) -> StagedState:
    state = StagedState()

    # 1. Bots — 12 demo personas. Reuse ensure_spatial_demo_bots so the cast
    # is shared with any future scenario that wants the same lineup.
    bot_ids = bot_scenarios.ensure_spatial_demo_bots(client)
    state.bots = {spec["id"].split("-spatial-", 1)[-1]: spec["id"]
                  for spec in bot_scenarios.DEMO_SPATIAL_BOTS}
    state.bots["primary"] = bot_ids[0]  # orchestrator

    def _bot(slug: str) -> str:
        return f"{bot_scenarios.SPATIAL_BOT_PREFIX}{slug}"

    # 2. Channels — bound to a per-channel bot so the canvas shows bots-as-
    # stars with channel satellites orbiting them. ``ensure_channel`` dedupes
    # on client_id; reruns are idempotent.
    channel_id_by_slug: dict[str, str] = {}  # short slug (e.g. "qa") -> uuid
    for name, client_id, category, bot_slug in SPATIAL_CHANNELS:
        ch = client.ensure_channel(
            client_id=client_id,
            bot_id=_bot(bot_slug),
            name=name,
            category=category,
        )
        slug = client_id.removeprefix(SPATIAL_CHANNEL_PREFIX)
        channel_id_by_slug[slug] = str(ch["id"])
    state.channels = dict(channel_id_by_slug)

    # 3. Force WorkspaceSpatialNode seeding so phyllotaxis lays out channel +
    # bot positions deterministically before any capture runs. Idempotent —
    # just a GET that triggers the auto-seed path.
    if not dry_run:
        client.list_spatial_nodes()

    # 4. Canvas widget pins — atomic pin + node create. Use a stable
    # display_label per pin so reruns dedupe by listing existing pins on the
    # ``workspace:spatial`` dashboard before posting.
    existing_canvas_pins = {
        p.get("display_label"): p
        for p in client.list_pins(dashboard_key="workspace:spatial")
    }
    pin_ids: list[str] = []
    primary_bot = bot_ids[0]
    for label, envelope_builder, channel_slug, (wx, wy, ww, wh) in SPATIAL_PINS:
        if label in existing_canvas_pins:
            pin_ids.append(str(existing_canvas_pins[label]["id"]))
            continue
        envelope = envelope_builder()
        # Replace the envelope's display_label so the canvas tile chrome
        # matches the layout label we keyed dedupe on.
        envelope = {**envelope, "display_label": label}
        envelope.setdefault("body", {})["display_label"] = label
        result = client.pin_canvas_widget(
            tool_name=envelope["body"]["widget_ref"].split("/", 1)[-1],
            envelope=envelope,
            source_kind="channel",
            source_channel_id=_ch_id(channel_slug, channel_id_by_slug),
            source_bot_id=primary_bot,
            display_label=label,
            world_x=wx,
            world_y=wy,
            world_w=ww,
            world_h=wh,
        )
        pin = result.get("pin") or {}
        if pin.get("id"):
            pin_ids.append(str(pin["id"]))
    state.pins = {f"canvas_{i}": pid for i, pid in enumerate(pin_ids)}
    state.dashboards["spatial"] = "workspace:spatial"

    # 5. Heartbeats — varied intervals across the time bands. Each enable
    # also flips ``append_spatial_prompt`` on so the heartbeat run is canvas-
    # aware (bots can sense neighbors when they fire).
    for channel_slug, interval, prompt in SPATIAL_HEARTBEATS:
        client.set_heartbeat(
            channel_id=_ch_id(channel_slug, channel_id_by_slug),
            enabled=True,
            interval_minutes=interval,
            prompt=prompt,
            dispatch_mode="optional",
            append_spatial_prompt=True,
        )

    # 6. Recent chat history on a handful of channels so density halos render
    # with visible variation. Same server helper flagship uses; idempotent
    # via the helper's ``>=4 messages → skip`` check.
    for slug in ACTIVE_CHANNEL_SLUGS:
        run_server_helper(
            ssh_alias=ssh_alias,
            container=ssh_container,
            helper_name="seed_chat_messages",
            args=[_ch_id(slug, channel_id_by_slug), primary_bot],
            dry_run=dry_run,
        )

    # 7. Surface a stable hero-channel UUID for capture specs to reference.
    # ``qa`` is the densest channel (canvas pins, heartbeat, recent activity)
    # so it's the natural target for the "zoom into a channel" spec.
    state.channels["spatial_hero"] = channel_id_by_slug["qa"]

    return state


def teardown_spatial(client: SpindrelClient) -> None:
    """Remove canvas pins, channels, and bots created by ``stage_spatial``.

    Order: pins → channels → bots. Heartbeats are owned by their channel
    (FK cascade), so deleting the channel removes them. Workspace spatial
    nodes also cascade off channel/pin delete.
    """
    # Canvas pins on the reserved ``workspace:spatial`` slug. Match by the
    # label set in SPATIAL_PINS so we don't touch user-created canvas pins.
    spatial_labels = {label for label, *_ in SPATIAL_PINS}
    for pin in client.list_pins(dashboard_key="workspace:spatial"):
        if pin.get("display_label") in spatial_labels:
            try:
                client.delete_pin(str(pin["id"]))
            except Exception:
                pass

    # Channels — bounded to our prefix.
    for ch in client.list_channels():
        cid = ch.get("client_id") or ""
        if cid.startswith(SPATIAL_CHANNEL_PREFIX):
            client.delete_channel(str(ch["id"]))

    # Bots last — channels reference bot_id, so delete after channels.
    bot_scenarios.teardown_spatial_demo_bots(client)
