"""Playwright-driven page capture for B2 doc-view scenes.

Two capture modes:

- ``capture_full_page`` — full-page PNG of a guide URL (long, page-height).
  Used by ``doc_hero`` for vertical scroll-pan effects.
- ``capture_callout`` — viewport-clipped PNG centered on a highlight selector,
  with an injected box-shadow ring so the callout reads on screen. Used by
  ``doc_callout``.

mkdocs-material's color scheme is controlled by the ``data-md-color-scheme``
attribute on ``<body>``, persisted via the ``__palette`` cookie. We set it
on every page load via ``add_init_script`` rather than relying on cookie
priming so the very first paint is correct.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from playwright.sync_api import sync_playwright


logger = logging.getLogger("screenshots.video.doc_capture")


# Module-level state populated by compose.py before any clip builds. Clips
# don't take a context object — keeping this implicit avoids threading
# state through MoviePy's per-frame callbacks.
_BASE_URL: str | None = None
_CACHE_DIR: Path | None = None


def configure(*, base_url: str, cache_dir: Path) -> None:
    global _BASE_URL, _CACHE_DIR
    _BASE_URL = base_url
    _CACHE_DIR = cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)


def _require_configured() -> tuple[str, Path]:
    if _BASE_URL is None or _CACHE_DIR is None:
        raise RuntimeError(
            "doc-view capture not configured — compose.py should call "
            "_doc_capture.configure(...) before rendering doc_* scenes"
        )
    return _BASE_URL, _CACHE_DIR


def guide_url(base_url: str, guide: str, anchor: str | None = None) -> str:
    """Resolve a markdown guide path to its mkdocs URL.

    ``guides/widget-system.md`` → ``<base>/guides/widget-system/[#<anchor>]``.
    """
    g = guide.strip()
    if g.endswith(".md"):
        g = g[:-3]
    if g.endswith("/index"):
        g = g[: -len("/index")]
    elif g == "index":
        g = ""
    path = f"/{g}/" if g else "/"
    url = base_url.rstrip("/") + path
    if anchor:
        url += f"#{anchor.lstrip('#')}"
    return url


def _palette_init_script(scheme: Literal["light", "dark"]) -> str:
    # mkdocs-material default palette uses scheme="default" for light and
    # scheme="slate" for dark. The site config above puts slate first, so
    # an unprimed cookie shows dark — we still set it explicitly so author
    # intent is unambiguous.
    md_scheme = "slate" if scheme == "dark" else "default"
    return f"""
try {{
  document.documentElement.setAttribute('data-md-color-scheme', {md_scheme!r});
  document.body && document.body.setAttribute('data-md-color-scheme', {md_scheme!r});
  localStorage.setItem('data-md-color-scheme', {md_scheme!r});
}} catch (e) {{}}
"""


@dataclass
class CalloutBox:
    """Highlight bounding box in fitted-image coordinate space.

    All values are in the same coords as the captured PNG (viewport-sized,
    DPR-aware). Used by doc_callout to drive the Ken Burns center.
    """
    x: float
    y: float
    width: float
    height: float
    image_width: int
    image_height: int

    @property
    def cx_norm(self) -> float:
        return (self.x + self.width / 2) / max(self.image_width, 1)

    @property
    def cy_norm(self) -> float:
        return (self.y + self.height / 2) / max(self.image_height, 1)


def capture_full_page(
    *,
    guide: str,
    anchor: str | None,
    scheme: Literal["light", "dark"],
    viewport_width: int,
    cache_key: str,
) -> Path:
    """Capture a full-page PNG of a mkdocs guide. Returns the file path."""
    base_url, cache_dir = _require_configured()
    out = cache_dir / f"{cache_key}.png"

    url = guide_url(base_url, guide, anchor)
    logger.info("doc capture (full page): %s → %s", url, out)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            # DPR=1 keeps the captured PNG manageable for very long guides.
            # Output video is 1080p, so 2x source supersamples needlessly and
            # tips PIL's decompression-bomb guard on 40k-tall pages.
            context = browser.new_context(
                viewport={"width": viewport_width, "height": 900},
                device_scale_factor=1,
            )
            context.add_init_script(_palette_init_script(scheme))
            page = context.new_page()
            page.goto(url, wait_until="networkidle", timeout=20_000)
            # Hide mkdocs-material's "back to top" button so it doesn't ride
            # the screenshot at every scroll position. Hide announce/header
            # tabs only if they overlap content unexpectedly — leave default.
            page.add_style_tag(content="""
                .md-top { display: none !important; }
                /* Disable smooth scroll for predictable capture */
                html { scroll-behavior: auto !important; }
            """)
            page.screenshot(path=str(out), full_page=True, type="png")
            context.close()
        finally:
            browser.close()

    return out


def capture_callout(
    *,
    guide: str,
    anchor: str | None,
    highlight: str,
    scheme: Literal["light", "dark"],
    viewport: tuple[int, int],
    cache_key: str,
) -> tuple[Path, CalloutBox]:
    """Capture a viewport-clipped PNG centered on `highlight`.

    Returns (png_path, CalloutBox) where the box is in image coords. The
    image dimensions match ``viewport`` (no DPR scaling — Playwright's
    device_scale_factor=1 here so bbox math stays direct).
    """
    base_url, cache_dir = _require_configured()
    out = cache_dir / f"{cache_key}.png"

    url = guide_url(base_url, guide, anchor)
    logger.info("doc capture (callout): %s [%s] → %s", url, highlight, out)

    vw, vh = viewport
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                viewport={"width": vw, "height": vh},
                device_scale_factor=1,
            )
            context.add_init_script(_palette_init_script(scheme))
            page = context.new_page()
            page.goto(url, wait_until="networkidle", timeout=20_000)

            page.add_style_tag(content="""
                .md-top { display: none !important; }
                html { scroll-behavior: auto !important; }
            """)

            # Scroll the highlight element to viewport center, then add a
            # high-contrast box-shadow ring so the callout reads visually.
            page.wait_for_selector(highlight, timeout=10_000)
            page.evaluate(
                """(sel) => {
                    const el = document.querySelector(sel);
                    if (!el) return;
                    const r = el.getBoundingClientRect();
                    // center vertically
                    const desiredTop = window.innerHeight / 2 - r.height / 2;
                    window.scrollBy(0, r.top - desiredTop);
                }""",
                highlight,
            )
            page.evaluate(
                """(sel) => {
                    const el = document.querySelector(sel);
                    if (!el) return;
                    el.style.transition = 'none';
                    el.style.boxShadow =
                        '0 0 0 4px rgba(99, 102, 241, 0.95),' +
                        ' 0 0 0 12px rgba(99, 102, 241, 0.25),' +
                        ' 0 16px 64px rgba(0, 0, 0, 0.55)';
                    el.style.borderRadius = el.style.borderRadius || '6px';
                    el.style.position = el.style.position || 'relative';
                    el.style.zIndex = '5';
                }""",
                highlight,
            )

            # Resolve bbox AFTER the scroll+style settle so coords reflect
            # the captured frame.
            box = page.evaluate(
                """(sel) => {
                    const el = document.querySelector(sel);
                    if (!el) return null;
                    const r = el.getBoundingClientRect();
                    return {x: r.x, y: r.y, width: r.width, height: r.height};
                }""",
                highlight,
            )
            if not box:
                raise RuntimeError(
                    f"highlight selector matched no element: {highlight!r}"
                )

            page.screenshot(path=str(out), full_page=False, type="png")
            context.close()
        finally:
            browser.close()

    callout = CalloutBox(
        x=float(box["x"]),
        y=float(box["y"]),
        width=float(box["width"]),
        height=float(box["height"]),
        image_width=vw,
        image_height=vh,
    )
    return out, callout
