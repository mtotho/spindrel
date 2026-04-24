"""Cross-layer drift guard for grid presets.

Backend owns `app/services/dashboards.py::GRID_PRESETS` (scales pin coords
server-side on preset change). Frontend owns
`ui/src/lib/dashboardGrid.ts::GRID_PRESETS` (the rich shape: breakpoint map,
tile chips, etc.). There is no API that exposes presets from backend to
frontend, so the two tables are definitionally duplicated.

This test pins the numeric fields that *must* match between the two sides:
`cols_lg` and `row_height` (the only fields the backend's `_scale_ratio`
relies on), plus the default preset id. It skips cleanly when the TS file
isn't available (Docker test image excludes `ui/`).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.dashboards import DEFAULT_PRESET, GRID_PRESETS as BACKEND_PRESETS


_REPO_ROOT = Path(__file__).resolve().parents[2]
_TS_FILE = _REPO_ROOT / "ui" / "src" / "lib" / "dashboardGrid.ts"


def _load_ts() -> str:
    if not _TS_FILE.is_file():
        pytest.skip(f"frontend source not available at {_TS_FILE}")
    return _TS_FILE.read_text()


def _extract_frontend_presets(src: str) -> dict[str, dict[str, int]]:
    """Return ``{preset_id: {cols_lg, row_height}}`` parsed from the TS source.

    The TS file declares each preset as a static object literal — regex over
    the declaration block is more brittle than a parser but cheap, and a
    failure here fails loud (which is the whole point of the drift guard).
    """
    block_match = re.search(
        r"export const GRID_PRESETS[^{]*=\s*\{(.*?)^\};",
        src,
        re.DOTALL | re.MULTILINE,
    )
    if not block_match:
        raise AssertionError("GRID_PRESETS literal not found in dashboardGrid.ts")
    body = block_match.group(1)

    entry_re = re.compile(
        r"(?P<id>\w+)\s*:\s*\{[^{}]*?"
        r"cols\s*:\s*\{[^}]*?\blg\s*:\s*(?P<cols_lg>\d+)[^}]*?\}[^{}]*?"
        r"rowHeight\s*:\s*(?P<row_height>\d+)",
        re.DOTALL,
    )
    entries: dict[str, dict[str, int]] = {}
    for m in entry_re.finditer(body):
        entries[m.group("id")] = {
            "cols_lg": int(m.group("cols_lg")),
            "row_height": int(m.group("row_height")),
        }
    if not entries:
        raise AssertionError(
            "no preset entries parsed from dashboardGrid.ts GRID_PRESETS block"
        )
    return entries


def _extract_frontend_default(src: str) -> str:
    m = re.search(
        r"export const DEFAULT_PRESET_ID[^=]*=\s*\"(?P<id>\w+)\"\s*;",
        src,
    )
    if not m:
        raise AssertionError(
            "DEFAULT_PRESET_ID export not found in dashboardGrid.ts"
        )
    return m.group("id")


def test_preset_ids_match_across_layers() -> None:
    src = _load_ts()
    frontend = _extract_frontend_presets(src)
    assert set(BACKEND_PRESETS) == set(frontend), (
        f"preset id drift: backend={sorted(BACKEND_PRESETS)} "
        f"frontend={sorted(frontend)}"
    )


def test_cols_lg_matches_across_layers() -> None:
    src = _load_ts()
    frontend = _extract_frontend_presets(src)
    for pid, backend_fields in BACKEND_PRESETS.items():
        assert frontend[pid]["cols_lg"] == backend_fields["cols_lg"], (
            f"preset {pid!r}: backend cols_lg={backend_fields['cols_lg']} "
            f"!= frontend cols.lg={frontend[pid]['cols_lg']}"
        )


def test_row_height_matches_across_layers() -> None:
    src = _load_ts()
    frontend = _extract_frontend_presets(src)
    for pid, backend_fields in BACKEND_PRESETS.items():
        assert frontend[pid]["row_height"] == backend_fields["row_height"], (
            f"preset {pid!r}: backend row_height={backend_fields['row_height']} "
            f"!= frontend rowHeight={frontend[pid]['row_height']}"
        )


def test_default_preset_matches_across_layers() -> None:
    src = _load_ts()
    frontend_default = _extract_frontend_default(src)
    assert DEFAULT_PRESET == frontend_default, (
        f"default preset drift: backend={DEFAULT_PRESET!r} "
        f"frontend={frontend_default!r}"
    )
