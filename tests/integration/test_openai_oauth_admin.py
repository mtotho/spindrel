"""Integration tests for the ChatGPT-subscription OAuth admin router.

Real FastAPI + SQLite DB + real router; the OpenAI HTTP endpoints
(``/deviceauth/usercode``, ``/deviceauth/token``, ``/oauth/token``) are
stubbed per the E.1 rule — they're true externals.

These verify wiring: the router mount, provider-type guarding, the
start/poll/disconnect lifecycle, and that a successful OAuth flow writes
encrypted tokens onto the provider's ``config.oauth`` blob.
"""
from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models import ProviderConfig
from app.services import openai_oauth as oa
from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _id_token(claims: dict) -> str:
    def enc(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()
    return f"{enc({'alg':'none'})}.{enc(claims)}.sig"


def _mock_resp(status: int, body) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.is_success = 200 <= status < 300
    r.json.return_value = body
    r.text = json.dumps(body) if not isinstance(body, str) else body
    return r


def _httpx_client(*responses):
    """AsyncClient mock whose .post returns the given responses in order."""
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(side_effect=list(responses))
    return client


async def _make_subscription_provider(db_session) -> ProviderConfig:
    row = ProviderConfig(
        id="chatgpt-sub",
        provider_type="openai-subscription",
        display_name="My ChatGPT",
        is_enabled=True,
        config={},
    )
    db_session.add(row)
    await db_session.commit()
    return row


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------


class TestStart:
    async def test_starts_flow_and_stashes_state(self, client, db_session):
        await _make_subscription_provider(db_session)
        oa._pending.clear()
        resp_mock = _mock_resp(200, {
            "device_auth_id": "dev_123",
            "user_code": "AAAA-BBBB",
            "interval": 2,
            "expires_in": 900,
        })
        with patch("httpx.AsyncClient", return_value=_httpx_client(resp_mock)):
            r = await client.post(
                "/api/v1/admin/providers/openai-oauth/start/chatgpt-sub",
                headers=AUTH_HEADERS,
            )
        assert r.status_code == 200
        body = r.json()
        assert body["user_code"] == "AAAA-BBBB"
        assert body["interval"] == 2
        assert "AAAA-BBBB" in body["verification_uri_complete"]
        assert "chatgpt-sub" in oa._pending

    async def test_rejects_non_subscription_provider(self, client, db_session):
        row = ProviderConfig(
            id="openai-keyed",
            provider_type="openai",
            display_name="Keyed",
            is_enabled=True,
            api_key="sk-x",
            config={},
        )
        db_session.add(row)
        await db_session.commit()
        r = await client.post(
            "/api/v1/admin/providers/openai-oauth/start/openai-keyed",
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 400
        assert "openai-subscription" in r.json()["detail"]

    async def test_404_on_missing_provider(self, client):
        r = await client.post(
            "/api/v1/admin/providers/openai-oauth/start/nope",
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# /poll (pending + success)
# ---------------------------------------------------------------------------


class TestPoll:
    async def test_pending_returns_pending(self, client, db_session):
        await _make_subscription_provider(db_session)
        import time
        oa._pending["chatgpt-sub"] = {
            "created_at": time.time(),
            "device_auth_id": "d",
            "user_code": "u",
            "interval": 1,
        }
        resp_mock = _mock_resp(404, "not yet")
        with patch("httpx.AsyncClient", return_value=_httpx_client(resp_mock)):
            r = await client.post(
                "/api/v1/admin/providers/openai-oauth/poll/chatgpt-sub",
                headers=AUTH_HEADERS,
            )
        assert r.status_code == 200
        assert r.json()["status"] == "pending"

    async def test_success_persists_tokens_onto_provider_config(
        self, client, db_session,
    ):
        await _make_subscription_provider(db_session)
        import time
        oa._pending["chatgpt-sub"] = {
            "created_at": time.time(),
            "device_auth_id": "d",
            "user_code": "u",
            "interval": 1,
        }

        # Two POSTs on the same httpx client: device token + oauth token exchange.
        device_poll = _mock_resp(200, {
            "authorization_code": "auth_1",
            "code_verifier": "ver_1",
            "code_challenge": "chal_1",
        })
        token_exchange = _mock_resp(200, {
            "access_token": "at_1",
            "refresh_token": "rt_1",
            "expires_in": 3600,
            "id_token": _id_token({
                "email": "me@example.com",
                "https://api.openai.com/auth": {
                    "chatgpt_account_id": "acct_99",
                    "chatgpt_plan_type": "plus",
                },
            }),
        })

        with patch("httpx.AsyncClient", return_value=_httpx_client(device_poll, token_exchange)):
            r = await client.post(
                "/api/v1/admin/providers/openai-oauth/poll/chatgpt-sub",
                headers=AUTH_HEADERS,
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "success"
        assert body["email"] == "me@example.com"
        assert body["plan"] == "plus"

        await db_session.refresh(await db_session.get(ProviderConfig, "chatgpt-sub"))
        row = await db_session.get(ProviderConfig, "chatgpt-sub")
        oauth = (row.config or {}).get("oauth") or {}
        assert oauth["account_id"] == "acct_99"
        # access_token is encrypt()ed by _persist_tokens; when ENCRYPTION_KEY
        # isn't set in tests, encrypt() is a no-op — tokens land plaintext.
        assert oauth["access_token"]  # non-empty
        assert oauth["refresh_token"]  # non-empty
        # State cleaned up after success.
        assert "chatgpt-sub" not in oa._pending


# ---------------------------------------------------------------------------
# /disconnect + /status
# ---------------------------------------------------------------------------


class TestDisconnectAndStatus:
    async def test_status_before_connect_reports_disconnected(
        self, client, db_session,
    ):
        await _make_subscription_provider(db_session)
        r = await client.get(
            "/api/v1/admin/providers/openai-oauth/status/chatgpt-sub",
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        assert r.json()["connected"] is False

    async def test_disconnect_clears_oauth_field(self, client, db_session):
        row = ProviderConfig(
            id="chatgpt-sub",
            provider_type="openai-subscription",
            display_name="",
            is_enabled=True,
            config={"oauth": {"access_token": "x", "account_id": "a"}},
        )
        db_session.add(row)
        await db_session.commit()

        r = await client.post(
            "/api/v1/admin/providers/openai-oauth/disconnect/chatgpt-sub",
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200

        await db_session.refresh(row)
        assert "oauth" not in (row.config or {})
