"""Phase B2 — doc_callout scene renderer.

Navigates to a guide URL, scrolls the highlight selector to viewport
center, decorates it with a glowing ring, and zooms the Ken Burns crop
into the highlight bbox over the scene's duration.
"""
from __future__ import annotations

from scripts.screenshots.video import _doc_capture
from scripts.screenshots.video.clips import still
from scripts.screenshots.video.storyboard import KenBurns, Meta, Scene


# Default zoom envelope: start at the surrounding viewport, end zoomed in
# on the highlight. Authors can override either endpoint via ken_burns.
_DEFAULT_START_ZOOM = 1.00
_DEFAULT_END_ZOOM = 1.18


def build(scene: Scene, meta: Meta):
    if not scene.guide:
        raise ValueError(f"scene {scene.id!r}: doc_callout requires `guide`")
    if not scene.highlight:
        raise ValueError(
            f"scene {scene.id!r}: doc_callout requires `highlight` selector"
        )

    cache_key = f"callout-{scene.id}-{scene.color_scheme}"
    image_path, box = _doc_capture.capture_callout(
        guide=scene.guide,
        anchor=scene.anchor,
        highlight=scene.highlight,
        scheme=scene.color_scheme,
        viewport=meta.resolution,
        cache_key=cache_key,
    )

    # If the author specified an explicit ken_burns we honor it; otherwise
    # build a zoom-into-callout envelope using the resolved bbox center.
    kb = scene.ken_burns
    if kb == KenBurns.identity():
        end_zoom = max(scene.zoom, _DEFAULT_END_ZOOM)
        kb = KenBurns(
            start=(_DEFAULT_START_ZOOM, 0.5, 0.5),
            end=(end_zoom, box.cx_norm, box.cy_norm),
        )

    return still.build_from_image(
        image_path=image_path,
        scene=scene,
        meta=meta,
        kb=kb,
        fit="cover",
    )
