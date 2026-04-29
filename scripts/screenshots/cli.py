"""Entrypoint for the screenshot pipeline.

Usage:
    python -m scripts.screenshots stage    --only flagship [--dry-run]
    python -m scripts.screenshots capture  --only flagship
    python -m scripts.screenshots all      --only flagship [--dry-run]
    python -m scripts.screenshots teardown --only flagship
    python -m scripts.screenshots video    {build|preview|plan} [args]
    python -m scripts.screenshots check
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import asdict

from scripts.screenshots import config
from scripts.screenshots.capture.browser import AuthBundle
from scripts.screenshots.capture.runner import capture_batch
from scripts.screenshots.capture.specs import (
    A3_DOCS_SPECS,
    ATTACHMENT_CHECK_SPECS,
    ATTENTION_SPECS,
    CHANNEL_SESSION_TAB_SPECS,
    CORE_FEATURE_SPECS,
    DOCS_REPAIR_SPECS,
    FLAGSHIP_SPECS,
    HARNESS_SPECS,
    INTEGRATION_CHAT_SPECS,
    INTEGRATIONS_SPECS,
    MOBILE_HOME_SPECS,
    NOTIFICATIONS_SPECS,
    PROJECT_WORKSPACE_SPECS,
    SPATIAL_CHECK_SPECS,
    SPATIAL_SPECS,
    STARBOARD_SPECS,
    VOICE_INPUT_SPECS,
    WIDGET_PIN_SPECS,
    resolve_specs,
)
from scripts.screenshots.stage.client import SpindrelClient
from scripts.screenshots.stage.scenarios.core_features import (
    stage_core_features,
    teardown_core_features,
)
from scripts.screenshots.stage.scenarios.docs_repair import (
    BLUEBUBBLES_CHANNEL_CLIENT_ID,
    stage_docs_repair,
    teardown_docs_repair,
)
from scripts.screenshots.stage.scenarios.flagship import stage_flagship, teardown_flagship
from scripts.screenshots.stage.scenarios.harness import (
    HARNESS_BOT_ID,
    HARNESS_CHAT_CHANNEL_CLIENT_ID,
    stage_harness,
    teardown_harness,
)
from scripts.screenshots.stage.scenarios.integrations import (
    stage_integrations,
    teardown_integrations,
)
from scripts.screenshots.stage.scenarios.integration_chat import (
    stage_integration_chat,
    teardown_integration_chat,
)
from scripts.screenshots.stage.scenarios.projects import (
    PROJECT_CHANNEL_CLIENT_ID,
    PROJECT_SLUG,
    stage_project_workspace,
    teardown_project_workspace,
)
from scripts.screenshots.stage.scenarios.spatial import stage_spatial, teardown_spatial
from scripts.screenshots.stage.scenarios.attention import (
    stage_attention,
    stage_notifications,
    teardown_attention,
    teardown_notifications,
)
from scripts.screenshots.stage.scenarios.attachments import (
    ATTACHMENT_CHANNEL_CLIENT_ID,
    stage_attachments,
    teardown_attachments,
)
from scripts.screenshots.stage.scenarios.channel_session_tabs import (
    CHANNEL_SESSION_TABS_CLIENT_ID,
    stage_channel_session_tabs,
    teardown_channel_session_tabs,
)
from scripts.screenshots.stage.scenarios.voice_input import (
    VOICE_INPUT_CHANNEL_CLIENT_ID,
    stage_voice_input,
    teardown_voice_input,
)


logger = logging.getLogger("screenshots")


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="screenshots")
    p.add_argument(
        "action",
        choices=["stage", "capture", "all", "teardown", "video", "check"],
    )
    p.add_argument("--only", default="flagship",
                   choices=["flagship", "docs-repair", "integrations", "a3-docs", "core-features", "setup-tui", "spatial", "spatial-checks", "attachment-checks", "voice-input", "channel-session-tabs", "integration-chat", "harness", "notifications", "attention", "widget-pin", "mobile-home", "starboard", "project-workspace"],
                   help="scenario bundle")
    p.add_argument("--dry-run", action="store_true",
                   help="log writes without executing (stage/teardown only)")
    p.add_argument("--verbose", "-v", action="store_true")
    # `video` has its own nested subcommand + flag set. We parse top-level
    # args with ``parse_known_args`` so flags like ``--only`` are recognized
    # for stage/capture/teardown, and the unknown tail is passed verbatim to
    # ``video.cli`` when the action is ``video``.
    args, unknown = p.parse_known_args()
    args.rest = unknown
    return args


def _flat_placeholders(state) -> dict[str, str]:
    # Merge all staged dicts into a single flat namespace used by route
    # placeholders. ``channels`` wins on collisions — the capture specs key
    # on channel labels directly.
    flat: dict[str, str] = {}
    flat.update(state.bots)
    flat.update(state.tasks)
    flat.update(state.dashboards)
    flat.update(state.channels)
    return flat


def _run_stage(cfg: config.Config, *, dry_run: bool, only: str = "flagship"):
    if only == "integrations":
        # Adopt a curated set so the Active list + detail pages render with
        # populated state (capability badges color-coded, env vars present,
        # not the universal "Available - not adopted" zero-state).
        with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
            stage_integrations(client)
        print("staged (integrations): adopted curated integrations")
        return None
    if only == "a3-docs":
        # A3-docs admin slice routes off the registry/tasks/approvals — no
        # staging required. Server state (whatever's been seeded by other
        # scenarios or normal use) is what shows up in the captures.
        print("staged (a3-docs): no-op — admin routes need no staging")
        return None
    if only == "setup-tui":
        # Synthetic terminal frames — no API, no browser. Stage is a no-op;
        # all work happens in the capture step (PIL render).
        print("staged (setup-tui): no-op — synthetic terminal frames")
        return None
    if only == "core-features":
        with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
            stage_core_features(
                client,
                ssh_alias=cfg.ssh_alias,
                ssh_container=cfg.ssh_container,
                dry_run=dry_run,
            )
        print("staged (core-features): seeded webhook rows + bot knowledge-base chunks")
        return None
    if only == "integration-chat":
        with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
            state = stage_integration_chat(
                client,
                ssh_alias=cfg.ssh_alias,
                ssh_container=cfg.ssh_container,
                dry_run=dry_run,
            )
        print("staged (integration-chat):")
        for k, v in asdict(state).items():
            print(f"  {k}: {v}")
        return state
    if only == "harness":
        with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
            state = stage_harness(
                client,
                ssh_alias=cfg.ssh_alias,
                ssh_container=cfg.ssh_container,
                dry_run=dry_run,
            )
        print(f"staged (harness):")
        for k, v in asdict(state).items():
            print(f"  {k}: {v}")
        return state
    if only == "project-workspace":
        with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
            state = stage_project_workspace(client, dry_run=dry_run)
        print("staged (project-workspace):")
        for k, v in asdict(state).items():
            print(f"  {k}: {v}")
        return state
    if only == "notifications":
        with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
            state = stage_notifications(client, dry_run=dry_run)
        print("staged (notifications):")
        for k, v in asdict(state).items():
            print(f"  {k}: {v}")
        return state
    if only == "attention":
        with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
            state = stage_attention(client, dry_run=dry_run)
        print("staged (attention):")
        for k, v in asdict(state).items():
            print(f"  {k}: {v}")
        return state
    if only == "attachment-checks":
        with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
            state = stage_attachments(client, dry_run=dry_run)
        print("staged (attachment-checks):")
        for k, v in asdict(state).items():
            print(f"  {k}: {v}")
        return state
    if only == "channel-session-tabs":
        with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
            state = stage_channel_session_tabs(
                client,
                ssh_alias=cfg.ssh_alias,
                ssh_container=cfg.ssh_container,
                dry_run=dry_run,
            )
        print("staged (channel-session-tabs):")
        for k, v in asdict(state).items():
            print(f"  {k}: {v}")
        return state
    if only == "voice-input":
        with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
            state = stage_voice_input(client, dry_run=dry_run)
        print("staged (voice-input):")
        for k, v in asdict(state).items():
            print(f"  {k}: {v}")
        return state
    if only == "widget-pin":
        print("staged (widget-pin): no-op — reuses flagship state (run `stage --only flagship` first)")
        return None
    if only == "mobile-home":
        print("staged (mobile-home): no-op — reuses flagship + attention state")
        return None
    if only == "starboard":
        print("staged (starboard): no-op — reuses spatial + attention state")
        return None
    if only == "spatial-checks":
        with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
            state = stage_spatial(
                client,
                ssh_alias=cfg.ssh_alias,
                ssh_container=cfg.ssh_container,
                dry_run=dry_run,
            )
            if not dry_run:
                attention_state = stage_attention(client, dry_run=dry_run)
                state.tasks.update(attention_state.tasks)
        print("staged (spatial-checks): spatial canvas + attention beacons")
        from dataclasses import asdict as _asdict
        for k, v in _asdict(state).items():
            if isinstance(v, dict) and len(v) > 6:
                print(f"  {k}: {len(v)} entries")
            else:
                print(f"  {k}: {v}")
        return state
    if only == "spatial":
        with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
            state = stage_spatial(
                client,
                ssh_alias=cfg.ssh_alias,
                ssh_container=cfg.ssh_container,
                dry_run=dry_run,
            )
        print(f"staged (spatial):")
        from dataclasses import asdict as _asdict
        for k, v in _asdict(state).items():
            if isinstance(v, dict) and len(v) > 6:
                # collapse the long channel/bot maps for legibility
                print(f"  {k}: {len(v)} entries")
            else:
                print(f"  {k}: {v}")
        return state
    with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
        if only == "flagship":
            state = stage_flagship(
                client,
                ssh_alias=cfg.ssh_alias,
                ssh_container=cfg.ssh_container,
                dry_run=dry_run,
            )
        elif only == "docs-repair":
            state = stage_docs_repair(
                client,
                ssh_alias=cfg.ssh_alias,
                ssh_container=cfg.ssh_container,
                dry_run=dry_run,
            )
        else:  # pragma: no cover
            raise ValueError(f"unknown scenario: {only!r}")
        print(f"staged ({only}):")
        for k, v in asdict(state).items():
            print(f"  {k}: {v}")
        return state


def _run_capture(cfg: config.Config, *, only: str = "flagship"):
    if only == "setup-tui":
        _run_capture_setup_tui(cfg)
        return

    if not cfg.login_email or not cfg.login_password:
        raise SystemExit(
            "SPINDREL_LOGIN_EMAIL / SPINDREL_LOGIN_PASSWORD required for capture "
            "(used to mint JWT tokens for the browser's localStorage)."
        )

    # Recover staged state by querying the API — stable screenshot:* client_ids
    # mean we can always rediscover what stage produced.
    with SpindrelClient(cfg.api_url, cfg.api_key) as client:
        login = client.login(email=cfg.login_email, password=cfg.login_password)
        bundle = AuthBundle(
            api_url=cfg.api_url,
            access_token=login["access_token"],
            refresh_token=login["refresh_token"],
            user=login["user"],
        )

        # Purge test debris BEFORE every capture so the channel sidebar
        # never leaks `chat:e2e:*`, `dbg-*`, `frag-*`, `smoke-*` rows into
        # a hero shot. Allow-list is `screenshot:*` + `orchestrator:*` +
        # `default`. Idempotent — clean instances are a no-op.
        purged = client.purge_test_channels()
        if purged:
            print(f"purged {len(purged)} test channel(s):")
            for cid in purged[:10]:
                print(f"  - {cid}")
            if len(purged) > 10:
                print(f"  ... and {len(purged) - 10} more")

        placeholders: dict[str, str] = {}

        if only == "harness":
            harness_bot = client.get_bot(HARNESS_BOT_ID)
            if not harness_bot:
                raise SystemExit(
                    f"Harness bot {HARNESS_BOT_ID!r} not found. Run `stage --only harness` first."
                )
            placeholders["harness_claude"] = str(harness_bot["id"])
            # Optional — only present when the demo runtime is registered on
            # the host (SPINDREL_DEMO_HARNESS=true). The chat capture spec
            # will fail with a clear "channel missing" if the placeholder
            # didn't resolve, but admin captures still pass.
            all_channels = {c.get("client_id"): c for c in client.list_channels()}
            chat_ch = all_channels.get(HARNESS_CHAT_CHANNEL_CLIENT_ID)
            placeholders["harness_chat"] = str(chat_ch["id"]) if chat_ch else "missing"
            spec_list = HARNESS_SPECS
        elif only == "spatial":
            # Spatial canvas captures key off ``/`` only — the canvas mounts
            # there and reads camera / chrome state from localStorage that
            # each spec seeds via ``extra_init_scripts``. No route
            # placeholders needed.
            spec_list = SPATIAL_SPECS
        elif only == "spatial-checks":
            spec_list = SPATIAL_CHECK_SPECS
        elif only == "notifications":
            # /admin/notifications is static — staging populates DB rows the
            # page reads back. No route placeholders.
            spec_list = NOTIFICATIONS_SPECS
        elif only == "attention":
            # Attention captures key off ``/`` only (canvas + drawer). DB
            # state from ``stage_attention`` drives what renders. No route
            # placeholders.
            spec_list = ATTENTION_SPECS
        elif only == "attachment-checks":
            all_channels = {c.get("client_id"): c for c in client.list_channels()}
            ch = all_channels.get(ATTACHMENT_CHANNEL_CLIENT_ID)
            if not ch:
                raise SystemExit(
                    "screenshot:attachments channel not found. Run `stage --only attachment-checks` first."
                )
            placeholders["attachments"] = str(ch["id"])
            spec_list = ATTACHMENT_CHECK_SPECS
        elif only == "voice-input":
            all_channels = {c.get("client_id"): c for c in client.list_channels()}
            ch = all_channels.get(VOICE_INPUT_CHANNEL_CLIENT_ID)
            if not ch:
                raise SystemExit(
                    "screenshot:voice-input channel not found. Run `stage --only voice-input` first."
                )
            placeholders["voice_input"] = str(ch["id"])
            spec_list = VOICE_INPUT_SPECS
        elif only == "channel-session-tabs":
            all_channels = {c.get("client_id"): c for c in client.list_channels()}
            ch = all_channels.get(CHANNEL_SESSION_TABS_CLIENT_ID)
            if not ch:
                raise SystemExit(
                    "screenshot:channel-session-tabs channel not found. Run `stage --only channel-session-tabs` first."
                )
            channel_id = str(ch["id"])
            sessions = client.list_channel_sessions(channel_id, limit=10)
            if len(sessions) < 2:
                raise SystemExit(
                    "channel-session-tabs capture needs at least two sessions. Run `stage --only channel-session-tabs` again."
                )
            placeholders["channel_session_tabs"] = channel_id
            placeholders["session_tabs_latest"] = str(sessions[0]["session_id"])
            placeholders["session_tabs_older"] = str(sessions[1]["session_id"])
            spec_list = CHANNEL_SESSION_TAB_SPECS
        elif only == "project-workspace":
            all_channels = {c.get("client_id"): c for c in client.list_channels()}
            ch = all_channels.get(PROJECT_CHANNEL_CLIENT_ID)
            if not ch:
                raise SystemExit(
                    "screenshot:project-workspace channel not found. Run `stage --only project-workspace` first."
                )
            project = next(
                (p for p in client.list_projects() if p.get("slug") == PROJECT_SLUG),
                None,
            )
            if not project:
                raise SystemExit(
                    "screenshot-project-workspace Project not found. Run `stage --only project-workspace` first."
                )
            placeholders["project_workspace"] = str(ch["id"])
            placeholders["project_workspace_project"] = str(project["id"])
            spec_list = PROJECT_WORKSPACE_SPECS
        elif only == "mobile-home":
            spec_list = MOBILE_HOME_SPECS
        elif only == "starboard":
            spec_list = STARBOARD_SPECS
        elif only == "widget-pin":
            # Resolve the demo dashboard's Notes pin via list_pins. The
            # demo dashboard is channel-scoped (`channel:<uuid>`); flagship
            # staging seeds a "Notes" pin into it.
            all_channels = {c.get("client_id"): c for c in client.list_channels()}
            demo_ch = all_channels.get("screenshot:demo-dashboard")
            if not demo_ch:
                raise SystemExit(
                    "screenshot:demo-dashboard channel not found. Run `stage --only flagship` first."
                )
            dashboard_key = f"channel:{demo_ch['id']}"
            pins = client.list_pins(dashboard_key=dashboard_key)
            notes_pin = next(
                (p for p in pins if p.get("display_label") == "Notes"),
                None,
            )
            if not notes_pin:
                raise SystemExit(
                    f"No 'Notes' pin found on {dashboard_key}. Run `stage --only flagship` first."
                )
            placeholders["notes_pin"] = str(notes_pin["id"])
            spec_list = WIDGET_PIN_SPECS
        elif only == "integrations":
            # Routes are static (/admin/integrations/<slug>) — no placeholders.
            spec_list = INTEGRATIONS_SPECS
        elif only == "core-features":
            # Admin routes are static; chat-content captures need each
            # dedicated channel's UUID resolved from its stable client_id.
            spec_list = CORE_FEATURE_SPECS
            all_channels = {c.get("client_id"): c for c in client.list_channels()}
            for client_id, key in (
                ("screenshot:chat-delegation", "chat_delegation"),
                ("screenshot:chat-cmd-exec",   "chat_cmd_exec"),
                ("screenshot:chat-plan",       "chat_plan"),
                ("screenshot:chat-subagents",  "chat_subagents"),
            ):
                ch = all_channels.get(client_id)
                if ch:
                    placeholders[key] = str(ch["id"])
                else:
                    # Stage hasn't created the channel yet — most likely the
                    # capture is being run before stage. Skip gracefully so
                    # the admin captures still land; the chat-content spec
                    # will fail its predicate with a clear "channel missing"
                    # signal in the route.
                    placeholders[key] = "missing"
        elif only == "integration-chat":
            spec_list = INTEGRATION_CHAT_SPECS
            all_channels = {c.get("client_id"): c for c in client.list_channels()}
            for client_id, key in (
                ("screenshot:chat-excalidraw",   "chat_excalidraw"),
                ("screenshot:chat-marp",         "chat_marp"),
                ("screenshot:chat-browser-live", "chat_browser_live"),
            ):
                ch = all_channels.get(client_id)
                placeholders[key] = str(ch["id"]) if ch else "missing"
        elif only == "a3-docs":
            # Most admin routes are static, but workspace-files needs the
            # default workspace UUID resolved from the API at capture time.
            workspaces = client.list_workspaces()
            if not workspaces:
                raise SystemExit("No workspaces found — workspace-files capture needs at least one.")
            placeholders["default_workspace"] = str(workspaces[0]["id"])
            spec_list = A3_DOCS_SPECS
        else:
            # Rebuild placeholder map from stable client_ids
            all_channels = {c.get("client_id"): c for c in client.list_channels()}
            def _chan(cid: str, *, required: bool = True) -> str:
                ch = all_channels.get(cid)
                if not ch:
                    if not required:
                        return "missing"
                    raise SystemExit(
                        f"Channel with client_id {cid!r} not found. Run `stage` first."
                    )
                return str(ch["id"])

            placeholders["chat_main"] = _chan("screenshot:chat-main")

            if only == "flagship":
                placeholders["demo_dashboard"] = _chan("screenshot:demo-dashboard")
                placeholders["pipeline"]       = _chan("screenshot:pipeline-demo")
                # Pipeline task_id
                pipeline_tasks = [
                    t for t in client.list_tasks(bot_id="screenshot-orchestrator")
                    if t.get("title") == "screenshot:pipeline-demo"
                ]
                if pipeline_tasks:
                    placeholders["pipeline_live"] = str(pipeline_tasks[0]["id"])
                else:
                    logger.warning("No mid-run pipeline task found; chat-pipeline-live will fail.")
                    placeholders["pipeline_live"] = "missing"
                spec_list = FLAGSHIP_SPECS
            elif only == "docs-repair":
                placeholders["bluebubbles"] = _chan(BLUEBUBBLES_CHANNEL_CLIENT_ID, required=False)
                spec_list = DOCS_REPAIR_SPECS
            else:  # pragma: no cover
                raise ValueError(f"unknown scenario: {only!r}")

    specs = resolve_specs(spec_list, placeholders)

    # Dev-panel localStorage seed (flagship only — docs-repair doesn't use it).
    if only == "flagship":
        from scripts.screenshots.capture.browser import _dev_panel_context_script
        dev_script = _dev_panel_context_script(
            bot_id="screenshot-orchestrator",
            channel_id=placeholders["chat_main"],
        )
        for s in specs:
            if s.name in ("dev-panel-tools",):
                s.extra_init_scripts.append(dev_script)

    results = asyncio.run(
        capture_batch(
            specs=specs,
            ui_base=cfg.ui_url,
            bundle=bundle,
            output_root=cfg.docs_images_dir,
        )
    )

    ok = 0
    print("\ncapture results:")
    for r in results:
        mark = "✓" if r.status == "ok" else "✗"
        line = f"  {mark} {r.name:<24} {r.status:<14} {r.output}"
        if r.detail:
            line += f"  ({r.detail})"
        print(line)
        if r.status == "ok":
            ok += 1
    print(f"\n{ok}/{len(results)} ok")
    if ok != len(results):
        sys.exit(1)


def _run_capture_setup_tui(cfg: config.Config) -> None:
    """Render the four setup.sh wizard frames as PNGs into docs/images.

    No API, no Playwright — frames are built from PROVIDERS in scripts/setup.py
    (parsed via AST so the wizard's questionary import doesn't have to load).
    """
    from scripts.screenshots.capture import tui_render
    from scripts.screenshots.capture.tui_frames import SETUP_TUI_FRAMES

    out_dir = cfg.docs_images_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    print("\ncapture results:")
    ok = 0
    for name, builder in SETUP_TUI_FRAMES.items():
        path = out_dir / f"{name}.png"
        tui_render.render(builder(), path)
        print(f"  ✓ {name:<30} ok             {path}")
        ok += 1
    print(f"\n{ok}/{len(SETUP_TUI_FRAMES)} ok")


def _run_teardown(cfg: config.Config, *, dry_run: bool, only: str = "flagship"):
    if only == "integrations":
        with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
            teardown_integrations(client)
        print("teardown (integrations): reverted adopted integrations to available")
        return
    if only == "a3-docs":
        print("teardown (a3-docs): no-op — admin routes have no scenario records")
        return
    if only == "setup-tui":
        print("teardown (setup-tui): no-op — synthetic frames have no scenario records")
        return
    if only == "core-features":
        with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
            teardown_core_features(
                client,
                ssh_alias=cfg.ssh_alias,
                ssh_container=cfg.ssh_container,
            )
        print("teardown (core-features): removed seeded webhook rows + KB chunks")
        return
    if only == "integration-chat":
        with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
            teardown_integration_chat(client)
        print("teardown (integration-chat): removed seeded integration-demo channels")
        return
    if only == "harness":
        with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
            teardown_harness(client)
        print("teardown (harness): removed harness scenario bot")
        return
    if only == "project-workspace":
        with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
            teardown_project_workspace(client)
        print("teardown (project-workspace): removed project workspace screenshot channel")
        return
    if only == "spatial":
        with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
            teardown_spatial(client)
        print("teardown (spatial): removed spatial canvas pins, channels, and bots")
        return
    if only == "notifications":
        with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
            teardown_notifications(client)
        print("teardown (notifications): removed seeded notification targets")
        return
    if only == "attention":
        with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
            teardown_attention(client)
        print("teardown (attention): resolved seeded attention items")
        return
    if only == "attachment-checks":
        with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
            teardown_attachments(client)
        print("teardown (attachment-checks): removed attachment screenshot channel and uploads")
        return
    if only == "channel-session-tabs":
        with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
            teardown_channel_session_tabs(client)
        print("teardown (channel-session-tabs): removed seeded session-tabs channel")
        return
    if only == "voice-input":
        with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
            teardown_voice_input(client)
        print("teardown (voice-input): removed seeded voice-input channel")
        return
    if only == "spatial-checks":
        with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
            teardown_attention(client)
            teardown_spatial(client)
        print("teardown (spatial-checks): removed attention beacons and spatial canvas records")
        return
    if only in ("widget-pin", "mobile-home", "starboard"):
        print(f"teardown ({only}): no-op — reuses other bundles' state")
        return
    with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
        if only == "flagship":
            teardown_flagship(client)
        elif only == "docs-repair":
            teardown_docs_repair(client)
        else:  # pragma: no cover
            raise ValueError(f"unknown scenario: {only!r}")
        print(f"teardown ({only}): removed scenario records")


def main() -> None:
    args = _parse()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    cfg = config.load()

    if args.action == "stage":
        _run_stage(cfg, dry_run=args.dry_run, only=args.only)
    elif args.action == "capture":
        _run_capture(cfg, only=args.only)
    elif args.action == "all":
        _run_stage(cfg, dry_run=args.dry_run, only=args.only)
        if not args.dry_run:
            _run_capture(cfg, only=args.only)
    elif args.action == "teardown":
        _run_teardown(cfg, dry_run=args.dry_run, only=args.only)
    elif args.action == "video":
        from scripts.screenshots.video import cli as video_cli
        sys.exit(video_cli.run(args.rest or []))
    elif args.action == "check":
        from scripts.screenshots.check_drift import check
        require_hero = "--require-hero" in (args.rest or [])
        sys.exit(check(require_hero=require_hero))


if __name__ == "__main__":
    main()
