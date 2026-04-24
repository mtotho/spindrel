"""Clip builders — one module per scene kind.

Each builder returns a MoviePy VideoClip of exact `scene.duration` and
matching the storyboard's `meta.resolution`. The compositor is ignorant of
kind; it just concatenates clips with transitions + overlays captions.
"""
from __future__ import annotations

from scripts.screenshots.video.storyboard import Meta, Scene

from . import doc_callout, doc_hero, manual, playwright_action, still


def build_clip(scene: Scene, meta: Meta):
    """Dispatch on scene.kind → returns a VideoClip.

    Unimplemented kinds raise NotImplementedError with the phase tag so the
    CLI can surface a clean "this needs phase Bn" error instead of crashing.
    """
    if scene.kind == "still":
        return still.build(scene, meta)
    if scene.kind == "doc_hero":
        return doc_hero.build(scene, meta)
    if scene.kind == "doc_callout":
        return doc_callout.build(scene, meta)
    if scene.kind == "playwright":
        return playwright_action.build(scene, meta)
    if scene.kind == "manual":
        return manual.build(scene, meta)
    raise ValueError(f"scene {scene.id!r}: unknown kind {scene.kind!r}")
