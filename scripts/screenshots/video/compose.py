"""Compose a full video from a Storyboard.

Walks sections in order; for each section emits an optional title card
followed by its scenes. Transitions are crossfades between scene boundaries
(including across section boundaries). A watermark overlay is composited
over the entire video.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path

import numpy as np
from moviepy.editor import (
    ColorClip,
    CompositeVideoClip,
    ImageClip,
    VideoClip,
    concatenate_videoclips,
)

from scripts.screenshots.video import _doc_capture
from scripts.screenshots.video.clips import build_clip
from scripts.screenshots.video.mkdocs_server import mkdocs_serve
from scripts.screenshots.video.overlays import title_card as title_card_overlay
from scripts.screenshots.video.overlays import watermark as watermark_overlay
from scripts.screenshots.video.storyboard import Meta, Storyboard


_DOC_KINDS = {"doc_hero", "doc_callout"}


logger = logging.getLogger("screenshots.video")

TITLE_CARD_DURATION = 1.4


def render_to_file(
    sb: Storyboard,
    *,
    output_path: Path,
    only_scene: str | None = None,
) -> Path:
    """Build the final clip and write it to `output_path`.

    If `only_scene` is set, renders just that single scene (used by the
    `video preview` subcommand for fast iteration).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with _doc_view_context(sb, only_scene=only_scene):
        if only_scene:
            clip = _build_single(sb, only_scene)
        else:
            clip = _build_full(sb)
        _write(clip, output_path, fps=sb.meta.fps)
    return output_path


@contextmanager
def _doc_view_context(sb: Storyboard, *, only_scene: str | None):
    """Spin up mkdocs only when at least one rendered scene needs it."""
    if only_scene:
        scene_ids = [only_scene]
    else:
        scene_ids = sb.ordered_scene_ids()
    needs_docs = any(sb.scenes[sid].kind in _DOC_KINDS for sid in scene_ids)
    if not needs_docs:
        yield
        return
    cache_dir = sb.repo_root / "scripts" / "screenshots" / ".cache" / "doc_views"
    with mkdocs_serve(sb.repo_root) as base_url:
        _doc_capture.configure(base_url=base_url, cache_dir=cache_dir)
        yield


# -------------------------------------------------------------- single preview


def _build_single(sb: Storyboard, scene_id: str) -> VideoClip:
    if scene_id not in sb.scenes:
        raise KeyError(f"scene id not found in storyboard: {scene_id!r}")
    scene = sb.scenes[scene_id]
    base = build_clip(scene, sb.meta)
    return _with_watermark(base, sb.meta)


# -------------------------------------------------------------- full build


def _build_full(sb: Storyboard) -> VideoClip:
    segments: list[VideoClip] = []

    for sec in sb.sections:
        if sec.title_card:
            segments.append(_title_card_clip(sec.title, sb.meta))
        for sid in sec.scenes:
            scene = sb.scenes[sid]
            segments.append(build_clip(scene, sb.meta))

    if not segments:
        raise ValueError("storyboard has no renderable scenes")

    trans = sb.meta.transition_duration if sb.meta.transition == "crossfade" else 0.0
    if trans > 0 and len(segments) > 1:
        # Apply crossfadein to all but the first, then concatenate with the
        # "compose" method and a negative padding so the transitions overlap.
        faded = [segments[0]]
        for seg in segments[1:]:
            faded.append(seg.crossfadein(trans))
        final = concatenate_videoclips(faded, method="compose", padding=-trans)
    else:
        final = concatenate_videoclips(segments, method="compose")

    return _with_watermark(final, sb.meta)


def _title_card_clip(title: str, meta: Meta) -> VideoClip:
    img = title_card_overlay.render(title=title, video_size=meta.resolution)
    # ImageClip expects a numpy array; use the solid-background rendering.
    clip = (
        ImageClip(np.array(img.convert("RGB")))
        .set_duration(TITLE_CARD_DURATION)
        .set_fps(meta.fps)
    )
    return clip


# -------------------------------------------------------------- watermark


def _with_watermark(base: VideoClip, meta: Meta) -> VideoClip:
    if not meta.watermark:
        return base
    wm_img = watermark_overlay.render(wm=meta.watermark, video_size=meta.resolution)
    wm_clip = ImageClip(np.array(wm_img)).set_duration(base.duration)
    return CompositeVideoClip([base, wm_clip], size=meta.resolution).set_fps(meta.fps)


# -------------------------------------------------------------- encoder


def _write(clip: VideoClip, output_path: Path, *, fps: int) -> None:
    logger.info("rendering %s (%.1fs, %dx%d @ %dfps)",
                output_path, clip.duration, *clip.size, fps)
    clip.write_videofile(
        str(output_path),
        fps=fps,
        codec="libx264",
        audio=False,
        preset="medium",
        ffmpeg_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart"],
        # MoviePy writes a progress bar by default; keep it — it's useful
        # during long renders.
        logger="bar",
    )


# -------------------------------------------------------------- for `plan`


def plan_outline(sb: Storyboard) -> str:
    """Render a human-readable outline string for the `video plan` CLI."""
    out: list[str] = []
    out.append(f"{sb.meta.title} — {sb.meta.resolution[0]}x{sb.meta.resolution[1]}"
               f"@{sb.meta.fps}, {sb.meta.transition} {sb.meta.transition_duration}s")
    out.append("")
    total_offset = 0.0
    total_scenes = 0
    total_kinds: set[str] = set()
    for sec in sb.sections:
        sec_start = total_offset
        if sec.title_card:
            total_offset += TITLE_CARD_DURATION
        sec_scene_time = 0.0
        for sid in sec.scenes:
            scene = sb.scenes[sid]
            sec_scene_time += scene.duration
            total_kinds.add(scene.kind)
            total_scenes += 1
        sec_dur = total_offset + sec_scene_time - sec_start
        out.append(f"§ {sec.title} — {_fmt_time(sec_start)} → "
                   f"{_fmt_time(sec_start + sec_dur)} ({sec_dur:.1f}s)")
        if sec.title_card:
            out.append(f"  · (title card)         {TITLE_CARD_DURATION:.1f}s")
        for sid in sec.scenes:
            scene = sb.scenes[sid]
            flag = "" if scene.kind in ("still",) else f"  [phase {_phase_for(scene.kind)}]"
            cap = (scene.caption or "").strip()
            if len(cap) > 60:
                cap = cap[:57] + "…"
            out.append(f"  · {scene.id:<22} {scene.kind:<14} "
                       f"{scene.duration:>4.1f}s   {cap!r}{flag}")
        out.append("")
        total_offset += sec_scene_time

    out.append(f"Total: {_fmt_time(total_offset)}  ·  "
               f"{len(sb.sections)} sections  ·  "
               f"{total_scenes} scenes  ·  {len(total_kinds)} kinds")
    return "\n".join(out)


def _fmt_time(t: float) -> str:
    m, s = divmod(int(round(t)), 60)
    return f"{m:02d}:{s:02d}"


def _phase_for(kind: str) -> str:
    return {
        "still": "B1",
        "doc_hero": "B2",
        "doc_callout": "B2",
        "playwright": "B3",
        "manual": "B3",
    }.get(kind, "?")
