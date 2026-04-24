"""Cluster 4C.3 — ratchet guard for raw hex color literals in UI code.

``feedback_tailwind_not_inline.md`` says new code uses Tailwind; inline
``style={{color: "#..."}}`` is legacy from the RN conversion. A big-bang
conversion isn't feasible (hundreds of call sites across the admin
surface), but a ratchet converts "slow migration" into "no regressions
+ gradual reduction" — every PR that touches a UI file is expected to
leave the hex count the same or lower.

The test counts raw hex patterns in ``ui/src/`` and ``ui/app/``
``.ts``/``.tsx`` files, excluding the canonical-source files that
*legitimately* hold hex tokens (the token palette itself, the widget
iframe theme generator, and its test). The count must not exceed
``_BASELINE``.

Skips cleanly when ``ui/`` is absent (Docker test image).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_UI_ROOT = _REPO_ROOT / "ui"


# Files that are legitimate sources of hex color values (the token
# palette itself, the iframe-preamble CSS generator, its tests).
# Paths are relative to ``ui/``. Everything else is ratcheted.
_EXCLUDE_FILES: frozenset[str] = frozenset({
    "src/theme/tokens.ts",
    "src/components/chat/renderers/widgetTheme.ts",
    "src/components/chat/renderers/widgetTheme.test.ts",
})


# Baseline at landing time (2026-04-24). Lower it when you remove hex
# literals; never raise it — new code should use Tailwind classes or
# the design-token CSS vars. If a raise is genuinely needed (e.g. a
# new file with legitimate hex palette), add the file to
# ``_EXCLUDE_FILES`` with a comment.
_BASELINE = 684


_HEX_RE = re.compile(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?")


def _count_hex_in_file(path: Path) -> int:
    try:
        return len(_HEX_RE.findall(path.read_text()))
    except (OSError, UnicodeDecodeError):
        return 0


def _iter_ui_ts_tsx() -> list[Path]:
    if not _UI_ROOT.is_dir():
        pytest.skip(f"ui/ not available at {_UI_ROOT}")
    out: list[Path] = []
    for sub in ("src", "app"):
        root = _UI_ROOT / sub
        if not root.is_dir():
            continue
        for ext in ("*.ts", "*.tsx"):
            for path in root.rglob(ext):
                # Skip dist/build outputs and node_modules defensively.
                if any(part in {"node_modules", "dist", ".chat-test-dist"}
                       for part in path.parts):
                    continue
                rel = path.relative_to(_UI_ROOT).as_posix()
                if rel in _EXCLUDE_FILES:
                    continue
                out.append(path)
    return out


def _total_hex_count() -> tuple[int, dict[str, int]]:
    per_file: dict[str, int] = {}
    total = 0
    for path in _iter_ui_ts_tsx():
        count = _count_hex_in_file(path)
        if count == 0:
            continue
        rel = path.relative_to(_UI_ROOT).as_posix()
        per_file[rel] = count
        total += count
    return total, per_file


def test_inline_hex_count_does_not_exceed_baseline() -> None:
    total, per_file = _total_hex_count()
    if total > _BASELINE:
        top = sorted(per_file.items(), key=lambda kv: -kv[1])[:10]
        rendered = "\n".join(f"  {count:4}  {rel}" for rel, count in top)
        raise AssertionError(
            f"Inline hex literal count {total} exceeds baseline {_BASELINE}. "
            "New code must use Tailwind classes or the design-token "
            "CSS variables — see docs/guides/ui-design.md and "
            "ui/src/theme/tokens.ts.\n\nTop offenders:\n" + rendered
            + "\n\nIf you genuinely need a new hex palette source, add "
            "the file to _EXCLUDE_FILES with a comment explaining why."
        )


def test_baseline_is_tight_against_actual_count() -> None:
    """Inverse pin — keep the ratchet honest. When someone removes
    hex literals, they should also lower ``_BASELINE`` so the guard
    doesn't turn into a permission slip. Tolerance: 10 hex values
    below baseline is fine (avoids churn); more than that wants a
    baseline update."""
    total, _ = _total_hex_count()
    tolerance = 10
    if total + tolerance < _BASELINE:
        raise AssertionError(
            f"Actual hex count ({total}) is more than {tolerance} "
            f"below the baseline ({_BASELINE}). Lower _BASELINE to "
            f"{total} to keep the ratchet tight."
        )
