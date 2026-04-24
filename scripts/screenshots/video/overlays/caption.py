"""Caption overlay — PIL-based (no ImageMagick dependency).

Produces an RGBA PIL.Image sized to the video width that can be wrapped in
a MoviePy ImageClip and positioned over a base clip. The caption is drawn
on a rounded, semi-transparent dark rectangle centered in a band that
spans the full video width.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from scripts.screenshots.video.storyboard import CaptionStyle


_CANDIDATE_FONT_PATHS = (
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/noto/NotoSans-Bold.ttf",
)


@lru_cache(maxsize=32)
def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for p in _CANDIDATE_FONT_PATHS:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    # Fallback — bitmap default is tiny but won't crash
    return ImageFont.load_default()


def render(*, text: str, video_width: int, style: CaptionStyle) -> Image.Image:
    """Render caption text to an RGBA image the full video width tall enough
    to contain the wrapped, padded text on its background rectangle.
    """
    side_pad = style.padding
    inner_pad = max(16, style.padding // 2)
    max_text_w = video_width - 2 * side_pad - 2 * inner_pad

    font = _font(style.font_size)
    lines = _wrap(text, font, max_text_w)

    # Measure
    line_h = _line_height(font)
    gap = max(4, style.font_size // 6)
    text_h = len(lines) * line_h + (len(lines) - 1) * gap
    text_w = max((_text_width(line, font) for line in lines), default=0)

    box_w = min(video_width - 2 * side_pad, text_w + 2 * inner_pad)
    box_h = text_h + 2 * inner_pad

    img_h = box_h + 2 * side_pad // 4  # small visual breathing room in the layer
    img = Image.new("RGBA", (video_width, img_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Centered rounded rectangle background
    box_x = (video_width - box_w) // 2
    box_y = (img_h - box_h) // 2
    bg_alpha = int(255 * style.bg_opacity)
    _rounded_rect(
        draw,
        (box_x, box_y, box_x + box_w, box_y + box_h),
        radius=min(24, box_h // 3),
        fill=(16, 16, 20, bg_alpha),
    )

    # Text, centered line by line
    y = box_y + inner_pad
    for line in lines:
        w = _text_width(line, font)
        x = (video_width - w) // 2
        draw.text((x, y), line, font=font, fill=(240, 240, 245, 255))
        y += line_h + gap

    return img


def _wrap(text: str, font, max_width: int) -> list[str]:
    # Simple greedy word wrap. Good enough for captions.
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for w in words[1:]:
        candidate = f"{current} {w}"
        if _text_width(candidate, font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = w
    lines.append(current)
    return lines


def _text_width(s: str, font) -> int:
    if hasattr(font, "getlength"):
        try:
            return int(font.getlength(s))
        except Exception:  # noqa: BLE001
            pass
    # Fallback for bitmap default font
    bbox = font.getbbox(s) if hasattr(font, "getbbox") else (0, 0, len(s) * 6, 10)
    return int(bbox[2] - bbox[0])


def _line_height(font) -> int:
    if hasattr(font, "getmetrics"):
        ascent, descent = font.getmetrics()
        return int(ascent + descent)
    return 14


def _rounded_rect(draw: ImageDraw.ImageDraw, xy, radius: int, fill) -> None:
    # Pillow 9+ has rounded_rectangle; fall back if needed.
    if hasattr(draw, "rounded_rectangle"):
        draw.rounded_rectangle(xy, radius=radius, fill=fill)
    else:
        draw.rectangle(xy, fill=fill)
