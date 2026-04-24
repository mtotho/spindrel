"""Still scene — Ken Burns pan/zoom over a static PNG.

Produces a CompositeVideoClip combining the animated still with an optional
caption overlay. All text rendering is PIL-based so we don't require
ImageMagick (MoviePy's TextClip does).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from moviepy.editor import CompositeVideoClip, ImageClip, VideoClip
from PIL import Image

from scripts.screenshots.video.overlays import caption as caption_overlay
from scripts.screenshots.video.storyboard import KenBurns, Meta, Scene


def build(scene: Scene, meta: Meta) -> VideoClip:
    if not scene.asset:
        raise ValueError(f"scene {scene.id!r}: still kind requires `asset`")

    # Resolve asset relative to repo root (the storyboard validator already
    # confirmed it exists; we just need the path here).
    from scripts.screenshots.video.storyboard import _default_repo_root
    repo_root = _default_repo_root()
    asset_path = repo_root / scene.asset

    base = _ken_burns_clip(
        image_path=asset_path,
        duration=scene.duration,
        fps=meta.fps,
        output_size=meta.resolution,
        kb=scene.ken_burns,
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


def _ken_burns_clip(
    *,
    image_path: Path,
    duration: float,
    fps: int,
    output_size: tuple[int, int],
    kb: KenBurns,
) -> VideoClip:
    """Animate a crop window over a source image; resize each frame to output.

    Source image is loaded once; per-frame work is crop + resize (both fast
    enough in PIL for 30fps). Zoom, cx, cy are linearly interpolated from
    kb.start to kb.end across [0, duration].
    """
    src = Image.open(image_path).convert("RGB")
    src_w, src_h = src.size
    out_w, out_h = output_size
    # Pre-fit the source so its aspect matches output: letterbox-free crop
    # means the full output frame is always filled at zoom=1.0.
    src = _center_fit(src, out_w, out_h)
    src_w, src_h = src.size

    start_z, start_cx, start_cy = kb.start
    end_z, end_cx, end_cy = kb.end

    def make_frame(t: float) -> np.ndarray:
        u = 0.0 if duration <= 0 else min(max(t / duration, 0.0), 1.0)
        zoom = start_z + (end_z - start_z) * u
        cx = start_cx + (end_cx - start_cx) * u
        cy = start_cy + (end_cy - start_cy) * u
        # Crop window in source pixels — smaller window = more zoom
        crop_w = src_w / zoom
        crop_h = src_h / zoom
        center_x = cx * src_w
        center_y = cy * src_h
        x0 = max(0.0, min(center_x - crop_w / 2, src_w - crop_w))
        y0 = max(0.0, min(center_y - crop_h / 2, src_h - crop_h))
        cropped = src.crop((x0, y0, x0 + crop_w, y0 + crop_h))
        if cropped.size != (out_w, out_h):
            cropped = cropped.resize((out_w, out_h), Image.LANCZOS)
        return np.asarray(cropped)

    clip = VideoClip(make_frame, duration=duration)
    return clip.set_fps(fps)


def _center_fit(src: Image.Image, out_w: int, out_h: int) -> Image.Image:
    """Resize the source so the output aspect is filled without letterboxing.

    Source images may be 1440×900 (screenshots) while output is 1920×1080 —
    different aspect. We scale up to cover and center-crop to the output
    aspect ratio. The Ken Burns zoom is then applied on top of this fitted
    canvas, so the effect is predictable regardless of source dimensions.
    """
    src_w, src_h = src.size
    src_aspect = src_w / src_h
    out_aspect = out_w / out_h

    if abs(src_aspect - out_aspect) < 1e-3:
        if (src_w, src_h) == (out_w, out_h):
            return src
        return src.resize((out_w, out_h), Image.LANCZOS)

    if src_aspect > out_aspect:
        # source wider than output → scale to match height, crop sides
        new_h = out_h
        new_w = int(round(src_w * new_h / src_h))
        scaled = src.resize((new_w, new_h), Image.LANCZOS)
        x0 = (new_w - out_w) // 2
        return scaled.crop((x0, 0, x0 + out_w, new_h))
    # source taller than output → scale to match width, crop top+bottom
    new_w = out_w
    new_h = int(round(src_h * new_w / src_w))
    scaled = src.resize((new_w, new_h), Image.LANCZOS)
    y0 = (new_h - out_h) // 2
    return scaled.crop((0, y0, new_w, y0 + out_h))
