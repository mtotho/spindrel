from __future__ import annotations

from typing import Any

import httpx
import pytest

from integrations.unifi.client import (
    UniFiClient,
    UniFiClientConfig,
    UniFiConfigurationError,
    redact_unifi_payload,
    normalize_unifi_base_url,
    unifi_api_path_candidates,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("192.168.1.1", "https://192.168.1.1"),
        ("https://192.168.1.1", "https://192.168.1.1"),
        ("https://unifi.local/proxy/network", "https://unifi.local/proxy/network"),
    ],
)
def test_normalize_unifi_base_url(raw: str, expected: str) -> None:
    assert normalize_unifi_base_url(raw) == expected


def test_normalize_unifi_base_url_rejects_missing_url() -> None:
    with pytest.raises(UniFiConfigurationError):
        normalize_unifi_base_url("")


def test_unifi_api_path_candidates_include_local_fallbacks() -> None:
    assert unifi_api_path_candidates("/custom/v1") == [
        "/custom/v1",
        "/proxy/network/integration/v1",
        "/integration/v1",
        "/v1",
    ]


def test_redact_unifi_payload_redacts_nested_sensitive_fields() -> None:
    payload = {
        "name": "IoT",
        "wifiPassword": "secret",
        "nested": [{"api_key": "abc"}, {"tokenValue": "def"}, {"ok": True}],
    }

    assert redact_unifi_payload(payload) == {
        "name": "IoT",
        "wifiPassword": "[redacted]",
        "nested": [{"api_key": "[redacted]"}, {"tokenValue": "[redacted]"}, {"ok": True}],
    }


@pytest.mark.asyncio
async def test_client_uses_x_api_key_and_falls_back_base_path() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/bad/v1/sites":
            return httpx.Response(404, json={"error": "missing"})
        if request.url.path == "/proxy/network/integration/v1/sites":
            return httpx.Response(200, json=[{"id": "default", "name": "Default"}])
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(handler)
    client = UniFiClient(UniFiClientConfig(
        base_url="https://unifi.local",
        api_key="secret",
        api_base_path="/bad/v1",
    ))
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        base_url=client.base_url,
        headers={"X-API-KEY": client.config.api_key},
        transport=transport,
    )

    async with client as connected:
        assert connected.api_base_path == "/proxy/network/integration/v1"

    assert [request.url.path for request in requests] == [
        "/bad/v1/sites",
        "/proxy/network/integration/v1/sites",
    ]
    assert requests[0].headers["X-API-KEY"] == "secret"
    assert client.connection_attempts[-1]["status"] == "connected"


@pytest.mark.asyncio
async def test_list_paginated_reads_data_envelopes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset", "0"))
        page = [{"id": offset}, {"id": offset + 1}] if offset < 4 else []
        return httpx.Response(200, json={"data": page, "totalCount": 4})

    client = UniFiClient(UniFiClientConfig(
        base_url="https://unifi.local",
        api_key="secret",
    ))
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        base_url=client.base_url,
        headers={"X-API-KEY": client.config.api_key},
        transport=httpx.MockTransport(handler),
    )

    try:
        result = await client.list_paginated("/sites/default/clients", limit=2, max_items=4)
    finally:
        await client.close()

    assert result == [{"id": 0}, {"id": 1}, {"id": 2}, {"id": 3}]
