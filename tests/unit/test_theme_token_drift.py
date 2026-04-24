"""Cluster 4C.1 — theme-token cross-layer drift guard.

The same ~35 semantic color tokens live in three files:
- ``ui/src/theme/tokens.ts`` — hex, consumed via ``useThemeTokens`` hook
  for inline ``style={{}}`` on raw HTML elements.
- ``app/services/widget_themes.py`` — hex, Python-side source for widget
  iframe CSS variables (channel-custom widget themes extend these).
- ``ui/global.css`` — RGB triplets, consumed by Tailwind via
  ``rgb(var(--color-accent) / <alpha>)`` (RGB format is mandatory for
  Tailwind's alpha-applying syntax).

There is no codegen pipeline; editing one file without the others
silently desyncs widgets from app chrome or dark-mode from light-mode.

This test pins two invariants:
1. For every token key that exists in BOTH ``tokens.ts`` and
   ``widget_themes.py``, the hex values must match (both light + dark).
2. For every ``--color-*`` CSS variable in ``global.css`` that has a
   corresponding key in ``tokens.ts``, the RGB triplet must equal the
   hex converted to RGB.

Skips cleanly when ``ui/`` is absent (Docker test image).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOKENS_TS = _REPO_ROOT / "ui" / "src" / "theme" / "tokens.ts"
_GLOBAL_CSS = _REPO_ROOT / "ui" / "global.css"


# ---------------------------------------------------------------------------
# TS parsing
# ---------------------------------------------------------------------------


def _load_tokens_ts() -> str:
    if not _TOKENS_TS.is_file():
        pytest.skip(f"frontend source not available at {_TOKENS_TS}")
    return _TOKENS_TS.read_text()


def _parse_tokens_block(src: str, block_name: str) -> dict[str, str]:
    """Parse a ``const DARK: ThemeTokens = { ... };`` block into a
    ``{camelKey: hex-or-rgba}`` dict. Values that aren't plain hex (e.g.
    ``rgba(59,130,246,0.08)``) pass through verbatim."""
    block_match = re.search(
        rf"const {block_name}[^=]*=\s*\{{(.*?)^\}};",
        src,
        re.DOTALL | re.MULTILINE,
    )
    if not block_match:
        raise AssertionError(f"{block_name} block not found in tokens.ts")
    body = block_match.group(1)
    entry_re = re.compile(
        r'(?P<key>[a-zA-Z][a-zA-Z0-9]*)\s*:\s*"(?P<value>[^"]+)"\s*,?'
    )
    return {m.group("key"): m.group("value") for m in entry_re.finditer(body)}


# ---------------------------------------------------------------------------
# Python parsing — live values, no regex.
# ---------------------------------------------------------------------------


def _py_tokens() -> tuple[dict[str, str], dict[str, str]]:
    from app.services.widget_themes import (
        BUILTIN_DARK_TOKENS,
        BUILTIN_LIGHT_TOKENS,
    )
    return dict(BUILTIN_LIGHT_TOKENS), dict(BUILTIN_DARK_TOKENS)


# ---------------------------------------------------------------------------
# global.css parsing
# ---------------------------------------------------------------------------


def _load_global_css() -> str:
    if not _GLOBAL_CSS.is_file():
        pytest.skip(f"frontend global.css not available at {_GLOBAL_CSS}")
    return _GLOBAL_CSS.read_text()


def _parse_css_color_block(src: str, selector: str) -> dict[str, tuple[int, int, int]]:
    """Parse ``:root`` or ``.dark`` color block into ``{color_name: (r,g,b)}``."""
    block_match = re.search(
        rf"{re.escape(selector)}\s*\{{(.*?)\}}",
        src,
        re.DOTALL,
    )
    if not block_match:
        raise AssertionError(f"{selector} block not found in global.css")
    body = block_match.group(1)
    entry_re = re.compile(
        r'--color-(?P<name>[a-z\-]+)\s*:\s*(?P<r>\d+)\s+(?P<g>\d+)\s+(?P<b>\d+)\s*;'
    )
    return {
        m.group("name"): (int(m.group("r")), int(m.group("g")), int(m.group("b")))
        for m in entry_re.finditer(body)
    }


# ---------------------------------------------------------------------------
# Key mapping — TS camelCase <-> CSS kebab-case <-> Python camelCase
# ---------------------------------------------------------------------------


def _camel_to_kebab(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()


def _hex_to_rgb(value: str) -> tuple[int, int, int] | None:
    """Return (r,g,b) for a hex string ``#rrggbb`` or ``#rgb``.
    Returns None for rgba() or other non-hex formats (we only pin
    opaque hex values against the RGB CSS variables)."""
    stripped = value.strip()
    if not stripped.startswith("#"):
        return None
    hexdigits = stripped[1:]
    if len(hexdigits) == 3:
        hexdigits = "".join(c * 2 for c in hexdigits)
    if len(hexdigits) != 6:
        return None
    try:
        return (
            int(hexdigits[0:2], 16),
            int(hexdigits[2:4], 16),
            int(hexdigits[4:6], 16),
        )
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Invariant 1 — tokens.ts agrees with widget_themes.py for shared keys
# ---------------------------------------------------------------------------


def test_ts_and_py_share_hex_values_for_common_light_keys() -> None:
    src = _load_tokens_ts()
    ts_light = _parse_tokens_block(src, "LIGHT")
    py_light, _ = _py_tokens()

    shared_keys = set(ts_light) & set(py_light)
    assert shared_keys, (
        "no shared keys between tokens.ts LIGHT and "
        "widget_themes.py BUILTIN_LIGHT_TOKENS — parser broke?"
    )

    mismatches = [
        (k, ts_light[k], py_light[k])
        for k in sorted(shared_keys)
        if ts_light[k] != py_light[k]
    ]
    if mismatches:
        rendered = "\n".join(f"  {k}: ts={t!r} py={p!r}" for k, t, p in mismatches)
        raise AssertionError(
            "LIGHT token drift between ui/src/theme/tokens.ts and "
            "app/services/widget_themes.py:\n" + rendered
            + "\n\nEdit BOTH files to keep them in sync."
        )


def test_ts_and_py_share_hex_values_for_common_dark_keys() -> None:
    src = _load_tokens_ts()
    ts_dark = _parse_tokens_block(src, "DARK")
    _, py_dark = _py_tokens()

    shared_keys = set(ts_dark) & set(py_dark)
    assert shared_keys, "no shared keys between DARK tables — parser broke?"

    mismatches = [
        (k, ts_dark[k], py_dark[k])
        for k in sorted(shared_keys)
        if ts_dark[k] != py_dark[k]
    ]
    if mismatches:
        rendered = "\n".join(f"  {k}: ts={t!r} py={p!r}" for k, t, p in mismatches)
        raise AssertionError(
            "DARK token drift between ui/src/theme/tokens.ts and "
            "app/services/widget_themes.py:\n" + rendered
            + "\n\nEdit BOTH files to keep them in sync."
        )


# ---------------------------------------------------------------------------
# Invariant 2 — global.css RGB triplets match tokens.ts hex for shared keys
# ---------------------------------------------------------------------------


# Known-drift allowlist for :root (light mode). Each entry captures
# an existing mismatch at test-landing time (Cluster 4C.1). Treat as a
# "fix this next" ratchet — removing an entry after aligning the two
# files is the win. Adding a new entry requires a justification comment.
#
# Root cause at landing: ``global.css :root`` was authored with
# Tailwind-default semantic colors (success=emerald-500,
# warning=yellow-500, danger=red-500, purple=purple-500) while
# ``tokens.ts LIGHT`` was authored with the designer-darker variants
# (emerald-600, yellow-600, red-600, violet-600). The app renders
# Tailwind-styled elements with :root colors and inline-styled
# elements with tokens.ts colors, so the two versions are visibly
# different. Fixing in either direction is a design call, not a
# refactor — hence the allowlist.
_LIGHT_KNOWN_DRIFT_KEYS: frozenset[str] = frozenset({
    "text-dim",       # tokens.ts #6b7280 vs global.css #a3a3a3
    "success",        # tokens.ts #16a34a vs global.css #22c55e
    "warning",        # tokens.ts #ca8a04 vs global.css #eab308
    "danger",         # tokens.ts #dc2626 vs global.css #ef4444
    "purple",         # tokens.ts #7c3aed vs global.css #a855f7
    "danger-muted",   # tokens.ts #ef4444 vs global.css #f87171
})


def test_global_css_light_rgb_matches_tokens_ts_hex() -> None:
    src = _load_tokens_ts()
    css = _load_global_css()
    ts_light = _parse_tokens_block(src, "LIGHT")
    css_light = _parse_css_color_block(css, ":root")

    mismatches: list[str] = []
    for css_key, rgb in css_light.items():
        if css_key in _LIGHT_KNOWN_DRIFT_KEYS:
            continue
        camel_key = css_key.replace("-", " ").title().replace(" ", "")
        camel_key = camel_key[0].lower() + camel_key[1:]
        if camel_key not in ts_light:
            continue
        hex_rgb = _hex_to_rgb(ts_light[camel_key])
        if hex_rgb is None:
            continue  # rgba() entries — not pinned here
        if hex_rgb != rgb:
            mismatches.append(
                f"  --color-{css_key}: css={rgb} ts={ts_light[camel_key]} "
                f"(converts to {hex_rgb})"
            )
    if mismatches:
        raise AssertionError(
            ":root (light) RGB triplets in global.css drift from "
            "tokens.ts LIGHT hex values:\n" + "\n".join(mismatches)
            + "\n\nEdit BOTH ui/global.css and ui/src/theme/tokens.ts, "
            "OR (if the drift is deliberate) add the key to "
            "_LIGHT_KNOWN_DRIFT_KEYS with a justification comment."
        )


def test_known_light_drift_is_still_present() -> None:
    """Inverse pin: when a key in ``_LIGHT_KNOWN_DRIFT_KEYS`` gets
    fixed (both files agree), it must be removed from the allowlist.
    Stale allowlist entries defeat the drift guard."""
    src = _load_tokens_ts()
    css = _load_global_css()
    ts_light = _parse_tokens_block(src, "LIGHT")
    css_light = _parse_css_color_block(css, ":root")

    stale: list[str] = []
    for css_key in _LIGHT_KNOWN_DRIFT_KEYS:
        rgb = css_light.get(css_key)
        if rgb is None:
            stale.append(f"  {css_key}: no longer present in global.css")
            continue
        camel_key = css_key.replace("-", " ").title().replace(" ", "")
        camel_key = camel_key[0].lower() + camel_key[1:]
        if camel_key not in ts_light:
            stale.append(f"  {css_key}: no longer present in tokens.ts LIGHT")
            continue
        hex_rgb = _hex_to_rgb(ts_light[camel_key])
        if hex_rgb is None:
            continue
        if hex_rgb == rgb:
            stale.append(
                f"  {css_key}: drift is fixed (both files agree on {rgb}); "
                "remove from _LIGHT_KNOWN_DRIFT_KEYS"
            )
    if stale:
        raise AssertionError(
            "Stale _LIGHT_KNOWN_DRIFT_KEYS entries:\n" + "\n".join(stale)
        )


def test_global_css_dark_rgb_matches_tokens_ts_hex() -> None:
    src = _load_tokens_ts()
    css = _load_global_css()
    ts_dark = _parse_tokens_block(src, "DARK")
    css_dark = _parse_css_color_block(css, ".dark")

    mismatches: list[str] = []
    for css_key, rgb in css_dark.items():
        camel_key = css_key.replace("-", " ").title().replace(" ", "")
        camel_key = camel_key[0].lower() + camel_key[1:]
        if camel_key not in ts_dark:
            continue
        hex_rgb = _hex_to_rgb(ts_dark[camel_key])
        if hex_rgb is None:
            continue
        if hex_rgb != rgb:
            mismatches.append(
                f"  --color-{css_key}: css={rgb} ts={ts_dark[camel_key]} "
                f"(converts to {hex_rgb})"
            )
    if mismatches:
        raise AssertionError(
            ".dark RGB triplets in global.css drift from "
            "tokens.ts DARK hex values:\n" + "\n".join(mismatches)
        )
