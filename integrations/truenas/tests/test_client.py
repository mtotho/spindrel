from __future__ import annotations

import pytest

from integrations.truenas.client import TrueNASConfigurationError, normalize_truenas_ws_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("truenas.local", "wss://truenas.local/api/current"),
        ("https://truenas.local", "wss://truenas.local/api/current"),
        ("http://truenas.local", "ws://truenas.local/api/current"),
        ("wss://nas.example/api/current", "wss://nas.example/api/current"),
        ("https://nas.example/api", "wss://nas.example/api/current"),
        ("https://nas.example/ui", "wss://nas.example/ui/api/current"),
        ("https://nas.example/api/v25.04", "wss://nas.example/api/v25.04"),
    ],
)
def test_normalize_truenas_ws_url(raw: str, expected: str) -> None:
    assert normalize_truenas_ws_url(raw) == expected


def test_normalize_truenas_ws_url_rejects_missing_url() -> None:
    with pytest.raises(TrueNASConfigurationError):
        normalize_truenas_ws_url("")

