"""Phase B2 — doc_callout scene renderer. Not implemented in B1."""
from __future__ import annotations

from scripts.screenshots.video.storyboard import Meta, Scene


def build(scene: Scene, meta: Meta):
    raise NotImplementedError(
        f"scene {scene.id!r}: kind=doc_callout requires Phase B2 "
        "(mkdocs server + highlight-box overlay + zoom-to-anchor). "
        "See Track - Quickstart Video.md."
    )
