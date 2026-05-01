"""Outbound URL guard — default-deny private / loopback / link-local.

Pins the new ``allow_loopback`` / ``allow_private`` opt-ins on the existing
``app/services/url_safety.py::assert_public_url`` helper. The helper is the
shared SSRF baseline used by webhook delivery, ``generate_image`` URL fetch,
and (since 2026-05) the MCP runtime path. These tests exercise classification
on literal IPs so we don't depend on real DNS.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.url_safety import (
    UnsafePublicURLError,
    assert_public_url,
    is_public_url,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://[::1]/",
    ],
)
async def test_loopback_blocked_by_default(url: str) -> None:
    with pytest.raises(UnsafePublicURLError, match="loopback"):
        await assert_public_url(url)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url, label",
    [
        ("http://10.0.0.5/", "private"),
        ("http://192.168.1.1/", "private"),
        ("http://172.16.0.1/", "private"),
        ("http://169.254.169.254/", "link-local"),
        ("http://100.64.0.1/", "cgnat"),
    ],
)
async def test_private_and_link_local_blocked(url: str, label: str) -> None:
    with pytest.raises(UnsafePublicURLError, match=label):
        await assert_public_url(url)


@pytest.mark.asyncio
async def test_public_url_allowed() -> None:
    # 1.1.1.1 (Cloudflare) is a literal IP Python's ipaddress treats as global.
    await assert_public_url("http://1.1.1.1/")


@pytest.mark.asyncio
async def test_loopback_opt_in() -> None:
    await assert_public_url("http://127.0.0.1/", allow_loopback=True)


@pytest.mark.asyncio
async def test_private_opt_in() -> None:
    await assert_public_url("http://10.0.0.5/", allow_private=True)


@pytest.mark.asyncio
async def test_loopback_opt_in_does_not_unlock_private() -> None:
    with pytest.raises(UnsafePublicURLError, match="private"):
        await assert_public_url("http://10.0.0.5/", allow_loopback=True)


@pytest.mark.asyncio
async def test_private_opt_in_does_not_unlock_loopback() -> None:
    with pytest.raises(UnsafePublicURLError, match="loopback"):
        await assert_public_url("http://127.0.0.1/", allow_private=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/",
        "gopher://example.com/",
        "javascript:alert(1)",
    ],
)
async def test_non_http_schemes_blocked(url: str) -> None:
    with pytest.raises(UnsafePublicURLError, match="Scheme"):
        await assert_public_url(url)


@pytest.mark.asyncio
async def test_empty_or_no_host() -> None:
    with pytest.raises(UnsafePublicURLError):
        await assert_public_url("http:///path-only")


@pytest.mark.asyncio
async def test_ipv4_mapped_ipv6_classified_via_unmap() -> None:
    # ::ffff:10.0.0.1 — should still be classified as private
    with pytest.raises(UnsafePublicURLError, match="private"):
        await assert_public_url("http://[::ffff:10.0.0.1]/")


@pytest.mark.asyncio
async def test_is_public_url_non_throwing() -> None:
    assert await is_public_url("http://1.1.1.1/") is True
    assert await is_public_url("http://127.0.0.1/") is False
    assert await is_public_url("http://127.0.0.1/", allow_loopback=True) is True
