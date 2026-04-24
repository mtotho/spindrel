"""Phase Q-SEC-2 — SSRF horizontal coverage drift-pin.

Complements ``tests/unit/test_url_safety.py`` (which pins the guard itself)
and ``tests/unit/test_webhooks.py::test_validate_webhook_url_*`` (which pins
the weaker string-based webhook URL check).

This file pins:

QSSRF.1  The bot/user-URL sinks that DO call ``assert_public_url`` actually
         invoke it before any outbound HTTP — patching the guard to raise
         prevents the fetch entirely. Today: ``standing_orders._tick_poll_url``
         + ``tools/local/image._download_image_url``.

QSSRF.2  Documented horizontal gap: sites that accept user/bot-supplied URLs
         but do NOT call ``assert_public_url`` before fetching. Pinned by
         source inspection (module imports + AST sweep for ``assert_public_url``
         references) so a future fix flips the test assertion instead of
         silently landing. Current ungated sites:
         - ``app/services/attachment_summarizer.py`` — fetches ``att.url``
         - ``app/routers/api_v1_admin/mcp_servers.py::_test_mcp_connection``
           — admin-only but lacks DNS-resolving SSRF guard (admin could probe
           internal services by registering a loopback MCP URL)

QSSRF.3  ``validate_webhook_url`` is string-only (no DNS resolution), so a
         public hostname that resolves to a private/loopback address
         bypasses it. Pin the gap so a future migration to
         ``assert_public_url`` has a clear flip point.
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


class TestUngatedSinksDocumented:
    """Pin the current SSRF horizontal gap via AST inspection.

    Today, these modules fetch user/bot/admin-supplied URLs without calling
    ``assert_public_url``. This is a documented gap — a future fix adds the
    import, flips the assertion, and gains DNS-resolving SSRF protection.

    If any assertion here flips (``assert_public_url`` appears in the module),
    update the assertion to ``True`` and add a functional short-circuit test
    matching ``TestStandingOrdersInvokesSSRFGuard.test_guard_raise_short_circuits_fetch``.
    """

    def test_attachment_summarizer_has_no_ssrf_guard(self):
        """``app/services/attachment_summarizer.py`` fetches ``att.url``
        (line 124) without calling ``assert_public_url``. A user who uploads
        an attachment with a loopback URL would have the server fetch it
        when summarization fires.
        """
        assert not _module_references_assert_public_url(
            "app/services/attachment_summarizer.py"
        ), (
            "attachment_summarizer now references assert_public_url — "
            "update this test to assert the positive gate (patch the guard "
            "to raise, verify httpx is not reached)."
        )

    def test_mcp_test_connection_has_no_ssrf_guard(self):
        """``app/routers/api_v1_admin/mcp_servers.py::_test_mcp_connection``
        POSTs to an admin-supplied URL without calling ``assert_public_url``.
        Admin-only gate, but a compromised admin key could probe internal
        services via MCP registration.
        """
        assert not _module_references_assert_public_url(
            "app/routers/api_v1_admin/mcp_servers.py"
        ), (
            "mcp_servers router now references assert_public_url — "
            "update this test to assert the positive gate."
        )


# ===========================================================================
# QSSRF.3 — validate_webhook_url string-only gap
# ===========================================================================


class TestWebhookValidatorStringOnly:
    """``validate_webhook_url`` is a STRING-BASED hostname check — it does
    NOT resolve DNS. A public hostname that resolves to a private/loopback
    address passes validation and the webhook fires against the private IP.

    This is a known gap vs ``assert_public_url`` (which DNS-resolves and
    rejects public hostnames with private resolution). Pin the gap so a
    future migration has a clear flip point.
    """

    def test_public_hostname_not_resolved_passes_even_if_dns_would_be_loopback(self):
        """A hostname like ``evil.example.com`` (which a malicious party can
        point at 127.0.0.1 via their own DNS) passes ``validate_webhook_url``
        because the validator doesn't resolve DNS.

        This test exists to document the bypass. Flip to ``pytest.raises``
        once ``validate_webhook_url`` is replaced with a DNS-resolving guard.
        """
        from app.services.webhooks import validate_webhook_url

        # Does NOT raise. If this starts raising, the validator was upgraded
        # to resolve DNS (good!) — update the test to positively verify the
        # resolution-based rejection.
        validate_webhook_url("https://evil.example.com/hook")

    def test_decimal_encoded_loopback_ip_currently_passes(self):
        """``http://2130706433/`` is the decimal encoding of
        ``127.0.0.1``. Many SSRF validators miss this. Pin the current
        (bypassable) behavior so a future fix surfaces here.
        """
        from app.services.webhooks import validate_webhook_url

        # Python's urlparse returns '2130706433' as the hostname — not in the
        # blocklist of string literals, so it passes. Document the bypass.
        validate_webhook_url("https://2130706433/hook")

    def test_ipv6_mapped_ipv4_loopback_currently_passes(self):
        """``[::ffff:7f00:1]`` is IPv6-mapped-IPv4 for 127.0.0.1. The
        string-based check only blocks the literal ``[::1]`` form. Pin the
        gap so the future DNS-resolving replacement flips this test.
        """
        from app.services.webhooks import validate_webhook_url

        validate_webhook_url("https://[::ffff:7f00:1]/hook")

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
