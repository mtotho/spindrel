"""Integration tests for api_v1_admin/limits.py — 5 routes.

Phase 3 of the Test Quality track. Real FastAPI + real SQLite DB + real router.
`load_limits()` opens its own async_session (not the one from get_db); it is
patched via the router's bound name so the test DB is not leaked.
`get_limits_status()` reads the in-memory _limits cache; patched per test.

BUG HUNT: update_limit does not guard against an empty body (both limit_usd
and enabled are None). The route still commits a timestamp-only change and
reloads the in-memory cache. Pinned in
test_when_empty_update_body_then_timestamp_changes_but_values_unchanged.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from tests.factories import build_usage_limit
from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio

_LOAD_LIMITS = "app.routers.api_v1_admin.limits.load_limits"
_GET_STATUS = "app.routers.api_v1_admin.limits.get_limits_status"


# ---------------------------------------------------------------------------
# GET /limits/ — list
# ---------------------------------------------------------------------------

class TestListLimits:
    async def test_when_limits_exist_then_all_returned(self, client, db_session):
        model_limit = build_usage_limit(scope_type="model", scope_value="gpt-4o", period="daily")
        bot_limit = build_usage_limit(scope_type="bot", scope_value="assistant", period="monthly")
        db_session.add(model_limit)
        db_session.add(bot_limit)
        await db_session.commit()

        resp = await client.get("/api/v1/admin/limits/", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        ids = {r["id"] for r in resp.json()}
        assert str(model_limit.id) in ids
        assert str(bot_limit.id) in ids

    async def test_when_no_limits_then_empty_list(self, client):
        resp = await client.get("/api/v1/admin/limits/", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# GET /limits/status — in-memory cache readout
# ---------------------------------------------------------------------------

class TestLimitsStatus:
    async def test_when_status_called_then_delegates_to_service(self, client):
        mock_status = [
            {"id": str(uuid.uuid4()), "scope_type": "model", "scope_value": "gpt-4o",
             "period": "daily", "limit_usd": 10.0, "current_spend": 3.5,
             "percentage": 35.0, "enabled": True}
        ]

        with patch(_GET_STATUS, AsyncMock(return_value=mock_status)):
            resp = await client.get("/api/v1/admin/limits/status", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        assert resp.json()[0]["percentage"] == 35.0


# ---------------------------------------------------------------------------
# POST /limits/ — create
# ---------------------------------------------------------------------------

class TestCreateLimit:
    async def test_when_valid_payload_then_201_and_row_persisted(self, client, db_session):
        payload = {"scope_type": "model", "scope_value": "claude-3-opus", "period": "daily", "limit_usd": 50.0}

        with patch(_LOAD_LIMITS, AsyncMock()):
            resp = await client.post("/api/v1/admin/limits/", json=payload, headers=AUTH_HEADERS)

        assert resp.status_code == 201
        body = resp.json()
        assert body["scope_value"] == "claude-3-opus"
        assert body["limit_usd"] == 50.0
        assert body["enabled"] is True

    async def test_when_invalid_scope_type_then_400(self, client):
        payload = {"scope_type": "workspace", "scope_value": "x", "period": "daily", "limit_usd": 1.0}

        resp = await client.post("/api/v1/admin/limits/", json=payload, headers=AUTH_HEADERS)

        assert resp.status_code == 400
        assert "scope_type" in resp.json()["detail"]

    async def test_when_invalid_period_then_400(self, client):
        payload = {"scope_type": "model", "scope_value": "x", "period": "weekly", "limit_usd": 1.0}

        resp = await client.post("/api/v1/admin/limits/", json=payload, headers=AUTH_HEADERS)

        assert resp.status_code == 400
        assert "period" in resp.json()["detail"]

    async def test_when_zero_limit_then_400(self, client):
        payload = {"scope_type": "bot", "scope_value": "bot-1", "period": "monthly", "limit_usd": 0.0}

        resp = await client.post("/api/v1/admin/limits/", json=payload, headers=AUTH_HEADERS)

        assert resp.status_code == 400
        assert "limit_usd" in resp.json()["detail"]

    async def test_when_duplicate_scope_period_then_409(self, client, db_session):
        existing = build_usage_limit(scope_type="bot", scope_value="bot-x", period="daily")
        db_session.add(existing)
        await db_session.commit()

        payload = {"scope_type": "bot", "scope_value": "bot-x", "period": "daily", "limit_usd": 5.0}

        with patch(_LOAD_LIMITS, AsyncMock()):
            resp = await client.post("/api/v1/admin/limits/", json=payload, headers=AUTH_HEADERS)

        assert resp.status_code == 409

    async def test_when_created_then_load_limits_called(self, client, db_session):
        payload = {"scope_type": "model", "scope_value": "ollama/llama3", "period": "monthly", "limit_usd": 0.01}

        mock_load = AsyncMock()
        with patch(_LOAD_LIMITS, mock_load):
            await client.post("/api/v1/admin/limits/", json=payload, headers=AUTH_HEADERS)

        mock_load.assert_called_once()


# ---------------------------------------------------------------------------
# PUT /limits/{id} — update
# ---------------------------------------------------------------------------

class TestUpdateLimit:
    async def test_when_limit_usd_updated_then_persisted(self, client, db_session):
        row = build_usage_limit(limit_usd=10.0)
        db_session.add(row)
        await db_session.commit()

        with patch(_LOAD_LIMITS, AsyncMock()):
            resp = await client.put(
                f"/api/v1/admin/limits/{row.id}",
                json={"limit_usd": 99.5},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        await db_session.refresh(row)
        assert row.limit_usd == 99.5

    async def test_when_enabled_toggled_then_persisted(self, client, db_session):
        row = build_usage_limit(enabled=True)
        db_session.add(row)
        await db_session.commit()

        with patch(_LOAD_LIMITS, AsyncMock()):
            resp = await client.put(
                f"/api/v1/admin/limits/{row.id}",
                json={"enabled": False},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        await db_session.refresh(row)
        assert row.enabled is False

    async def test_when_zero_limit_usd_then_400(self, client, db_session):
        row = build_usage_limit(limit_usd=5.0)
        db_session.add(row)
        await db_session.commit()

        with patch(_LOAD_LIMITS, AsyncMock()):
            resp = await client.put(
                f"/api/v1/admin/limits/{row.id}",
                json={"limit_usd": -1.0},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 400

    async def test_when_limit_missing_then_404(self, client):
        with patch(_LOAD_LIMITS, AsyncMock()):
            resp = await client.put(
                f"/api/v1/admin/limits/{uuid.uuid4()}",
                json={"limit_usd": 10.0},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 404

    async def test_when_invalid_uuid_then_400(self, client):
        with patch(_LOAD_LIMITS, AsyncMock()):
            resp = await client.put(
                "/api/v1/admin/limits/not-a-uuid",
                json={"limit_usd": 10.0},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 400

    async def test_when_empty_update_body_then_timestamp_changes_but_values_unchanged(
        self, client, db_session,
    ):
        """No guard against empty body — route commits a no-op, returning original values."""
        row = build_usage_limit(limit_usd=7.77, enabled=True)
        db_session.add(row)
        await db_session.commit()
        original_updated_at = row.updated_at

        with patch(_LOAD_LIMITS, AsyncMock()):
            resp = await client.put(
                f"/api/v1/admin/limits/{row.id}",
                json={},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["limit_usd"] == 7.77
        assert body["enabled"] is True
        await db_session.refresh(row)
        assert row.updated_at >= original_updated_at  # timestamp may change


# ---------------------------------------------------------------------------
# DELETE /limits/{id} — delete
# ---------------------------------------------------------------------------

class TestDeleteLimit:
    async def test_when_limit_exists_then_deleted_and_sibling_survives(self, client, db_session):
        target = build_usage_limit()
        sibling = build_usage_limit()
        db_session.add(target)
        db_session.add(sibling)
        await db_session.commit()
        target_id = target.id

        with patch(_LOAD_LIMITS, AsyncMock()):
            resp = await client.delete(
                f"/api/v1/admin/limits/{target_id}", headers=AUTH_HEADERS,
            )

        assert resp.status_code == 204
        gone = await db_session.get(type(target), target_id)
        assert gone is None
        assert await db_session.get(type(sibling), sibling.id) is not None

    async def test_when_limit_missing_then_404(self, client):
        with patch(_LOAD_LIMITS, AsyncMock()):
            resp = await client.delete(
                f"/api/v1/admin/limits/{uuid.uuid4()}", headers=AUTH_HEADERS,
            )

        assert resp.status_code == 404

    async def test_when_invalid_uuid_then_400(self, client):
        with patch(_LOAD_LIMITS, AsyncMock()):
            resp = await client.delete(
                "/api/v1/admin/limits/not-a-uuid", headers=AUTH_HEADERS,
            )

        assert resp.status_code == 400
