"""Tests for :mod:`app.services.url_safety`.

Pin the SSRF guard against loopback / link-local / private / reserved
addresses and bad schemes. DNS resolution is mocked so the suite stays
offline.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.url_safety import (
    UnsafePublicURLError,
    assert_public_url,
    is_public_url,
)


def _mock_resolve(addrs: list[str]):
    """Return an async function suitable for monkeypatching
    ``app.services.url_safety._resolve``."""

    async def fake(_host):
        return list(addrs)

    return fake


def _mock_resolve_raises(exc: Exception):
    async def fake(_host):
        raise exc

    return fake


async def _assert_raises(url: str, match: str | None = None):
    with pytest.raises(UnsafePublicURLError) as info:
        await assert_public_url(url)
    if match:
        assert match.lower() in str(info.value).lower()


@pytest.mark.asyncio
async def test_public_url_passes():
    with patch("app.services.url_safety._resolve", _mock_resolve(["1.1.1.1"])):
        await assert_public_url("https://example.com/image.png")


@pytest.mark.asyncio
async def test_literal_public_ip_passes():
    # No DNS needed for IP literals.
    await assert_public_url("https://1.1.1.1/")


@pytest.mark.asyncio
async def test_loopback_literal_blocked():
    await _assert_raises("http://127.0.0.1/admin", match="non-public")


@pytest.mark.asyncio
async def test_loopback_name_blocked():
    with patch("app.services.url_safety._resolve", _mock_resolve(["127.0.0.1"])):
        await _assert_raises("http://localhost/", match="non-public")


@pytest.mark.asyncio
async def test_aws_metadata_blocked():
    await _assert_raises("http://169.254.169.254/latest/meta-data/", match="non-public")


@pytest.mark.asyncio
async def test_rfc1918_blocked():
    for ip in ("10.0.0.1", "172.16.5.4", "192.168.1.1"):
        await _assert_raises(f"http://{ip}/", match="non-public")


@pytest.mark.asyncio
async def test_dns_rebinding_public_then_private_blocked():
    """If ANY resolved IP is private, the URL is rejected —
    defends against DNS rebinding that returns mixed results."""
    with patch(
        "app.services.url_safety._resolve",
        _mock_resolve(["1.1.1.1", "10.0.0.5"]),
    ):
        await _assert_raises("https://evil.example/", match="non-public")


@pytest.mark.asyncio
async def test_ipv6_loopback_blocked():
    await _assert_raises("http://[::1]/", match="non-public")


@pytest.mark.asyncio
async def test_ipv6_link_local_blocked():
    await _assert_raises("http://[fe80::1]/", match="non-public")


@pytest.mark.asyncio
async def test_multicast_blocked():
    await _assert_raises("http://224.0.0.1/", match="non-public")


@pytest.mark.asyncio
async def test_scheme_ftp_blocked():
    await _assert_raises("ftp://example.com/x", match="scheme")


@pytest.mark.asyncio
async def test_scheme_file_blocked():
    await _assert_raises("file:///etc/passwd", match="scheme")


@pytest.mark.asyncio
async def test_scheme_javascript_blocked():
    await _assert_raises("javascript:alert(1)", match="scheme")


@pytest.mark.asyncio
async def test_missing_host_blocked():
    await _assert_raises("http:///", match="host")


@pytest.mark.asyncio
async def test_unresolvable_host_blocked():
    with patch(
        "app.services.url_safety._resolve",
        _mock_resolve_raises(OSError("nodename nor servname provided")),
    ):
        await _assert_raises("https://nonexistent.invalid/", match="resolve")


@pytest.mark.asyncio
async def test_empty_dns_result_blocked():
    with patch("app.services.url_safety._resolve", _mock_resolve([])):
        await _assert_raises("https://void.example/", match="did not resolve")


@pytest.mark.asyncio
async def test_is_public_url_true_for_public():
    with patch("app.services.url_safety._resolve", _mock_resolve(["1.1.1.1"])):
        assert await is_public_url("https://example.com/") is True


@pytest.mark.asyncio
async def test_is_public_url_false_for_loopback():
    assert await is_public_url("http://127.0.0.1/") is False
