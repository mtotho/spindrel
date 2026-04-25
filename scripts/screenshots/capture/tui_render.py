"""Synthetic terminal-frame renderer for the setup.sh wizard captures.

Renders Frame objects (lists of styled lines) onto a 1920x1080 dark canvas
that reads as a terminal. Used for setup walkthrough heroes where we need
deterministic frames that don't depend on actually running setup.sh.

Frames are constructed in tui_frames.py — that module imports the live
PROVIDERS list from scripts/setup.py so model menus stay current as the
wizard evolves.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[3]
_FONT_DIR = REPO_ROOT / "scripts" / "screenshots" / "assets"
FONT_REGULAR = _FONT_DIR / "JetBrainsMonoNerdFont-Regular.ttf"
FONT_BOLD = _FONT_DIR / "JetBrainsMonoNerdFont-Bold.ttf"


PALETTE = {
    "fg":          (205, 214, 244),
    "fg_dim":      (108, 112, 134),
    "fg_bold":     (255, 255, 255),
    "red":         (243, 139, 168),
    "green":       (166, 227, 161),
    "yellow":      (249, 226, 175),
    "blue":        (137, 180, 250),
    "cyan":        (148, 226, 213),
    "magenta":     (203, 166, 247),
    "prompt":      (245, 194, 231),
    "bg":          (17, 17, 27),
    "title_bar":   (30, 30, 46),
    "highlight":   (49, 50, 68),
    "dot_red":     (255, 95, 87),
    "dot_yellow":  (255, 189, 46),
    "dot_green":   (39, 201, 63),
}


@dataclass
class Span:
    text: str
    color: str = "fg"
    bold: bool = False


@dataclass
class Line:
    spans: list[Span] = field(default_factory=list)
    highlight: bool = False

    @classmethod
    def blank(cls) -> "Line":
        return cls([])

    @classmethod
    def of(cls, text: str, color: str = "fg", bold: bool = False, *, highlight: bool = False) -> "Line":
        return cls([Span(text, color=color, bold=bold)], highlight=highlight)

    def then(self, text: str, color: str = "fg", bold: bool = False) -> "Line":
        self.spans.append(Span(text, color=color, bold=bold))
        return self


@dataclass
class Frame:
    lines: list[Line]
    title: str = "spindrel — setup"


def render(
    frame: Frame,
    output_path: Path,
    *,
    width: int = 1920,
    height: int = 1080,
    font_size: int = 22,
    line_spacing: int = 10,
) -> Path:
    img = Image.new("RGB", (width, height), PALETTE["bg"])
    draw = ImageDraw.Draw(img)

    font = ImageFont.truetype(str(FONT_REGULAR), font_size)
    font_bold = ImageFont.truetype(str(FONT_BOLD), font_size)

    asc, desc = font.getmetrics()
    cell_h = asc + desc + line_spacing

    title_h = 56
    draw.rectangle([(0, 0), (width, title_h)], fill=PALETTE["title_bar"])
    for i, c in enumerate(["dot_red", "dot_yellow", "dot_green"]):
        cx = 28 + i * 26
        cy = title_h // 2
        draw.ellipse([(cx - 8, cy - 8), (cx + 8, cy + 8)], fill=PALETTE[c])
    title_font = ImageFont.truetype(str(FONT_BOLD), 18)
    draw.text(
        (130, title_h // 2 - 11),
        frame.title,
        fill=PALETTE["fg_dim"],
        font=title_font,
    )

    pad_x = 80
    y = title_h + 40

    for line in frame.lines:
        if line.highlight:
            draw.rectangle(
                [(pad_x - 16, y - 4), (width - 60, y + cell_h - 4)],
                fill=PALETTE["highlight"],
            )
        x = pad_x
        for span in line.spans:
            f = font_bold if span.bold else font
            color = PALETTE.get(span.color, PALETTE["fg"])
            draw.text((x, y), span.text, fill=color, font=f)
            x += int(f.getlength(span.text))
        y += cell_h

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)
    return output_path
