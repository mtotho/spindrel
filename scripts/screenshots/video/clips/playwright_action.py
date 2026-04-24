"""Phase B3 — playwright action recording. Not implemented in B1."""
from __future__ import annotations

from scripts.screenshots.video.storyboard import Meta, Scene


def build(scene: Scene, meta: Meta):
    raise NotImplementedError(
        f"scene {scene.id!r}: kind=playwright requires Phase B3 "
        "(scripted actions + record_video_dir context + trim). "
        "See Track - Quickstart Video.md."
    )
