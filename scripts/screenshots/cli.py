"""Entrypoint for the screenshot pipeline.

Usage:
    python -m scripts.screenshots stage    --only flagship [--dry-run]
    python -m scripts.screenshots capture  --only flagship
    python -m scripts.screenshots all      --only flagship [--dry-run]
    python -m scripts.screenshots teardown --only flagship
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
from scripts.screenshots.capture.specs import FLAGSHIP_SPECS, resolve_specs
from scripts.screenshots.stage.client import SpindrelClient
from scripts.screenshots.stage.scenarios.flagship import stage_flagship, teardown_flagship


logger = logging.getLogger("screenshots")


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="screenshots")
    p.add_argument("action", choices=["stage", "capture", "all", "teardown"])
    p.add_argument("--only", default="flagship", choices=["flagship"],
                   help="scenario bundle (only flagship for now)")
    p.add_argument("--dry-run", action="store_true",
                   help="log writes without executing (stage/teardown only)")
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args()


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


def _run_stage(cfg: config.Config, *, dry_run: bool):
    with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
        state = stage_flagship(
            client,
            ssh_alias=cfg.ssh_alias,
            ssh_container=cfg.ssh_container,
            dry_run=dry_run,
        )
        print("staged:")
        for k, v in asdict(state).items():
            print(f"  {k}: {v}")
        return state


def _run_capture(cfg: config.Config):
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

        # Rebuild placeholder map from stable client_ids
        all_channels = {c.get("client_id"): c for c in client.list_channels()}
        def _chan(cid: str) -> str:
            ch = all_channels.get(cid)
            if not ch:
                raise SystemExit(
                    f"Channel with client_id {cid!r} not found. Run `stage` first."
                )
            return str(ch["id"])

        placeholders: dict[str, str] = {
            "chat_main":       _chan("screenshot:chat-main"),
            "demo_dashboard":  _chan("screenshot:demo-dashboard"),
            "pipeline":        _chan("screenshot:pipeline-demo"),
        }
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

    specs = resolve_specs(FLAGSHIP_SPECS, placeholders)

    # Dev-panel localStorage seed (bot + channel context the sandbox restores).
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


def _run_teardown(cfg: config.Config, *, dry_run: bool):
    with SpindrelClient(cfg.api_url, cfg.api_key, dry_run=dry_run) as client:
        teardown_flagship(client)
        print("teardown: removed all screenshot:* records")


def main() -> None:
    args = _parse()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    cfg = config.load()

    if args.action == "stage":
        _run_stage(cfg, dry_run=args.dry_run)
    elif args.action == "capture":
        _run_capture(cfg)
    elif args.action == "all":
        _run_stage(cfg, dry_run=args.dry_run)
        if not args.dry_run:
            _run_capture(cfg)
    elif args.action == "teardown":
        _run_teardown(cfg, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
