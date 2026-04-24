"""Section title card — full-frame card shown ~1s at start of each section."""
from __future__ import annotations

from PIL import Image, ImageDraw

from scripts.screenshots.video.overlays.caption import _font, _text_width


def render(*, title: str, video_size: tuple[int, int]) -> Image.Image:
    """Simple centered title on a dark background — phase B1 look.

    Rendered as a full-size RGBA image so the compositor can drop it onto a
    solid-color ColorClip for the title-card duration.
    """
    w, h = video_size
    img = Image.new("RGBA", (w, h), (10, 12, 18, 255))
    draw = ImageDraw.Draw(img)

    big_size = max(64, h // 14)
    small_size = max(22, h // 44)

    big = _font(big_size)
    small = _font(small_size)

    title_w = _text_width(title, big)
    tx = (w - title_w) // 2
    ty = h // 2 - big_size
    draw.text((tx, ty), title, font=big, fill=(245, 245, 250, 255))

    subtitle = "Spindrel"
    sub_w = _text_width(subtitle, small)
    sx = (w - sub_w) // 2
    sy = ty + big_size + 16
    draw.text((sx, sy), subtitle, font=small, fill=(130, 135, 155, 255))

    return img
