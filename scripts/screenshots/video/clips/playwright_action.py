"""Phase B3 — kind=playwright clip.

Drives the recording module to capture a real-time screencast of a list
of scripted actions, then loads the resulting mp4 as a MoviePy clip with
an optional caption overlay (matching the still-clip behavior).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from moviepy.editor import (
    CompositeVideoClip,
    ImageClip,
    VideoClip,
    VideoFileClip,
)

from scripts.screenshots.video.overlays import caption as caption_overlay
from scripts.screenshots.video.recording import playwright_record
from scripts.screenshots.video.storyboard import Meta, Scene


def build(scene: Scene, meta: Meta) -> VideoClip:
    if not scene.actions:
        raise ValueError(f"scene {scene.id!r}: kind=playwright requires `actions`")

    rec_cache = _repo_root() / "scripts" / "screenshots" / ".cache" / "recordings"
    mp4 = playwright_record.record_actions(
        scene_id=scene.id,
        actions=scene.actions,
        base_url=_default_base_url(),
        duration=scene.duration,
        viewport=meta.resolution,
        fps=meta.fps,
        output_dir=rec_cache,
        auth=_auth_bundle(scene),
        color_scheme=scene.color_scheme,
    )

    base = (
        VideoFileClip(str(mp4))
        .subclip(0, scene.duration)
        .resize(newsize=meta.resolution)
        .set_fps(meta.fps)
    )
    if not scene.caption:
        return base

    cap_png = caption_overlay.render(
        text=scene.caption,
        video_width=meta.resolution[0],
        style=meta.caption_style,
    )
    cap_clip = (
        ImageClip(np.array(cap_png))
        .set_duration(scene.duration)
        .set_position(("center", _caption_y(cap_png.height, meta)))
    )
    return CompositeVideoClip([base, cap_clip], size=meta.resolution)


def _caption_y(caption_height: int, meta: Meta) -> int:
    pad = meta.caption_style.padding
    if meta.caption_style.position == "top":
        return pad
    return meta.resolution[1] - caption_height - pad


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_base_url() -> str:
    from scripts.screenshots import config as cfg_mod

    try:
        return cfg_mod.load().ui_url
    except Exception:
        return "http://localhost:8080"


def _auth_bundle(scene: Scene):
    needs_auth = any(
        ("goto" in a) and isinstance(a["goto"], str) and a["goto"].startswith("/")
        for a in scene.actions
    )
    if not needs_auth:
        return None

    from scripts.screenshots import config as cfg_mod
    from scripts.screenshots.stage.client import SpindrelClient

    cfg = cfg_mod.load()
    if not cfg.login_email or not cfg.login_password:
        return None
    with SpindrelClient(cfg.api_url, cfg.api_key) as client:
        login = client.login(email=cfg.login_email, password=cfg.login_password)
    return playwright_record.AuthBundle(
        api_url=cfg.api_url,
        access_token=login["access_token"],
        refresh_token=login["refresh_token"],
        user=login["user"],
    )
