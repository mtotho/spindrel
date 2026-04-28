"""Tests for DB-backed webhook service: cache, event filtering, HMAC, delivery, retry."""
import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.webhooks import (
    EVENT_REGISTRY,
    _RETRY_DELAYS,
    _deliver,
    _endpoints_cache,
    emit_webhooks,
    generate_secret,
    invalidate_cache,
    sign_payload,
    validate_webhook_url,
    verify_signature,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_cache():
    """Reset the endpoint cache before/after each test."""
    import app.services.webhooks as mod
    saved_cache = list(mod._endpoints_cache)
    saved_loaded = mod._cache_loaded
    mod._endpoints_cache.clear()
    mod._cache_loaded = False
    yield
    mod._endpoints_cache.clear()
    mod._endpoints_cache.extend(saved_cache)
    mod._cache_loaded = saved_loaded


@pytest.fixture(autouse=True)
def _allow_public_urls(monkeypatch):
    async def _ok(_url: str) -> None:
        return None

    monkeypatch.setattr("app.services.webhooks.assert_public_url", _ok)


def _make_endpoint(events=None, url="https://example.com/hook", secret="testsecret"):
    return {
        "id": uuid.uuid4(),
        "url": url,
        "secret": secret,
        "events": events or [],
    }


# ---------------------------------------------------------------------------
# HMAC signing
# ---------------------------------------------------------------------------

class TestHMACSigning:
    def test_sign_and_verify_roundtrip(self):
        secret = generate_secret()
        body = b'{"event":"test"}'
        timestamp = "1800000000"
        sig = sign_payload(body, secret, timestamp)
        with patch("app.services.webhooks.time.time", return_value=1800000000):
            assert verify_signature(body, secret, sig, timestamp)

    def test_wrong_secret_fails(self):
        body = b'{"event":"test"}'
        timestamp = "1800000000"
        sig = sign_payload(body, "secret-a", timestamp)
        with patch("app.services.webhooks.time.time", return_value=1800000000):
            assert not verify_signature(body, "secret-b", sig, timestamp)

    def test_tampered_body_fails(self):
        secret = "my-secret"
        timestamp = "1800000000"
        sig = sign_payload(b'{"event":"test"}', secret, timestamp)
        with patch("app.services.webhooks.time.time", return_value=1800000000):
            assert not verify_signature(b'{"event":"tampered"}', secret, sig, timestamp)

    def test_stale_timestamp_fails(self):
        secret = "my-secret"
        body = b'{"event":"test"}'
        sig = sign_payload(body, secret, "1800000000")
        with patch("app.services.webhooks.time.time", return_value=1800000400):
            assert not verify_signature(body, secret, sig, "1800000000")

    def test_generate_secret_length(self):
        s = generate_secret()
        assert len(s) == 64
        assert all(c in "0123456789abcdef" for c in s)


# ---------------------------------------------------------------------------
# Event filtering
# ---------------------------------------------------------------------------

class TestEventFiltering:
    @pytest.mark.asyncio
    async def test_empty_events_matches_all(self):
        """Endpoint with empty events list receives all events."""
        ep = _make_endpoint(events=[])
        import app.services.webhooks as mod
        mod._endpoints_cache.append(ep)
        mod._cache_loaded = True

        with patch("app.services.webhooks._deliver", new_callable=AsyncMock) as mock_deliver:
            await emit_webhooks("after_response", {"event": "after_response"})
            await asyncio.sleep(0)
            mock_deliver.assert_called_once_with(ep, "after_response", {"event": "after_response"})

    @pytest.mark.asyncio
    async def test_specific_events_filter(self):
        """Endpoint with specific events only receives matching events."""
        ep = _make_endpoint(events=["after_response", "after_tool_call"])
        import app.services.webhooks as mod
        mod._endpoints_cache.append(ep)
        mod._cache_loaded = True

        with patch("app.services.webhooks._deliver", new_callable=AsyncMock) as mock_deliver:
            # Should match
            await emit_webhooks("after_response", {"event": "after_response"})
            await asyncio.sleep(0)
            assert mock_deliver.call_count == 1

            mock_deliver.reset_mock()

            # Should not match
            await emit_webhooks("before_llm_call", {"event": "before_llm_call"})
            await asyncio.sleep(0)
            mock_deliver.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_endpoints_filtering(self):
        """Multiple endpoints each apply their own event filter."""
        ep_all = _make_endpoint(events=[], url="https://all.example.com/hook")
        ep_filtered = _make_endpoint(events=["after_response"], url="https://filtered.example.com/hook")

        import app.services.webhooks as mod
        mod._endpoints_cache.extend([ep_all, ep_filtered])
        mod._cache_loaded = True

        with patch("app.services.webhooks._deliver", new_callable=AsyncMock) as mock_deliver:
            await emit_webhooks("before_llm_call", {"event": "before_llm_call"})
            await asyncio.sleep(0)

            # Only the "all" endpoint should be called
            assert mock_deliver.call_count == 1
            assert mock_deliver.call_args_list[0].args[0] == ep_all


# ---------------------------------------------------------------------------
# Cache loading + invalidation
# ---------------------------------------------------------------------------

class TestCache:
    @pytest.mark.asyncio
    async def test_invalidate_clears_cache(self):
        import app.services.webhooks as mod
        mod._endpoints_cache.append(_make_endpoint())
        mod._cache_loaded = True

        invalidate_cache()
        assert len(mod._endpoints_cache) == 0
        assert mod._cache_loaded is False


# ---------------------------------------------------------------------------
# Delivery with retry
# ---------------------------------------------------------------------------

class TestDelivery:
    @pytest.mark.asyncio
    async def test_successful_delivery(self):
        """Successful POST records delivery with status 200."""
        ep = _make_endpoint()
        payload = {"event": "test", "data": {}}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        mock_session = AsyncMock()
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.webhooks._get_http_client", return_value=mock_client), \
             patch("app.services.webhooks.async_session", return_value=mock_session):
            await _deliver(ep, "test", payload)

        mock_client.post.assert_called_once()
        # Verify headers include signature and event
        call_kwargs = mock_client.post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert "X-Spindrel-Signature" in headers
        assert "X-Spindrel-Timestamp" in headers
        assert headers["X-Spindrel-Event"] == "test"

    @pytest.mark.asyncio
    async def test_retry_on_5xx(self):
        """5xx responses trigger retry attempts."""
        ep = _make_endpoint()
        payload = {"event": "test", "data": {}}

        # First two calls return 500, third returns 200
        mock_500 = MagicMock()
        mock_500.status_code = 500
        mock_500.text = "Internal Server Error"

        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.text = "OK"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[mock_500, mock_500, mock_200])

        mock_session = AsyncMock()
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.webhooks._get_http_client", return_value=mock_client), \
             patch("app.services.webhooks.async_session", return_value=mock_session), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await _deliver(ep, "test", payload)

        assert mock_client.post.call_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_4xx(self):
        """4xx responses do not trigger retry."""
        ep = _make_endpoint()
        payload = {"event": "test", "data": {}}

        mock_404 = MagicMock()
        mock_404.status_code = 404
        mock_404.text = "Not Found"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_404)

        mock_session = AsyncMock()
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.webhooks._get_http_client", return_value=mock_client), \
             patch("app.services.webhooks.async_session", return_value=mock_session):
            await _deliver(ep, "test", payload)

        # Should not retry on client error
        assert mock_client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_connection_error(self):
        """Connection errors trigger retry."""
        ep = _make_endpoint()
        payload = {"event": "test", "data": {}}

        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.text = "OK"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[
            ConnectionError("refused"),
            ConnectionError("refused"),
            mock_200,
        ])

        mock_session = AsyncMock()
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.webhooks._get_http_client", return_value=mock_client), \
             patch("app.services.webhooks.async_session", return_value=mock_session), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await _deliver(ep, "test", payload)

        assert mock_client.post.call_count == 3


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------

class TestURLValidation:
    @pytest.mark.asyncio
    async def test_valid_https_url(self, monkeypatch):
        called: list[str] = []

        async def _ok(url: str) -> None:
            called.append(url)

        monkeypatch.setattr("app.services.webhooks.assert_public_url", _ok)
        await validate_webhook_url("https://example.com/hook")
        assert called == ["https://example.com/hook"]

    @pytest.mark.asyncio
    async def test_valid_http_url(self, monkeypatch):
        called: list[str] = []

        async def _ok(url: str) -> None:
            called.append(url)

        monkeypatch.setattr("app.services.webhooks.assert_public_url", _ok)
        await validate_webhook_url("http://example.com/hook")
        assert called == ["http://example.com/hook"]

    @pytest.mark.asyncio
    async def test_reject_unsafe_url(self, monkeypatch):
        from app.services.url_safety import UnsafePublicURLError

        async def _blocked(url: str) -> None:
            raise UnsafePublicURLError("Host resolves to non-public address: 127.0.0.1")

        monkeypatch.setattr("app.services.webhooks.assert_public_url", _blocked)
        with pytest.raises(ValueError, match="non-public"):
            await validate_webhook_url("https://127.0.0.1/hook")


# ---------------------------------------------------------------------------
# Event registry
# ---------------------------------------------------------------------------

class TestEventRegistry:
    def test_all_events_have_descriptions(self):
        for event, desc in EVENT_REGISTRY.items():
            assert isinstance(event, str)
            assert isinstance(desc, str)
            assert len(desc) > 0

    def test_expected_events_present(self):
        expected = {"after_response", "after_tool_call", "after_llm_call", "before_llm_call"}
        assert expected.issubset(set(EVENT_REGISTRY.keys()))
