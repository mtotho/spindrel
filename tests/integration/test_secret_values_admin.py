"""Integration tests for api_v1_admin/secret_values.py — 5 routes.

Phase 3 of the Test Quality track. Real FastAPI + real SQLite DB + real router.

Encryption: without ENCRYPTION_KEY set (test env), encrypt() is a passthrough
and decrypt() passes through too. So `row.value` stores plaintext in tests.

`_rebuild_registry()` is patched in every mutating test to avoid pulling in
the real secret_registry (which has its own DB session + redaction state).
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.db.models import SecretValue
from tests.factories import build_secret_value
from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio

_REBUILD = "app.services.secret_values._rebuild_registry"


# ---------------------------------------------------------------------------
# GET /secret-values/ — list
# ---------------------------------------------------------------------------

class TestListSecretValues:
    async def test_when_secrets_exist_then_all_returned_without_plaintext(
        self, client, db_session,
    ):
        s1 = build_secret_value(name="API_KEY_ONE")
        s2 = build_secret_value(name="API_KEY_TWO")
        db_session.add(s1)
        db_session.add(s2)
        await db_session.commit()

        resp = await client.get("/api/v1/admin/secret-values/", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        names = {r["name"] for r in resp.json()}
        assert {"API_KEY_ONE", "API_KEY_TWO"} <= names
        for r in resp.json():
            assert "value" not in r  # plaintext is never returned
            assert "has_value" in r

    async def test_when_no_secrets_then_empty_list(self, client):
        resp = await client.get("/api/v1/admin/secret-values/", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# POST /secret-values/ — create
# ---------------------------------------------------------------------------

class TestCreateSecretValue:
    async def test_when_valid_payload_then_201_and_row_persisted(self, client, db_session):
        payload = {"name": "MY_API_TOKEN", "value": "super-secret-123"}

        with patch(_REBUILD, AsyncMock()):
            resp = await client.post("/api/v1/admin/secret-values/", json=payload, headers=AUTH_HEADERS)

        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "MY_API_TOKEN"
        assert body["has_value"] is True
        assert "value" not in body

    async def test_when_invalid_name_format_then_422(self, client):
        payload = {"name": "123-invalid", "value": "x"}

        resp = await client.post("/api/v1/admin/secret-values/", json=payload, headers=AUTH_HEADERS)

        assert resp.status_code == 422

    async def test_when_name_starts_with_digit_then_422(self, client):
        payload = {"name": "1_BAD_NAME", "value": "x"}

        resp = await client.post("/api/v1/admin/secret-values/", json=payload, headers=AUTH_HEADERS)

        assert resp.status_code == 422

    async def test_when_duplicate_name_then_409(self, client, db_session):
        existing = build_secret_value(name="EXISTING_SECRET")
        db_session.add(existing)
        await db_session.commit()

        payload = {"name": "EXISTING_SECRET", "value": "new-value"}

        with patch(_REBUILD, AsyncMock()):
            resp = await client.post("/api/v1/admin/secret-values/", json=payload, headers=AUTH_HEADERS)

        assert resp.status_code == 409
        assert "EXISTING_SECRET" in resp.json()["detail"]

    async def test_when_created_then_registry_rebuild_called(self, client, db_session):
        payload = {"name": "REBUILD_TEST_KEY", "value": "val"}

        mock_rebuild = AsyncMock()
        with patch(_REBUILD, mock_rebuild):
            await client.post("/api/v1/admin/secret-values/", json=payload, headers=AUTH_HEADERS)

        mock_rebuild.assert_called_once()


# ---------------------------------------------------------------------------
# GET /secret-values/{id} — get single
# ---------------------------------------------------------------------------

class TestGetSecretValue:
    async def test_when_exists_then_returns_without_plaintext(self, client, db_session):
        row = build_secret_value(name="SINGLE_SECRET", description="My key")
        db_session.add(row)
        await db_session.commit()

        resp = await client.get(f"/api/v1/admin/secret-values/{row.id}", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "SINGLE_SECRET"
        assert body["description"] == "My key"
        assert body["has_value"] is True
        assert "value" not in body

    async def test_when_missing_then_404(self, client):
        resp = await client.get(
            f"/api/v1/admin/secret-values/{uuid.uuid4()}", headers=AUTH_HEADERS,
        )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /secret-values/{id} — update
# ---------------------------------------------------------------------------

class TestUpdateSecretValue:
    async def test_when_value_updated_then_has_value_true(self, client, db_session):
        row = build_secret_value(name="UPDATE_ME")
        db_session.add(row)
        await db_session.commit()

        with patch(_REBUILD, AsyncMock()):
            resp = await client.put(
                f"/api/v1/admin/secret-values/{row.id}",
                json={"value": "new-secret-value"},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["has_value"] is True

    async def test_when_description_updated_then_persisted(self, client, db_session):
        row = build_secret_value(description="old desc")
        db_session.add(row)
        await db_session.commit()

        with patch(_REBUILD, AsyncMock()):
            resp = await client.put(
                f"/api/v1/admin/secret-values/{row.id}",
                json={"description": "new desc"},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["description"] == "new desc"

    async def test_when_renamed_then_name_updated_in_db(self, client, db_session):
        row = build_secret_value(name="OLD_NAME_123")
        db_session.add(row)
        await db_session.commit()

        with patch(_REBUILD, AsyncMock()):
            resp = await client.put(
                f"/api/v1/admin/secret-values/{row.id}",
                json={"name": "NEW_NAME_456"},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        await db_session.refresh(row)
        assert row.name == "NEW_NAME_456"

    async def test_when_missing_then_404(self, client):
        with patch(_REBUILD, AsyncMock()):
            resp = await client.put(
                f"/api/v1/admin/secret-values/{uuid.uuid4()}",
                json={"description": "ghost"},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /secret-values/{id} — delete
# ---------------------------------------------------------------------------

class TestDeleteSecretValue:
    async def test_when_exists_then_deleted_and_sibling_survives(self, client, db_session):
        target = build_secret_value(name="DELETE_TARGET_A")
        sibling = build_secret_value(name="SIBLING_B")
        db_session.add(target)
        db_session.add(sibling)
        await db_session.commit()
        target_id = target.id

        with patch(_REBUILD, AsyncMock()):
            resp = await client.delete(
                f"/api/v1/admin/secret-values/{target_id}", headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        gone = await db_session.execute(
            select(SecretValue).where(SecretValue.id == target_id)
        )
        assert gone.scalar_one_or_none() is None
        assert await db_session.get(SecretValue, sibling.id) is not None

    async def test_when_missing_then_404(self, client):
        with patch(_REBUILD, AsyncMock()):
            resp = await client.delete(
                f"/api/v1/admin/secret-values/{uuid.uuid4()}", headers=AUTH_HEADERS,
            )

        assert resp.status_code == 404
