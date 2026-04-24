"""Phase B3 — manual user-supplied MP4/PNG pass-through. Not implemented in B1."""
from __future__ import annotations

from scripts.screenshots.video.storyboard import Meta, Scene


def build(scene: Scene, meta: Meta):
    raise NotImplementedError(
        f"scene {scene.id!r}: kind=manual requires Phase B3 "
        "(pass-through for user-supplied MP4/PNG under assets/manual/). "
        "See Track - Quickstart Video.md."
    )
