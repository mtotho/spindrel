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
    DOCS_REPAIR_SPECS,
    FLAGSHIP_SPECS,
    INTEGRATIONS_SPECS,
    resolve_specs,
)
from scripts.screenshots.stage.client import SpindrelClient
from scripts.screenshots.stage.scenarios.docs_repair import (
    BLUEBUBBLES_CHANNEL_CLIENT_ID,
    stage_docs_repair,
    teardown_docs_repair,
)
from scripts.screenshots.stage.scenarios.flagship import stage_flagship, teardown_flagship
from scripts.screenshots.stage.scenarios.integrations import (
    stage_integrations,
    teardown_integrations,
)


logger = logging.getLogger("screenshots")


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="screenshots")
    p.add_argument(
        "action",
        choices=["stage", "capture", "all", "teardown", "video", "check"],
    )
    p.add_argument("--only", default="flagship",
                   choices=["flagship", "docs-repair", "integrations", "a3-docs"],
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

        placeholders: dict[str, str] = {}

        if only == "integrations":
            # Routes are static (/admin/integrations/<slug>) — no placeholders.
            spec_list = INTEGRATIONS_SPECS
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


def _run_teardown(cfg: config.Config, *, dry_run: bool, only: str = "flagship"):
    if only == "integrations":
        with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
            teardown_integrations(client)
        print("teardown (integrations): reverted adopted integrations to available")
        return
    if only == "a3-docs":
        print("teardown (a3-docs): no-op — admin routes have no scenario records")
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
        sys.exit(check())


if __name__ == "__main__":
    main()
