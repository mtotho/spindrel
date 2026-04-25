"""Storyboard dataclasses + YAML loader + validation.

The storyboard YAML is the one hand-edited artifact that drives the whole
video pipeline. All scene kinds are defined here so the schema is stable
across phases even though only `still` renders in B1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml


SceneKind = Literal["still", "doc_hero", "doc_callout", "playwright", "manual"]
KNOWN_KINDS: frozenset[str] = frozenset(
    ["still", "doc_hero", "doc_callout", "playwright", "manual"]
)
# Implemented right now. Others are schema-reserved; clip modules raise at
# render time with a phase marker.
IMPLEMENTED_KINDS: frozenset[str] = frozenset(["still", "doc_hero", "doc_callout"])


@dataclass
class KenBurns:
    """Ken Burns pan/zoom. start/end are (zoom, cx, cy) in normalized coords.

    zoom >= 1.0 (1.0 = no zoom). cx, cy in [0, 1] — the normalized center of
    the visible crop on the source image. A subtle effect reads as motion
    without being distracting; start/end zooms between 1.00 and 1.08 are the
    usual band.
    """
    start: tuple[float, float, float]
    end: tuple[float, float, float]

    @classmethod
    def identity(cls) -> "KenBurns":
        return cls(start=(1.0, 0.5, 0.5), end=(1.0, 0.5, 0.5))


@dataclass
class Audio:
    """Phase B4 — reserved in B1 schema, never used by B1 renderer."""
    text: str | None = None
    voice: str | None = None
    file: str | None = None


@dataclass
class Scene:
    id: str
    kind: SceneKind
    duration: float
    caption: str | None = None
    # kind=still | manual
    asset: str | None = None
    ken_burns: KenBurns = field(default_factory=KenBurns.identity)
    # kind=doc_hero | doc_callout (phase B2)
    guide: str | None = None
    anchor: str | None = None
    highlight: str | None = None
    scroll: str | list[float] | None = None
    zoom: float = 1.0
    color_scheme: Literal["light", "dark"] = "dark"
    # kind=playwright (phase B3)
    actions: list[dict[str, Any]] = field(default_factory=list)
    # phase B4
    audio: Audio | None = None


@dataclass
class CaptionStyle:
    position: Literal["top", "bottom"] = "bottom"
    font_size: int = 36
    padding: int = 48
    bg_opacity: float = 0.55


@dataclass
class Watermark:
    text: str
    opacity: float = 0.5


@dataclass
class Meta:
    title: str
    slug: str = "quickstart"
    output_dir: str = "docs/videos/"
    resolution: tuple[int, int] = (1920, 1080)
    fps: int = 30
    transition: Literal["crossfade", "cut"] = "crossfade"
    transition_duration: float = 0.5
    watermark: Watermark | None = None
    caption_style: CaptionStyle = field(default_factory=CaptionStyle)


@dataclass
class Section:
    id: str
    title: str
    scenes: list[str]
    title_card: bool = True


@dataclass
class Storyboard:
    meta: Meta
    sections: list[Section]
    scenes: dict[str, Scene]
    source_path: Path
    repo_root: Path

    def ordered_scene_ids(self) -> list[str]:
        """Scene ids in section order — the render sequence."""
        out: list[str] = []
        for sec in self.sections:
            out.extend(sec.scenes)
        return out

    def total_duration(self) -> float:
        return sum(self.scenes[sid].duration for sid in self.ordered_scene_ids())


# ------------------------------------------------------------------ loader


def load(path: Path, *, repo_root: Path | None = None) -> Storyboard:
    """Load + validate a storyboard. Fails loudly on any structural error."""
    if not path.exists():
        raise FileNotFoundError(f"storyboard not found: {path}")
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: top-level must be a mapping")

    repo_root = repo_root or _default_repo_root()

    meta = _parse_meta(raw.get("meta", {}))

    scenes: dict[str, Scene] = {}
    for raw_scene in raw.get("scenes", []):
        scene = _parse_scene(raw_scene)
        if scene.id in scenes:
            raise ValueError(f"duplicate scene id: {scene.id!r}")
        scenes[scene.id] = scene

    sections: list[Section] = []
    for raw_sec in raw.get("sections", []):
        sections.append(
            Section(
                id=raw_sec["id"],
                title=raw_sec.get("title", raw_sec["id"]),
                scenes=list(raw_sec.get("scenes", [])),
                title_card=bool(raw_sec.get("title_card", True)),
            )
        )

    sb = Storyboard(
        meta=meta,
        sections=sections,
        scenes=scenes,
        source_path=path,
        repo_root=repo_root,
    )
    _validate(sb)
    return sb


def _default_repo_root() -> Path:
    # Walk up from this file (scripts/screenshots/video/storyboard.py) to repo root.
    here = Path(__file__).resolve()
    return here.parents[3]


def _parse_meta(raw: dict) -> Meta:
    wm_raw = raw.get("watermark")
    watermark = None
    if wm_raw:
        watermark = Watermark(
            text=wm_raw["text"],
            opacity=float(wm_raw.get("opacity", 0.5)),
        )
    cs_raw = raw.get("caption_style", {})
    caption_style = CaptionStyle(
        position=cs_raw.get("position", "bottom"),
        font_size=int(cs_raw.get("font_size", 36)),
        padding=int(cs_raw.get("padding", 48)),
        bg_opacity=float(cs_raw.get("bg_opacity", 0.55)),
    )
    res = raw.get("resolution", [1920, 1080])
    return Meta(
        title=raw.get("title", "Untitled"),
        slug=raw.get("slug", "quickstart"),
        output_dir=raw.get("output_dir", "docs/videos/"),
        resolution=(int(res[0]), int(res[1])),
        fps=int(raw.get("fps", 30)),
        transition=raw.get("transition", "crossfade"),
        transition_duration=float(raw.get("transition_duration", 0.5)),
        watermark=watermark,
        caption_style=caption_style,
    )


def _parse_scene(raw: dict) -> Scene:
    kb_raw = raw.get("ken_burns")
    ken_burns: KenBurns
    if kb_raw:
        ken_burns = KenBurns(
            start=tuple(kb_raw["start"]),  # type: ignore[arg-type]
            end=tuple(kb_raw["end"]),      # type: ignore[arg-type]
        )
    else:
        ken_burns = KenBurns.identity()

    audio_raw = raw.get("audio")
    audio = Audio(**audio_raw) if audio_raw else None

    return Scene(
        id=raw["id"],
        kind=raw["kind"],
        duration=float(raw["duration"]),
        caption=raw.get("caption"),
        asset=raw.get("asset"),
        ken_burns=ken_burns,
        guide=raw.get("guide"),
        anchor=raw.get("anchor"),
        highlight=raw.get("highlight"),
        scroll=raw.get("scroll"),
        zoom=float(raw.get("zoom", 1.0)),
        color_scheme=raw.get("color_scheme", "dark"),
        actions=list(raw.get("actions", [])),
        audio=audio,
    )


# ------------------------------------------------------------------ validate


def _validate(sb: Storyboard) -> None:
    # Every scene id referenced by a section must exist
    for sec in sb.sections:
        for sid in sec.scenes:
            if sid not in sb.scenes:
                raise ValueError(
                    f"section {sec.id!r} references unknown scene {sid!r}"
                )

    # Every scene kind must be known (implementation check is per-clip at render)
    for scene in sb.scenes.values():
        if scene.kind not in KNOWN_KINDS:
            raise ValueError(
                f"scene {scene.id!r}: unknown kind {scene.kind!r} "
                f"(known: {sorted(KNOWN_KINDS)})"
            )

    # Per-kind required-field checks
    for scene in sb.scenes.values():
        if scene.kind == "still":
            if not scene.asset:
                raise ValueError(f"scene {scene.id!r} (still) missing `asset`")
            _assert_asset_exists(sb.repo_root, scene.asset, scene.id)
        elif scene.kind == "manual":
            if not scene.asset:
                raise ValueError(f"scene {scene.id!r} (manual) missing `asset`")
            # At B1 we don't render manual, so don't insist the file exists yet —
            # that check moves to the manual clip module in B3.
        elif scene.kind in ("doc_hero", "doc_callout"):
            if not scene.guide:
                raise ValueError(f"scene {scene.id!r} ({scene.kind}) missing `guide`")
            if scene.kind == "doc_callout" and not scene.highlight:
                raise ValueError(
                    f"scene {scene.id!r} (doc_callout) missing `highlight` selector"
                )

    # Warn (via ValueError? no — silent for now) about scenes not referenced by any section.
    # Unused scenes are fine during authoring; they just don't appear in the render.


def _assert_asset_exists(repo_root: Path, asset: str, scene_id: str) -> None:
    path = repo_root / asset
    if not path.exists():
        raise FileNotFoundError(
            f"scene {scene_id!r}: asset {asset!r} not found at {path}"
        )
