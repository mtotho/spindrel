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

# Doc-hero scenes capture full-page screenshots that can exceed PIL's
# default decompression-bomb threshold for very long guides. These are
# our own renders, never untrusted input.
Image.MAX_IMAGE_PIXELS = None

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

    return build_from_image(
        image_path=asset_path,
        scene=scene,
        meta=meta,
        kb=scene.ken_burns,
    )


def build_from_image(
    *,
    image_path: Path,
    scene: Scene,
    meta: Meta,
    kb: KenBurns,
    fit: str = "cover",
) -> VideoClip:
    """Public helper: render a Ken Burns clip from any image + scene metadata.

    `fit` controls how the source is mapped onto the output frame before
    the Ken Burns crop is applied:
    - ``cover`` — center-fit so output is filled (default; matches still).
    - ``width`` — scale source to output width; height may exceed output and
      will be panned by the Ken Burns vertical crop. Used by doc_hero for
      tall full-page screenshots.
    """
    base = _ken_burns_clip(
        image_path=image_path,
        duration=scene.duration,
        fps=meta.fps,
        output_size=meta.resolution,
        kb=kb,
        fit=fit,
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
    fit: str = "cover",
) -> VideoClip:
    """Animate a crop window over a source image; resize each frame to output.

    Source image is loaded once; per-frame work is crop + resize (both fast
    enough in PIL for 30fps). Zoom, cx, cy are linearly interpolated from
    kb.start to kb.end across [0, duration].

    `fit="cover"` center-crops to output aspect (good for hero stills).
    `fit="width"` scales to output width — height grows; used for tall
    full-page screenshots that should pan vertically.
    """
    src = Image.open(image_path).convert("RGB")
    out_w, out_h = output_size
    if fit == "width":
        src = _fit_width(src, out_w, out_h)
    else:
        src = _center_fit(src, out_w, out_h)
    src_w, src_h = src.size

    start_z, start_cx, start_cy = kb.start
    end_z, end_cx, end_cy = kb.end

    def make_frame(t: float) -> np.ndarray:
        u = 0.0 if duration <= 0 else min(max(t / duration, 0.0), 1.0)
        zoom = start_z + (end_z - start_z) * u
        cx = start_cx + (end_cx - start_cx) * u
        cy = start_cy + (end_cy - start_cy) * u
        # Crop window in source pixels — smaller window = more zoom.
        # For fit="cover" the source has output aspect, so cropping in src
        # coords stays output-aspect. For fit="width" the source can be much
        # taller than output, so the crop window must be derived from the
        # output dims to keep the rendered frame from squashing.
        if fit == "width":
            crop_w = out_w / zoom
            crop_h = out_h / zoom
        else:
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


def _fit_width(src: Image.Image, out_w: int, out_h: int) -> Image.Image:
    """Scale source so its width equals out_w; height scales proportionally.

    Used for tall full-page screenshots where the Ken Burns will pan
    vertically. If the source is already too short to cover even one
    output frame, pad-bottom with the bottom-most pixel row so cropping
    doesn't read past the source.
    """
    src_w, src_h = src.size
    if src_w == out_w:
        scaled = src
    else:
        new_h = max(1, int(round(src_h * out_w / src_w)))
        scaled = src.resize((out_w, new_h), Image.LANCZOS)
    if scaled.size[1] >= out_h:
        return scaled
    # Pad short pages so the crop math has somewhere to land.
    padded = Image.new("RGB", (out_w, out_h), color=(0, 0, 0))
    padded.paste(scaled, (0, 0))
    return padded


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
