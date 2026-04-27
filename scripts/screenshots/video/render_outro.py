"""Render the quickstart outro card to ``docs/images/quickstart-outro.png``.

The outro is referenced by ``storyboards/quickstart.yml`` as a ``kind: still``
scene so both the MoviePy and Remotion renderers handle it via the existing
still pipeline. Run this once after editing copy below; the storyboard
validator will fail if the asset is missing.

    python -m scripts.screenshots.video.render_outro
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from scripts.screenshots.video.overlays.caption import _font, _text_width


# 1920×1080 matches storyboard meta.resolution. Centered layout — the still
# pipeline applies an identity Ken Burns so this gets blitted as-is.
_W, _H = 1920, 1080


_TITLE = "Spindrel"
_TAGLINE = "Channels · Widgets · Pipelines · Skills"
_RECAP = "A workspace, as a place — your bots, dashboards, and scheduled jobs in one canvas."
_SUBLINE = "Bring your own agent — Claude Code · Codex SDK soon"
_LINKS = [
    ("Code", "github.com/mtotho/spindrel"),
    ("Docs", "docs.spindrel.dev"),
]


def render() -> Image.Image:
    img = Image.new("RGB", (_W, _H), (10, 12, 18))
    draw = ImageDraw.Draw(img)

    title_font = _font(168)
    tagline_font = _font(44)
    recap_font = _font(36)
    label_font = _font(28)
    url_font = _font(40)

    # Vertical layout — pin from center outward so resolution swaps still
    # land cleanly. Title sits 16% above center; links sit 18% below.
    cy = _H // 2

    title_w = _text_width(_TITLE, title_font)
    title_y = cy - int(_H * 0.18) - 168 // 2
    draw.text(((_W - title_w) // 2, title_y), _TITLE, font=title_font, fill=(245, 245, 250))

    tagline_w = _text_width(_TAGLINE, tagline_font)
    tagline_y = title_y + 168 + 24
    draw.text(((_W - tagline_w) // 2, tagline_y), _TAGLINE, font=tagline_font, fill=(160, 170, 200))

    recap_w = _text_width(_RECAP, recap_font)
    recap_y = tagline_y + 44 + 80
    draw.text(((_W - recap_w) // 2, recap_y), _RECAP, font=recap_font, fill=(200, 205, 220))

    subline_font = _font(32)
    subline_w = _text_width(_SUBLINE, subline_font)
    subline_y = recap_y + 36 + 24
    draw.text(((_W - subline_w) // 2, subline_y), _SUBLINE, font=subline_font, fill=(140, 200, 255))

    # Two-column links centered as a unit.
    link_y = cy + int(_H * 0.18)
    rendered: list[tuple[str, str, int, int]] = []  # (label, url, label_w, url_w)
    pair_pad = 96
    total_w = 0
    for label, url in _LINKS:
        lw = _text_width(label, label_font)
        uw = _text_width(url, url_font)
        rendered.append((label, url, lw, uw))
        total_w += max(lw, uw)
    total_w += pair_pad * (len(_LINKS) - 1)

    x = (_W - total_w) // 2
    for label, url, lw, uw in rendered:
        col_w = max(lw, uw)
        draw.text((x + (col_w - lw) // 2, link_y), label, font=label_font, fill=(120, 130, 155))
        draw.text((x + (col_w - uw) // 2, link_y + 28 + 16), url, font=url_font, fill=(140, 200, 255))
        x += col_w + pair_pad

    return img


def main() -> int:
    repo_root = Path(__file__).resolve().parents[3]
    out_path = repo_root / "docs" / "images" / "quickstart-outro.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img = render()
    img.save(out_path, "PNG")
    print(f"wrote {out_path} ({_W}x{_H})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
