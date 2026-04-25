"""Phase B2 — doc_hero scene renderer.

Captures a full-page mkdocs render of a guide and pans it vertically over
the scene's duration. The pan defaults to a top→bottom scroll if the scene
declares no explicit `ken_burns`; an explicit override (e.g. for a fixed
hero shot) is honored as-is.
"""
from __future__ import annotations

from scripts.screenshots.video import _doc_capture
from scripts.screenshots.video.clips import still
from scripts.screenshots.video.storyboard import KenBurns, Meta, Scene


# Default vertical pan for a full-page doc hero. cy=0 places the crop at
# the page top, cy=1 at the bottom; clamping inside `_ken_burns_clip` keeps
# the window inside the source.
_DEFAULT_PAN = KenBurns(start=(1.0, 0.5, 0.05), end=(1.0, 0.5, 0.95))


def build(scene: Scene, meta: Meta):
    if not scene.guide:
        raise ValueError(f"scene {scene.id!r}: doc_hero requires `guide`")

    cache_key = f"hero-{scene.id}-{scene.color_scheme}"
    image_path = _doc_capture.capture_full_page(
        guide=scene.guide,
        anchor=scene.anchor,
        scheme=scene.color_scheme,
        viewport_width=meta.resolution[0],
        cache_key=cache_key,
    )

    # An author who wrote `ken_burns:` in the storyboard meant it. Otherwise
    # default to a slow vertical scroll across the whole page.
    kb = scene.ken_burns
    if kb == KenBurns.identity():
        kb = _DEFAULT_PAN

    return still.build_from_image(
        image_path=image_path,
        scene=scene,
        meta=meta,
        kb=kb,
        fit="width",
    )
