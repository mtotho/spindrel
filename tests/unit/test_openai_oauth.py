"""Tests for the ChatGPT subscription OAuth service (device-code + refresh)."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import openai_oauth as oa


# ---------------------------------------------------------------------------
# ID-token claim parsing
# ---------------------------------------------------------------------------


def _make_id_token(claims: dict) -> str:
    """Fabricate an unverifiable JWT for tests — header/sig don't matter."""
    def enc(obj):
        raw = json.dumps(obj).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    return f"{enc({'alg':'none'})}.{enc(claims)}.sig"


class TestClaimExtraction:
    def test_extracts_email_and_plan(self):
        tok = _make_id_token({
            "email": "me@example.com",
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "acct_abc",
                "chatgpt_plan_type": "plus",
            },
        })
        info = oa._extract_account_info(tok)
        assert info == {"email": "me@example.com", "account_id": "acct_abc", "plan": "plus"}

    def test_missing_claim_returns_empty(self):
        assert oa._extract_account_info("not-a-jwt") == {}

    def test_partial_claims_tolerated(self):
        tok = _make_id_token({"email": "x@y.com"})
        info = oa._extract_account_info(tok)
        assert info["email"] == "x@y.com"
        assert info["account_id"] == ""
        assert info["plan"] == ""


# ---------------------------------------------------------------------------
# Token persistence + decrypt round-trip
# ---------------------------------------------------------------------------


class TestDecryptOauthFields:
    def test_plaintext_passthrough_when_not_encrypted(self):
        # When ENCRYPTION_KEY is not set, encrypt() returns plaintext, so
        # decrypt should also pass through. Ensures we don't crash on
        # servers that haven't enabled encryption.
        config = {
            "oauth": {
                "access_token": "plaintext_at",
                "refresh_token": "plaintext_rt",
                "expires_at": "2026-05-19T00:00:00+00:00",
                "account_id": "acct",
            }
        }
        out = oa.decrypt_oauth_fields(config)
        assert out["oauth"]["access_token"] == "plaintext_at"
        assert out["oauth"]["refresh_token"] == "plaintext_rt"
        # Doesn't clobber non-secret fields.
        assert out["oauth"]["account_id"] == "acct"

    def test_missing_oauth_is_noop(self):
        assert oa.decrypt_oauth_fields({"other": 1}) == {"other": 1}


# ---------------------------------------------------------------------------
# Device-code flow
# ---------------------------------------------------------------------------


def _mock_httpx(response_map):
    """Patch httpx.AsyncClient so any POST/GET returns a canned response.

    response_map is ``{method: MagicMock_response}`` or a single MagicMock
    if all calls should return the same response.
    """
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    if isinstance(response_map, dict):
        if "post" in response_map:
            client.post = AsyncMock(return_value=response_map["post"])
        if "get" in response_map:
            client.get = AsyncMock(return_value=response_map["get"])
    else:
        client.post = AsyncMock(return_value=response_map)
        client.get = AsyncMock(return_value=response_map)
    return client


def _mock_response(status: int, body) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.is_success = 200 <= status < 300
    r.json.return_value = body
    r.text = json.dumps(body) if not isinstance(body, str) else body
    return r


class TestStartDeviceFlow:
    @pytest.mark.asyncio
    async def test_start_returns_user_code_and_stashes_state(self):
        # Clear any leftover state from previous tests.
        oa._pending.clear()
        resp = _mock_response(200, {
            "device_auth_id": "dev_1",
            "user_code": "ABCD-1234",
            "interval": 3,
            "expires_in": 900,
        })
        with patch("httpx.AsyncClient", return_value=_mock_httpx(resp)):
            result = await oa.start_device_flow("prov_a")

        assert result["user_code"] == "ABCD-1234"
        assert result["interval"] == 3
        assert result["verification_uri"] == "https://auth.openai.com/codex/device"
        assert "user_code=ABCD-1234" in result["verification_uri_complete"]
        # State stashed for later polls.
        assert oa._pending["prov_a"]["device_auth_id"] == "dev_1"

    @pytest.mark.asyncio
    async def test_start_raises_on_server_error(self):
        oa._pending.clear()
        resp = _mock_response(500, "boom")
        with patch("httpx.AsyncClient", return_value=_mock_httpx(resp)):
            with pytest.raises(RuntimeError, match="Device code request failed"):
                await oa.start_device_flow("prov_a")


class TestPollOnce:
    @pytest.mark.asyncio
    async def test_pending_returns_pending_dict(self):
        oa._pending["prov"] = {
            "created_at": 0,  # fresh-ish (under TTL check via monkeypatch below)
            "device_auth_id": "dev",
            "user_code": "x",
            "interval": 1,
        }
        # Force created_at within TTL.
        oa._pending["prov"]["created_at"] = __import__("time").time()
        resp = _mock_response(404, "pending")
        with patch("httpx.AsyncClient", return_value=_mock_httpx(resp)):
            out = await oa.poll_once("prov")
        assert out == {"status": "pending"}

    @pytest.mark.asyncio
    async def test_expired_flow_cleans_up_and_raises(self):
        oa._pending["prov"] = {
            "created_at": __import__("time").time() - (oa._STATE_TTL_SECONDS + 10),
            "device_auth_id": "dev", "user_code": "x", "interval": 1,
        }
        with pytest.raises(RuntimeError, match="expired"):
            await oa.poll_once("prov")
        assert "prov" not in oa._pending

    @pytest.mark.asyncio
    async def test_success_triggers_token_exchange_and_persist(self):
        # On the 2nd POST (token exchange) return a token payload. We use
        # separate _mock_response objects for each call.
        oa._pending["prov"] = {
            "created_at": __import__("time").time(),
            "device_auth_id": "dev", "user_code": "x", "interval": 1,
        }

        device_poll = _mock_response(200, {
            "authorization_code": "auth_1",
            "code_verifier": "verif_1",
            "code_challenge": "chal_1",
        })
        token_exchange = _mock_response(200, {
            "access_token": "access_1",
            "refresh_token": "refresh_1",
            "expires_in": 3600,
            "id_token": _make_id_token({
                "email": "u@e.com",
                "https://api.openai.com/auth": {
                    "chatgpt_account_id": "acct_1",
                    "chatgpt_plan_type": "plus",
                },
            }),
        })

        client = AsyncMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.post = AsyncMock(side_effect=[device_poll, token_exchange])

        persisted: dict = {}
        async def _fake_persist(pid, payload):
            persisted["pid"] = pid
            persisted["payload"] = payload

        with patch("httpx.AsyncClient", return_value=client):
            with patch("app.services.openai_oauth._persist_tokens", _fake_persist):
                out = await oa.poll_once("prov")

        assert out == {"status": "success", "email": "u@e.com", "plan": "plus"}
        assert persisted["pid"] == "prov"
        assert persisted["payload"]["access_token"] == "access_1"


# ---------------------------------------------------------------------------
# Refresh path
# ---------------------------------------------------------------------------


class TestLoadAndRefresh:
    @pytest.mark.asyncio
    async def test_fresh_token_no_refresh(self):
        provider = MagicMock()
        provider.id = "p"
        provider.config = {
            "oauth": {
                "access_token": "current",
                "refresh_token": "refresh",
                "account_id": "acct",
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            }
        }

        async def _should_not_call():  # pragma: no cover
            raise AssertionError("refresh should not fire")

        with patch("app.services.openai_oauth._refresh_access_token", _should_not_call):
            out = await oa.load_and_refresh_tokens(provider)
        assert out["access_token"] == "current"
        assert out["account_id"] == "acct"

    @pytest.mark.asyncio
    async def test_expiring_token_triggers_refresh(self):
        provider = MagicMock()
        provider.id = "p"
        provider.config = {
            "oauth": {
                "access_token": "stale",
                "refresh_token": "rt",
                "account_id": "acct",
                # Within the leeway window — should refresh.
                "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(),
            }
        }

        refreshed_payload = {
            "access_token": "new_at",
            "refresh_token": "new_rt",
            "expires_in": 3600,
            "id_token": _make_id_token({
                "https://api.openai.com/auth": {"chatgpt_account_id": "acct"},
            }),
        }

        async def _fake_refresh(rt):
            assert rt == "rt"
            return refreshed_payload

        persisted: dict = {}

        async def _fake_persist(pid, payload):
            persisted["payload"] = payload
            # Mutate the provider so the post-refresh re-read sees new tokens.
            provider.config["oauth"]["access_token"] = payload["access_token"]
            provider.config["oauth"]["expires_at"] = (
                datetime.now(timezone.utc) + timedelta(hours=1)
            ).isoformat()

        with patch("app.services.openai_oauth._refresh_access_token", _fake_refresh):
            with patch("app.services.openai_oauth._persist_tokens", _fake_persist):
                out = await oa.load_and_refresh_tokens(provider)
        assert out["access_token"] == "new_at"
        assert persisted["payload"]["access_token"] == "new_at"

    @pytest.mark.asyncio
    async def test_no_access_token_raises(self):
        provider = MagicMock()
        provider.id = "p"
        provider.config = {}
        with pytest.raises(RuntimeError, match="has no OAuth token"):
            await oa.load_and_refresh_tokens(provider)
