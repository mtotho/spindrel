"""Phase Q-SEC-2 — SSRF horizontal coverage drift-pin.

Complements ``tests/unit/test_url_safety.py`` (which pins the guard itself)
and ``tests/unit/test_webhooks.py::test_validate_webhook_url_*`` (which pins
the weaker string-based webhook URL check).

This file pins:

QSSRF.1  The bot/user-URL sinks that DO call ``assert_public_url`` actually
         invoke it before any outbound HTTP — patching the guard to raise
         prevents the fetch entirely. Today: ``standing_orders._tick_poll_url``
         + ``tools/local/image._download_image_url``.

QSSRF.2  User/bot/admin supplied URL sinks call ``assert_public_url`` before
         fetching:
         - ``app/services/attachment_summarizer.py`` — fetches ``att.url``
         - ``app/routers/api_v1_admin/mcp_servers.py::_test_mcp_connection``
           — admin-only, but still guarded before outbound POST

QSSRF.3  ``validate_webhook_url`` delegates to the same DNS-resolving guard.
"""
from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.url_safety import UnsafePublicURLError


REPO_ROOT = Path(__file__).resolve().parents[2]


# ===========================================================================
# QSSRF.1 — Gated sites: assert_public_url is actually invoked
# ===========================================================================


class TestStandingOrdersInvokesSSRFGuard:
    """``_tick_poll_url`` calls ``assert_public_url`` before the httpx request.
    Patch the guard to raise; httpx must never be reached, TickResult.failed
    must be True with the guard error surfaced.
    """

    @pytest.mark.asyncio
    async def test_guard_raise_short_circuits_fetch(self, monkeypatch):
        from app.services import standing_orders as so_mod

        http_calls: list[str] = []

        async def _fake_assert(url: str) -> None:
            raise UnsafePublicURLError(f"pinned-block: {url}")

        class _FakeAsyncClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                http_calls.append("aenter")
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **kw):
                http_calls.append("get")
                raise AssertionError("httpx reached despite guard raise")

        # The import inside the function resolves to `app.services.url_safety`,
        # so patch that module attribute.
        monkeypatch.setattr(
            "app.services.url_safety.assert_public_url", _fake_assert
        )
        monkeypatch.setattr(so_mod.httpx, "AsyncClient", _FakeAsyncClient)

        result = await so_mod._tick_poll_url({"url": "http://public.example/"})
        assert result.failed is True
        assert "pinned-block" in (result.failure_reason or "")
        assert http_calls == [], (
            "SSRF guard did not short-circuit — httpx was invoked: "
            f"{http_calls}"
        )

    @pytest.mark.asyncio
    async def test_loopback_literal_rejected_end_to_end(self):
        """No mocks — real ``assert_public_url`` rejects ``http://127.0.0.1/``
        before any network call. Pins the end-to-end contract.
        """
        from app.services import standing_orders as so_mod

        result = await so_mod._tick_poll_url({"url": "http://127.0.0.1/admin"})
        assert result.failed is True
        assert "non-public" in (result.failure_reason or "").lower()

    @pytest.mark.asyncio
    async def test_missing_url_rejected_without_guard_call(self, monkeypatch):
        """Empty URL is rejected BEFORE the guard is called (cheaper fail)."""
        from app.services import standing_orders as so_mod

        guard_called: list[str] = []

        async def _fake_assert(url: str) -> None:
            guard_called.append(url)

        monkeypatch.setattr(
            "app.services.url_safety.assert_public_url", _fake_assert
        )

        result = await so_mod._tick_poll_url({"url": ""})
        assert result.failed is True
        assert "missing url" in (result.failure_reason or "").lower()
        assert guard_called == []


# ===========================================================================
# QSSRF.2 — Source-inspection pins for ungated sinks
# ===========================================================================


def _module_references_assert_public_url(relpath: str) -> bool:
    """Return True iff the module at ``relpath`` has any reference to
    ``assert_public_url`` (import or attribute access). AST-based so
    comments / strings don't falsely trigger.
    """
    src = (REPO_ROOT / relpath).read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        # `from app.services.url_safety import ..., assert_public_url, ...`
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "assert_public_url":
                    return True
        # Bare name reference: `assert_public_url(...)` or `mod.assert_public_url(...)`
        if isinstance(node, ast.Name) and node.id == "assert_public_url":
            return True
        if isinstance(node, ast.Attribute) and node.attr == "assert_public_url":
            return True
    return False


class TestHorizontalSinksGuarded:
    """Pin that user/bot/admin-supplied URL sinks use the shared guard."""

    def test_attachment_summarizer_has_ssrf_guard(self):
        assert _module_references_assert_public_url(
            "app/services/attachment_summarizer.py"
        )

    def test_mcp_test_connection_has_ssrf_guard(self):
        assert _module_references_assert_public_url(
            "app/routers/api_v1_admin/mcp_servers.py"
        )


# ===========================================================================
# QSSRF.3 — webhook URLs delegate to DNS-resolving guard
# ===========================================================================


class TestWebhookValidatorDelegatesToPublicUrlGuard:
    @pytest.mark.asyncio
    async def test_public_hostname_uses_dns_resolving_guard(self, monkeypatch):
        from app.services.webhooks import validate_webhook_url

        async def _blocked(url: str) -> None:
            assert url == "https://evil.example.com/hook"
            raise UnsafePublicURLError("Host resolves to non-public address: 127.0.0.1")

        monkeypatch.setattr("app.services.webhooks.assert_public_url", _blocked)
        with pytest.raises(ValueError, match="non-public"):
            await validate_webhook_url("https://evil.example.com/hook")

    @pytest.mark.asyncio
    async def test_decimal_encoded_loopback_is_rejected(self, monkeypatch):
        from app.services.webhooks import validate_webhook_url

        async def _blocked(url: str) -> None:
            assert url == "https://2130706433/hook"
            raise UnsafePublicURLError("Host resolves to non-public address: 127.0.0.1")

        monkeypatch.setattr("app.services.webhooks.assert_public_url", _blocked)
        with pytest.raises(ValueError, match="non-public"):
            await validate_webhook_url("https://2130706433/hook")

    @pytest.mark.asyncio
    async def test_ipv6_mapped_ipv4_loopback_is_rejected(self):
        from app.services.webhooks import validate_webhook_url

        with pytest.raises(ValueError, match="non-public"):
            await validate_webhook_url("https://[::ffff:7f00:1]/hook")

    @pytest.mark.asyncio
    async def test_assert_public_url_catches_what_validate_webhook_url_misses(self):
        """Baseline: the ``assert_public_url`` guard DOES catch loopback by
        literal — so a future webhook-validator upgrade has a working
        upstream to delegate to. Pins the handoff contract.
        """
        from app.services.url_safety import assert_public_url

        with pytest.raises(UnsafePublicURLError):
            await assert_public_url("https://[::ffff:7f00:1]/hook")
        with pytest.raises(UnsafePublicURLError):
            await assert_public_url("https://127.0.0.1/hook")
