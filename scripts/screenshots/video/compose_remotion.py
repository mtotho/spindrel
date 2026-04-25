"""Remotion render path — parallel target to compose.py.

Resolves all storyboard scenes to PNG assets on disk, copies them into
`scripts/screenshots/video/remotion/public/` so Remotion's static-file
loader can find them, serializes the scenes + meta to a JSON props file,
and shells out to `npx remotion render` with `--props`.

The MoviePy renderer in compose.py stays the fast-iteration path; this
renderer is the higher-polish ship target for the published MP4.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from scripts.screenshots.video import _doc_capture
from scripts.screenshots.video.mkdocs_server import mkdocs_serve
from scripts.screenshots.video.storyboard import (
    KenBurns,
    Meta,
    Scene,
    Storyboard,
)


# Constants mirrored from the MoviePy clip modules (which we can't import
# from this path because moviepy itself is an optional dep). Keep these
# in sync with `clips/doc_hero.py` and `clips/doc_callout.py`.
_DOC_HERO_DEFAULT_PAN = KenBurns(start=(1.0, 0.5, 0.05), end=(1.0, 0.5, 0.95))
_DOC_CALLOUT_START_ZOOM = 1.00
_DOC_CALLOUT_END_ZOOM = 1.18


logger = logging.getLogger("screenshots.video.remotion")


TITLE_CARD_DURATION_S = 1.4
_DOC_KINDS = {"doc_hero", "doc_callout"}
_REMOTION_DIR = Path(__file__).resolve().parent / "remotion"


def render_to_file(sb: Storyboard, *, output_path: Path) -> Path:
    """Build the storyboard via Remotion. Returns the rendered MP4 path."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    public_dir = _REMOTION_DIR / "public"
    cache_dir = sb.repo_root / "scripts" / "screenshots" / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    _ensure_npm_deps()

    with _doc_view_context(sb):
        public_dir.mkdir(parents=True, exist_ok=True)
        _clear_public(public_dir)
        scenes_payload = _resolve_scenes(sb, public_dir=public_dir)

    props = {
        "meta": _meta_payload(sb.meta),
        "scenes": scenes_payload,
    }

    props_path = cache_dir / "remotion-props.json"
    props_path.write_text(json.dumps(props, indent=2))

    _invoke_remotion(props_path=props_path, output_path=output_path)
    return output_path


# ---------------------------------------------------------------- doc context


@contextmanager
def _doc_view_context(sb: Storyboard):
    """Spin up mkdocs only when at least one doc_* scene is present."""
    needs_docs = any(
        sb.scenes[sid].kind in _DOC_KINDS for sid in sb.ordered_scene_ids()
    )
    if not needs_docs:
        yield
        return
    cache_dir = sb.repo_root / "scripts" / "screenshots" / ".cache" / "doc_views"
    with mkdocs_serve(sb.repo_root) as base_url:
        _doc_capture.configure(base_url=base_url, cache_dir=cache_dir)
        yield


# ---------------------------------------------------------------- scene resolution


def _resolve_scenes(sb: Storyboard, *, public_dir: Path) -> list[dict]:
    """Walk sections in order; emit synthetic title_card scenes + real scenes.

    For each real scene, resolves the asset to a PNG on disk, drops it into
    `public/<scene_id>.png`, and returns the JSON-ready payload.
    """
    out: list[dict] = []
    for sec in sb.sections:
        if sec.title_card:
            out.append(
                {
                    "id": f"title-{sec.id}",
                    "kind": "title_card",
                    "duration": TITLE_CARD_DURATION_S,
                    "asset_url": None,
                    "caption": None,
                    "ken_burns": _kb_payload(KenBurns.identity()),
                    "fit": "cover",
                    "title": sec.title,
                }
            )
        for sid in sec.scenes:
            scene = sb.scenes[sid]
            payload = _resolve_scene(scene, sb=sb, public_dir=public_dir)
            out.append(payload)
    return out


def _resolve_scene(
    scene: Scene, *, sb: Storyboard, public_dir: Path
) -> dict:
    """Resolve one scene to a JSON payload. Heavy lifting lives in the
    existing capture helpers — we just intercept their PNG outputs."""
    if scene.kind == "still":
        if not scene.asset:
            raise ValueError(f"scene {scene.id!r}: still missing `asset`")
        src = sb.repo_root / scene.asset
        dest = _stage_asset(src, public_dir=public_dir, scene_id=scene.id)
        return {
            "id": scene.id,
            "kind": "still",
            "duration": scene.duration,
            "asset_url": dest.name,
            "caption": scene.caption,
            "ken_burns": _kb_payload(scene.ken_burns),
            "fit": "cover",
        }

    if scene.kind == "doc_hero":
        cache_key = f"hero-{scene.id}-{scene.color_scheme}"
        png = _doc_capture.capture_full_page(
            guide=scene.guide or "",
            anchor=scene.anchor,
            scheme=scene.color_scheme,
            viewport_width=sb.meta.resolution[0],
            cache_key=cache_key,
        )
        kb = scene.ken_burns
        if kb == KenBurns.identity():
            kb = _DOC_HERO_DEFAULT_PAN
        dest = _stage_asset(png, public_dir=public_dir, scene_id=scene.id)
        return {
            "id": scene.id,
            "kind": "doc_hero",
            "duration": scene.duration,
            "asset_url": dest.name,
            "caption": scene.caption,
            "ken_burns": _kb_payload(kb),
            "fit": "width",
        }

    if scene.kind == "playwright":
        from scripts.screenshots.video.recording import playwright_record

        rec_cache = sb.repo_root / "scripts" / "screenshots" / ".cache" / "recordings"
        base_url = _resolve_base_url(scene)
        mp4 = playwright_record.record_actions(
            scene_id=scene.id,
            actions=scene.actions,
            base_url=base_url,
            duration=scene.duration,
            viewport=sb.meta.resolution,
            fps=sb.meta.fps,
            output_dir=rec_cache,
            auth=_auth_bundle_for_scene(scene),
            color_scheme=scene.color_scheme,
        )
        dest = _stage_asset(mp4, public_dir=public_dir, scene_id=scene.id)
        return {
            "id": scene.id,
            "kind": "video",
            "duration": scene.duration,
            "asset_url": dest.name,
            "caption": scene.caption,
            "ken_burns": _kb_payload(KenBurns.identity()),
            "fit": "cover",
        }

    if scene.kind == "doc_callout":
        cache_key = f"callout-{scene.id}-{scene.color_scheme}"
        png, box = _doc_capture.capture_callout(
            guide=scene.guide or "",
            anchor=scene.anchor,
            highlight=scene.highlight or "",
            scheme=scene.color_scheme,
            viewport=sb.meta.resolution,
            cache_key=cache_key,
        )
        kb = scene.ken_burns
        if kb == KenBurns.identity():
            end_zoom = max(scene.zoom, _DOC_CALLOUT_END_ZOOM)
            kb = KenBurns(
                start=(_DOC_CALLOUT_START_ZOOM, 0.5, 0.5),
                end=(end_zoom, box.cx_norm, box.cy_norm),
            )
        dest = _stage_asset(png, public_dir=public_dir, scene_id=scene.id)
        return {
            "id": scene.id,
            "kind": "doc_callout",
            "duration": scene.duration,
            "asset_url": dest.name,
            "caption": scene.caption,
            "ken_burns": _kb_payload(kb),
            "fit": "cover",
        }

    raise NotImplementedError(
        f"scene {scene.id!r}: kind {scene.kind!r} not yet supported in remotion path"
    )


def _stage_asset(src: Path, *, public_dir: Path, scene_id: str) -> Path:
    """Copy the source asset into Remotion's public/ keeping the suffix
    (so .png stays .png and .mp4 stays .mp4)."""
    suffix = src.suffix.lower() or ".png"
    dest = public_dir / f"{scene_id}{suffix}"
    shutil.copyfile(src, dest)
    return dest


def _clear_public(public_dir: Path) -> None:
    """Wipe stale captures (PNG + MP4) from previous runs.

    Keep any non-asset (README, .gitkeep) files untouched.
    """
    for child in public_dir.iterdir():
        if child.is_file() and child.suffix.lower() in {".png", ".mp4", ".webm"}:
            child.unlink()


def _resolve_base_url(scene: Scene) -> str:
    """Pick the base URL for a playwright scene.

    Default is the e2e UI from screenshots config. Authors can override
    by setting an `actions:` list whose first goto is absolute, or by
    adding a sentinel action ``{js: "// base=https://example.com"}``.
    """
    from scripts.screenshots import config as cfg_mod

    try:
        return cfg_mod.load().ui_url
    except Exception:
        # Fall back to a placeholder that will fail loudly if anyone
        # actually navigates to it; only relevant when the env isn't set up.
        return "http://localhost:8080"


def _auth_bundle_for_scene(scene: Scene):
    """Mint an AuthBundle for authenticated scenes.

    The Scene schema doesn't yet carry an explicit `authenticated` flag.
    We treat any goto starting with `/` (relative path) as needing auth
    by default, since unauth'd UI redirects to the login screen.
    """
    needs_auth = any(
        ("goto" in a) and isinstance(a["goto"], str) and a["goto"].startswith("/")
        for a in scene.actions
    )
    if not needs_auth:
        return None

    from scripts.screenshots import config as cfg_mod
    from scripts.screenshots.stage.client import SpindrelClient
    from scripts.screenshots.video.recording.playwright_record import AuthBundle

    cfg = cfg_mod.load()
    if not cfg.login_email or not cfg.login_password:
        logger.warning(
            "scene %r looks authed but SPINDREL_LOGIN_* env not set; recording without auth",
            scene.id,
        )
        return None
    with SpindrelClient(cfg.api_url, cfg.api_key) as client:
        login = client.login(email=cfg.login_email, password=cfg.login_password)
    return AuthBundle(
        api_url=cfg.api_url,
        access_token=login["access_token"],
        refresh_token=login["refresh_token"],
        user=login["user"],
    )


# ---------------------------------------------------------------- payload helpers


def _meta_payload(meta: Meta) -> dict:
    return {
        "title": meta.title,
        "slug": meta.slug,
        "resolution": list(meta.resolution),
        "fps": meta.fps,
        "transition": meta.transition,
        "transition_duration": meta.transition_duration,
        "watermark": (
            {"text": meta.watermark.text, "opacity": meta.watermark.opacity}
            if meta.watermark
            else None
        ),
        "caption_style": asdict(meta.caption_style),
    }


def _kb_payload(kb: KenBurns) -> dict:
    return {"start": list(kb.start), "end": list(kb.end)}


# ---------------------------------------------------------------- node invocation


def _ensure_npm_deps() -> None:
    """Install npm deps once if `node_modules` is missing.

    The remotion bundle is checked in but its node_modules are not — first
    render after a fresh clone needs `npm ci`.
    """
    nm = _REMOTION_DIR / "node_modules"
    if nm.exists():
        return
    logger.info("installing remotion npm deps (one-time) …")
    proc = subprocess.run(
        ["npm", "ci", "--silent"],
        cwd=_REMOTION_DIR,
        check=False,
    )
    if proc.returncode != 0:
        # `npm ci` requires package-lock.json; fall back to `npm install`.
        subprocess.run(
            ["npm", "install", "--silent"],
            cwd=_REMOTION_DIR,
            check=True,
        )


def _invoke_remotion(*, props_path: Path, output_path: Path) -> None:
    cmd = [
        "npx",
        "remotion",
        "render",
        "src/index.ts",
        "Quickstart",
        str(output_path),
        f"--props={props_path}",
    ]
    logger.info("remotion render: %s", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=_REMOTION_DIR, check=False)
    if proc.returncode != 0:
        sys.exit(proc.returncode)
