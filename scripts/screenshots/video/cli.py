"""`video` subcommand — build | preview | plan.

Invoked via `python -m scripts.screenshots video <subcommand> [args]`.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from scripts.screenshots.video import compose, storyboard


logger = logging.getLogger("screenshots.video.cli")


DEFAULT_STORYBOARD = (
    Path(__file__).resolve().parents[1]
    / "storyboards"
    / "quickstart.yml"
)


def run(argv: list[str]) -> int:
    """Parse `video <sub> ...` args and dispatch. Returns an exit code."""
    parser = argparse.ArgumentParser(prog="screenshots video")
    sub = parser.add_subparsers(dest="sub", required=True)

    p_build = sub.add_parser("build", help="Build the full video")
    p_build.add_argument("--storyboard", type=Path, default=DEFAULT_STORYBOARD)
    p_build.add_argument(
        "--skip-capture", action="store_true",
        help="Skip re-staging + capturing screenshots; use existing docs/images/",
    )

    p_preview = sub.add_parser("preview", help="Render one scene for iteration")
    p_preview.add_argument("--scene", required=True, help="Scene id")
    p_preview.add_argument("--storyboard", type=Path, default=DEFAULT_STORYBOARD)

    p_plan = sub.add_parser("plan", help="Print the storyboard outline")
    p_plan.add_argument("--storyboard", type=Path, default=DEFAULT_STORYBOARD)

    args = parser.parse_args(argv)

    if args.sub == "plan":
        return _cmd_plan(args.storyboard)
    if args.sub == "preview":
        return _cmd_preview(args.storyboard, args.scene)
    if args.sub == "build":
        return _cmd_build(args.storyboard, skip_capture=args.skip_capture)
    parser.error(f"unknown subcommand: {args.sub}")
    return 2


def _cmd_plan(path: Path) -> int:
    sb = storyboard.load(path)
    print(compose.plan_outline(sb))
    return 0


def _cmd_preview(path: Path, scene_id: str) -> int:
    sb = storyboard.load(path)
    out_dir = sb.repo_root / sb.meta.output_dir / "preview"
    out_path = out_dir / f"{scene_id}.mp4"
    compose.render_to_file(sb, output_path=out_path, only_scene=scene_id)
    print(f"wrote {out_path}")
    return 0


def _cmd_build(path: Path, *, skip_capture: bool) -> int:
    sb = storyboard.load(path)

    if not skip_capture:
        # Import lazily so `video plan` / `preview` don't pull the capture
        # stack (playwright auth etc.) when they don't need it.
        logger.info("refreshing screenshots via stage + capture …")
        _run_stage_and_capture()
        # After capture, re-validate: assets should all exist.
        sb = storyboard.load(path)

    out_dir = sb.repo_root / sb.meta.output_dir
    out_path = out_dir / f"{sb.meta.slug}.mp4"
    compose.render_to_file(sb, output_path=out_path)
    print(f"wrote {out_path}")
    return 0


def _run_stage_and_capture() -> None:
    """Delegate to the existing screenshots CLI in-process."""
    from scripts.screenshots import cli as main_cli
    from scripts.screenshots import config as cfg_mod

    cfg = cfg_mod.load()
    main_cli._run_stage(cfg, dry_run=False)
    main_cli._run_capture(cfg)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run(sys.argv[1:]))
