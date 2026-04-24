"""Watermark overlay — small text in the bottom-right corner."""
from __future__ import annotations

from PIL import Image, ImageDraw

from scripts.screenshots.video.overlays.caption import _font, _text_width
from scripts.screenshots.video.storyboard import Watermark


def render(*, wm: Watermark, video_size: tuple[int, int]) -> Image.Image:
    w, h = video_size
    font_size = max(16, h // 60)
    font = _font(font_size)
    text_w = _text_width(wm.text, font)
    pad = 24
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    x = w - text_w - pad
    y = h - font_size - pad
    alpha = int(255 * wm.opacity)
    draw.text((x, y), wm.text, font=font, fill=(240, 240, 245, alpha))
    return img
