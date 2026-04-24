"""Drift test — canonical integration guide ↔ `_KNOWN_KEYS`.

Every top-level key parsed from `integration.yaml` by
`app/services/integration_manifests.py::_KNOWN_KEYS` must have a row in
the surface map of `docs/guides/integrations.md`, and the surface map
must not advertise keys that no longer exist in `_KNOWN_KEYS`.

Editing one side without the other is what made the old `chat_hud`
surface outlive its code by three sessions. This test closes that loop.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.services.integration_manifests import _KNOWN_KEYS

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = REPO_ROOT / "docs" / "guides" / "integrations.md"

# Matches a surface-map row: ``| `<key>` | …``. Keys are lowercase/underscore/digit.
_ROW_RE = re.compile(r"^\|\s*`([a-z_][a-z0-9_]*)`\s*\|", re.MULTILINE)


def _surface_map_section() -> str:
    """Return the raw markdown between ``## Surface map`` and the next ``## `` heading."""
    text = DOC_PATH.read_text()
    match = re.search(
        r"^## Surface map\s*$(.*?)^## ",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match, "canonical integration guide is missing the `## Surface map` section"
    return match.group(1)


def _documented_keys() -> set[str]:
    return set(_ROW_RE.findall(_surface_map_section()))


def test_every_known_key_is_documented() -> None:
    """Adding a key to ``_KNOWN_KEYS`` without updating the surface map fails here."""
    missing = _KNOWN_KEYS - _documented_keys()
    assert not missing, (
        "_KNOWN_KEYS entries missing from surface map in "
        f"docs/guides/integrations.md: {sorted(missing)}"
    )


def test_no_stale_keys_in_doc() -> None:
    """Removing a key from ``_KNOWN_KEYS`` without updating the surface map fails here."""
    stale = _documented_keys() - _KNOWN_KEYS
    assert not stale, (
        "Surface map rows reference keys not in _KNOWN_KEYS: "
        f"{sorted(stale)}. Either restore the key or delete the row."
    )
