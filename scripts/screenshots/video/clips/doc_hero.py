"""Phase B2 — doc_hero scene renderer. Not implemented in B1."""
from __future__ import annotations

from scripts.screenshots.video.storyboard import Meta, Scene


def build(scene: Scene, meta: Meta):
    raise NotImplementedError(
        f"scene {scene.id!r}: kind=doc_hero requires Phase B2 "
        "(mkdocs server + Playwright full-page screenshot + Ken Burns). "
        "See Track - Quickstart Video.md."
    )
